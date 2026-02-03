#!/usr/bin/env python3
# Copyright (c) 2025, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

import argparse
import hashlib
import os
import platform
import re
import subprocess
import tempfile
import time
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import termcolor
import yaml


# -----------------------------------------------------------------------------
# Utility functions
# -----------------------------------------------------------------------------
def extract_env_vars(source_filepath, keys=None):
    if not os.path.exists(source_filepath):
        return None

    try:
        _, output, _ = run_shell(
            f"bash -c 'set -a && source {source_filepath} && env'",
            capture_output=True,
            check=True
        )
    except subprocess.CalledProcessError:
        return None

    env_values_by_key = {}
    for line in output.splitlines():
        key, _, value = line.partition("=")
        if keys is None or key in keys:
            env_values_by_key[key] = value

    # Check for bash arrays for any remaining keys
    for key in keys:
        if key not in env_values_by_key:
            _, output, _ = run_shell(
                f"bash -c 'source {source_filepath} && echo ${{{key}[@]}}'",
                capture_output=True
            )
            env_values_by_key[key] = output.strip().rstrip().split(" ")
    return env_values_by_key


def run_shell(command: str,
              capture_output=True,
              verbose=False,
              check=False,
              env=None) -> Tuple[bool, str, str]:
    """Run a shell command in a subprocess and return the result."""
    if verbose:
        termcolor.cprint(command, "yellow", attrs=["bold"], flush=True)

    os_env = os.environ.copy()
    if env:
        os_env.update(env)
    # Always run with check=False so we can surface stdout/stderr before raising.
    completed_process = subprocess.run(
        command,
        capture_output=capture_output,
        text=True,
        check=False,
        shell=True,
        env=os_env,
    )
    if check and completed_process.returncode != 0:
        # When capture_output=True (default), Jenkins would otherwise show only the
        # CalledProcessError without the real underlying stderr. Print both streams
        # to make failures debuggable (e.g. `docker buildx create --driver kubernetes`).
        if capture_output:
            if completed_process.stdout:
                termcolor.cprint("STDOUT:", "red", attrs=["bold"])
                print(completed_process.stdout, flush=True)
            if completed_process.stderr:
                termcolor.cprint("STDERR:", "red", attrs=["bold"])
                print(completed_process.stderr, flush=True)
        raise subprocess.CalledProcessError(
            completed_process.returncode,
            completed_process.args,
            output=completed_process.stdout,
            stderr=completed_process.stderr,
        )
    return (completed_process.returncode == 0,
            completed_process.stdout,
            completed_process.stderr)


def docker_login(base_docker_registry_name):
    """
    Attempts to log in to a Docker registry using the provided registry name.
    """
    try:
        subprocess.run(
            ['docker', 'login', base_docker_registry_name,
             '--username', '', '--password', ''],
            check=True,
            shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError:
        print(f"Could not login to {base_docker_registry_name}")
        return False


def check_docker_logins(base_docker_registry_names, fail_on_anon):
    """
    Checks login status of specified Docker registries.
    """
    for base_docker_registry_name in base_docker_registry_names:
        if docker_login(base_docker_registry_name):
            print(f"Logged in to {base_docker_registry_name}. Using this for cache.")
            return base_docker_registry_name
        print(f"Could not login to {base_docker_registry_name}.")
    if fail_on_anon:
        raise Exception(
            'Could not login to any of the specified docker registries.'
        )
    return None


def calculate_md5(filename):
    hash_md5 = hashlib.md5()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def redact_bake_hcl(hcl_text: str) -> str:
    """Redact inline AWS credentials from docker buildx bake HCL output."""
    if not hcl_text:
        return hcl_text
    redactions = [
        (r"(access_key_id=)([^\",]+)", r"\1***"),
        (r"(secret_access_key=)([^\",]+)", r"\1***"),
        (r"(session_token=)([^\",]+)", r"\1***"),
    ]
    redacted = hcl_text
    for pattern, replacement in redactions:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


# -----------------------------------------------------------------------------
# Classes used in image building
# -----------------------------------------------------------------------------
class ImageKey:
    def __init__(self, image_key_list: List[str]):
        self.image_keys_ = image_key_list

    def __str__(self):
        return ".".join(self.image_keys_)

    @classmethod
    def from_key_set(cls, image_key_set, key_order=None):
        import functools
        key_order = key_order or []

        def compare_image_keys(a, b):
            if a in key_order and b in key_order:
                return -1 if key_order.index(a) < key_order.index(b) else 1
            elif a in key_order:
                return -1
            elif b in key_order:
                return 1
            else:
                return -1 if a < b else 1

        return cls(sorted(image_key_set, key=functools.cmp_to_key(compare_image_keys)))

    @classmethod
    def from_string(cls, image_key_str):
        return cls(image_key_str.split("."))


class Config:
    def __init__(self, platform_):
        self.target_image_name_ = None
        self.image_key_order_ = None
        self.docker_search_dirs_ = []
        self.cache_to_registry_names_ = []
        self.cache_from_registry_names_ = []
        self.remote_builder_ = None
        self.build_args_ = {}
        self.verbose_ = False
        self.platform_ = platform_
        self.base_image_ = None
        self.context_dir_ = None
        self.common_config_file_ = None
        self.context_overrides_ = {}
        self.s3_cache_ = None

    def load_shell_common_config(self):
        """
        Load shell common config from .isaac_ros_common-config file.
        """
        # Get the directory of the current script
        current_dir = os.path.dirname(os.path.abspath(__file__))

        # Define potential config file locations
        config_locations = [
            os.path.expandvars("$ISAAC_ROS_WS/../scripts/.isaac_ros_common-config"),
            # scripts/isaac-ros-cli/config/
            os.path.join(current_dir, '..', '..', '..',
                         '.isaac_ros_common-config'),
            # scripts/isaac-ros-cli/config/ from symlink
            os.path.join(current_dir, '.isaac_ros_common-config'),

            # Isaac ROS CLI
            '/etc/isaac-ros-cli/.isaac_ros_common-config'
        ]

        # Try each location
        common_config_file = None
        for location in config_locations:
            if os.path.exists(location):
                common_config_file = location
                self.common_config_file_ = common_config_file
                break

        if not common_config_file:
            return False

        config_remap = {
            'CONFIG_DOCKER_SEARCH_DIRS': 'docker_search_dirs',
            'BASE_DOCKER_REGISTRY_NAMES': 'cache_from_registry_names'
        }
        config_vars = extract_env_vars(common_config_file, config_remap.keys())
        if not config_vars:
            return False
        config_dict = {}
        for source_key, target_key in config_remap.items():
            config_dict[target_key] = config_vars[source_key]
        return self.load(config_dict)

    def load_yaml(self, config_file):
        if not os.path.exists(config_file):
            return False
        with open(config_file, 'r') as f:
            config_dict = yaml.safe_load(f)
        return self.load(config_dict)

    def load(self, config_dict) -> None:
        def list_prepend_unique(key, variable_name=None, processor=None):
            if key not in config_dict:
                return
            if not variable_name:
                variable_name = f'{key}_'
            prepend_list = config_dict[key]
            if processor:
                prepend_list = [processor(val) for val in prepend_list]
            base_list = getattr(self, variable_name, [])
            new_base_list = [x for x in base_list if x not in prepend_list]
            setattr(self, variable_name, prepend_list + new_base_list)

        def override_value(key, variable_name=None, processor=None):
            if key not in config_dict:
                return
            if not variable_name:
                variable_name = f'{key}_'
            value = config_dict[key]
            if processor:
                value = processor(value)
            setattr(self, variable_name, value)

        override_value(
            'image_key_order',
            processor=lambda x: [str(key).split('.') for key in x][0]
        )
        if self.common_config_file_:
            list_prepend_unique(
                'docker_search_dirs',
                processor=lambda x: os.path.join(
                    os.path.dirname(os.path.abspath(self.common_config_file_)),
                    x
                )
            )
        else:
            list_prepend_unique(
                'docker_search_dirs',
                processor=lambda x: os.path.dirname(os.path.abspath(__file__))
            )
        list_prepend_unique('cache_to_registry_names')
        list_prepend_unique('cache_from_registry_names')
        override_value(
            'remote_builder',
            processor=lambda x: x[self.platform_] if x else None
        )
        override_value('context_overrides')
        override_value('s3_cache')

        return True


class Dockerfile:
    def __init__(self, dockerfile_path: Path, context_dir: Path, image_key: ImageKey):
        self.dockerfile_path_ = dockerfile_path
        self.context_dir_ = context_dir
        self.image_key_ = image_key
        self.md5_hash_ = None
        print(f'Dockerfile created: image_key = {image_key}')

    def md5_hash(self) -> str:
        if not self.md5_hash_:
            self.md5_hash_ = calculate_md5(self.dockerfile_path_)
        return self.md5_hash_

    def target_name(self) -> str:
        return f"{self.image_key_}_{self.md5_hash()}"

    def hashless_target_name(self) -> str:
        return f"{self.image_key_}"

    def image_key(self) -> str:
        return str(self.image_key_)

    def __str__(self):
        return f'{self.dockerfile_path_}@{self.md5_hash()}'


class ImageBuildPlan:
    def __init__(self, dockerfiles: List[Dockerfile], image_key: ImageKey = None):
        self.dockerfiles_ = dockerfiles
        self.image_key_ = image_key
        self.build_variables_ = {}

    def md5hash(self) -> str:
        tmp_file = "/tmp/dockerhash.tmp"
        subprocess.getoutput(f'rm -Rf {tmp_file}')
        subprocess.getoutput(f'touch {tmp_file}')
        for d in sorted(self.dockerfiles_, key=lambda x: x.image_key()):
            individual_hash = subprocess.getoutput(
                f"md5sum {d.dockerfile_path_}").partition(' ')[0]
            subprocess.getoutput(f"echo {individual_hash} >> {tmp_file}")
        hash_value = subprocess.getoutput(f"md5sum {tmp_file}").partition(' ')[0]
        return hash_value

    def target_names(self):
        return [
            ImageBuildPlan(self.dockerfiles_[:i+1]).target_name()
            for i in range(len(self.dockerfiles_))
        ]

    def target_name(self):
        names = "-".join([d.image_key() for d in self.dockerfiles_])
        return f"{names}_{self.md5hash()}"

    def hashless_target_name(self):
        names = "-".join([d.image_key() for d in self.dockerfiles_])
        return f"{names}"

    def generate_bake_dict(
        self,
        arch,
        cache_from_registry,
        cache_to_registry,
        target_image_name=None,
        base_image=None,
        context_dir=None,
        extra_build_args=None,
        nvcr_tag=False,
        s3_cache_config=None,
        use_kubernetes_driver=False
    ):
        """
        Generate a dictionary representing the docker buildx bake configuration.

        :param arch: architecture string.
        :param cache_from_registry: registry to pull cache from (unused, kept for compatibility).
        :param cache_to_registry: registry to push cache to (unused, kept for compatibility).
        :param target_image_name: Optional final image name.
        :param base_image: Optional base image override (applied to first target).
        :param context_dir: Optional context directory override for final target.
        :param extra_build_args: Dictionary of additional build args.
        :param s3_cache_config: Dictionary containing s3 cache configuration.
        :param use_kubernetes_driver: Boolean indicating if kubernetes driver is used.
        """
        build_plan = {}
        nvcr_url = "nvcr.io/nvidian/isaac-ros/ros"
        dockerfile_list = self.dockerfiles_
        file_arch = 'arm64' if arch == 'aarch64' else 'amd64'
        platform = file_arch  # Use file_arch directly
        variables = dict(self.build_variables_)
        variables.update({
            'ARCH': arch,
            'FILE_ARCH': file_arch,
            'CACHE_FROM_REGISTRY': cache_from_registry if cache_from_registry else "local"
        })
        build_plan['variables'] = variables

        use_s3_cache = False
        aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID', '')
        aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY', '')
        aws_session_token = os.getenv('AWS_SESSION_TOKEN', '')

        # Only use S3 cache if:
        # 1. Config is present
        # 2. Using Kubernetes driver
        # 3. AWS Credentials are present (Access Key + Secret Key)
        if (
            s3_cache_config
            and use_kubernetes_driver
            and aws_access_key_id
            and aws_secret_access_key
        ):
            use_s3_cache = True
        elif s3_cache_config and use_kubernetes_driver:
            print("Warning: S3 cache configured but AWS credentials missing. Skipping S3 cache.")

        def get_target(dockerfiles: List[Dockerfile]):
            return ImageBuildPlan(dockerfiles).target_name()

        build_plan['targets'] = {}
        targets = build_plan['targets']
        for i, target in enumerate(dockerfile_list):
            target_name = get_target(dockerfile_list[:i+1])
            targets[target_name] = {'name': target_name}
            target_dict = targets[target_name]
            target_dict['context'] = str(target.context_dir_)
            target_dict['dockerfile'] = target.dockerfile_path_
            target_dict['args'] = {'PLATFORM': file_arch}

            if use_s3_cache:
                bucket = s3_cache_config.get('bucket')
                region = s3_cache_config.get('region')
                # Use hashless target name + arch to allow reuse of layers across builds/commits
                # while avoiding architecture collisions.
                hashless_name = ImageBuildPlan(dockerfile_list[:i+1]).hashless_target_name()
                cache_name = f"{hashless_name}-{file_arch}"

                s3_opts = "type=s3"
                s3_opts += f",region={region}"
                s3_opts += f",bucket={bucket}"
                s3_opts += f",name={cache_name}"
                s3_opts += ",ignore-error=true"
                s3_opts += f",access_key_id={aws_access_key_id}"
                s3_opts += f",secret_access_key={aws_secret_access_key}"
                if aws_session_token:
                    s3_opts += f",session_token={aws_session_token}"

                target_dict['cache-to'] = [f"{s3_opts},mode=max"]
                target_dict['cache-from'] = [s3_opts]

            if i == 0:
                # First target – set (if provided) BASE_IMAGE.
                target_dict['tags'] = [
                    f"{cache_from_registry}/{target_name}-{platform}:latest"
                ]
                if base_image is not None:
                    target_dict['args']['BASE_IMAGE'] = base_image
            else:
                depends_name = ImageBuildPlan(dockerfile_list[:i]).target_name()
                target_dict['tags'] = [
                    f"{cache_from_registry}/{target_name}-{platform}:latest"
                ]

                target_dict['args'].update({
                    'BASE_IMAGE': (
                        f"{cache_from_registry}/{depends_name}-{platform}:latest"
                    )
                })
                target_dict['depends_on'] = [f"{get_target(dockerfile_list[:i])}"]
            if nvcr_tag:
                target_dict['tags'].append(f"{nvcr_url}:{target_name}")

        # If extra build args are provided, update each target's args.
        if extra_build_args:
            for target in targets.values():
                if 'args' not in target:
                    target['args'] = {}
                target['args'].update(extra_build_args)

        # Optionally add a final target that simply retags the built image.
        if target_image_name is not None:
            final_key = get_target(dockerfile_list)
            final_target = targets[final_key]
            if context_dir is not None:
                final_target['context'] = context_dir
            final_target_dict = {
                'name': target_image_name,
                'dockerfile-inline': f"FROM {final_target['tags'][0]}",
                'depends_on': [final_target['name']],
                'tags': [f"{target_image_name}"]
            }

            targets['final_target'] = final_target_dict
        return build_plan

    @staticmethod
    def as_hcl_str(bake_plan_dict):
        import io
        f = io.StringIO()
        variables = bake_plan_dict['variables']
        for key, value in variables.items():
            f.write(f'variable "{key}" {{\n')
            f.write(f'  default = "{value}"\n')
            f.write('}\n\n')

        def quoted_list(str_list: List[str]):
            return '[' + ', '.join([f'"{value}"' for value in str_list]) + ']'

        targets = bake_plan_dict['targets']
        for target_name, target in targets.items():
            f.write(f'target "{target_name}" {{\n')

            def write_target_attr(attr_key, processor=None):
                if attr_key in target:
                    if processor:
                        value = processor(target[attr_key])
                    else:
                        value = f'"{target[attr_key]}"'
                    f.write(f'  {attr_key:12} = {value}\n')

            write_target_attr('context')
            write_target_attr('dockerfile')
            write_target_attr('dockerfile-inline')
            write_target_attr('tags', lambda x: quoted_list(x))
            write_target_attr('cache-from', lambda x: quoted_list(x))
            write_target_attr('cache-to', lambda x: quoted_list(x))
            write_target_attr('inherits', lambda x: quoted_list(x))
            if 'args' in target:
                f.write('  args       = {\n')
                items = list(target['args'].items())
                for i, (k, v) in enumerate(items):
                    comma = "," if i < len(items) - 1 else ""
                    f.write(f'    {k} = "{v}"{comma}\n')
                f.write('  }\n')
            write_target_attr('depends_on', lambda x: quoted_list(x))
            f.write('}\n\n')
        return f.getvalue()


def resolve_dockerfiles(
    image_key: ImageKey,
    docker_search_dirs: List[str],
    context_overrides: Dict[str, str] = {},
    ignore_composite_keys=False,
    verbose=False
):
    dockerfiles = []
    image_ids = list(image_key.image_keys_)
    while image_ids:
        unmatched_id_count = len(image_ids)
        for i in reversed(range(len(image_ids))):
            matched = False
            if ignore_composite_keys and i == 1:
                break
            layer_image_ids = image_ids[:i+1]
            layer_image_suffix = ".".join(layer_image_ids)
            if verbose:
                print(f"Searching for {layer_image_suffix}")
            for docker_search_dir in docker_search_dirs:
                dockerfile = Path(f"{docker_search_dir}/Dockerfile.{layer_image_suffix}")
                if verbose:
                    print(f"Checking {dockerfile}")
                if dockerfile.is_file():
                    context_dir = Path(docker_search_dir) / \
                        context_overrides.get(layer_image_suffix, "")
                    dockerfiles.append(
                        Dockerfile(
                            dockerfile.absolute(),
                            context_dir,
                            ImageKey(layer_image_ids)
                        )
                    )
                    image_ids = image_ids[i+1:]
                    if verbose:
                        print(
                            f"Matched {dockerfile}, remaining image keys: "
                            f"{'.'.join(image_ids)}"
                        )
                    matched = True
                    break
            if matched:
                break
        if unmatched_id_count == len(image_ids):
            if verbose:
                print(
                    f"Could not resolve Dockerfiles for target image ids: "
                    f"{'.'.join(image_ids)}"
                )
            if dockerfiles and verbose:
                print("Partially resolved Dockerfiles:")
                for d in dockerfiles:
                    print(d)
            return None
    return ImageBuildPlan(dockerfiles, image_key)


def check_docker_image_exists(image):
    try:
        run_shell(
            f'docker manifest inspect {image}',
            capture_output=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False


def countdown_warning(message, seconds=5):
    """Display a countdown warning message with the option to cancel."""
    print(f"\n{message}")
    print("Ctrl+C to cancel. Building locally in ", end='', flush=True)
    try:
        for i in range(seconds, 0, -1):
            print(f"{i}...", end='', flush=True)
            time.sleep(1)
        print("\n")
    except KeyboardInterrupt:
        print("\nBuild cancelled.")
        sys.exit(1)


def get_image_name(cache_from_registry_name, env_list, file_arch, include_hash=False):
    """Get the full image name for a given environment list and architecture.

    Args:
        cache_from_registry_name (str): Registry name to use for the image
        env_list (List[str]): List of environment components
        file_arch (str): Architecture (e.g. 'amd64', 'sbsa', 'arm64')
        include_hash (bool): Whether to include the hash in the image name

    Returns:
        str: Full image name including registry, environment components,
            architecture and optionally hash
    """
    base_name = '-'.join(env_list)
    if os.getenv("CONFIG_CONTAINER_NAME_SUFFIX"):
        base_name += f"-{os.getenv('CONFIG_CONTAINER_NAME_SUFFIX')}"

    # Use the same docker search dirs as main()
    config = Config(
        platform_="x86_64" if file_arch == "amd64"
        else "aarch64" if file_arch == "arm64" or file_arch == "sbsa"
        else platform.uname().machine
    )
    config.load_shell_common_config()
    # Create ImageBuildPlan to get the hash
    image_key = ImageKey.from_key_set(env_list, key_order=config.image_key_order_)
    build_plan = resolve_dockerfiles(
        image_key,
        config.docker_search_dirs_,
        context_overrides=config.context_overrides_
    )

    if include_hash:
        if build_plan:
            base_name += f"_{build_plan.md5hash()}"
        else:
            print("Error: Could not resolve all Dockerfiles.")
            print(f"Image key: {image_key}")
            print(f"Docker search dirs: {config.docker_search_dirs_}")
            print(f"Common config file: {config.common_config_file_}")
            print(f"$ISAAC_ROS_WS: {os.getenv('ISAAC_ROS_WS')}")
            print("Please ensure that the $ISAAC_ROS_WS variable is set, "
                  "the .isaac_ros_common-config file is present and valid, "
                  "and that the docker_search_dirs are present and correct.")
            exit(1)

    target_name = f"{base_name}-{file_arch}"

    if cache_from_registry_name.count("nvcr.io"):
        return f"{cache_from_registry_name}:{target_name}"
    else:
        return f"{cache_from_registry_name}/{target_name}:latest"


def main(image_key_set: List[str],
         target_image_name: str = None,
         config_file: str = None,
         verbose=False,
         no_cache=False,
         base_image=None,
         context_dir=None,
         build_args: List[str] = None,
         platform_: str = None,
         nvcr_tag: bool = False,
         skip_registry_check: bool = False,
         build_local: bool = False,
         push: bool = False,
         use_kubernetes_driver: bool = False):

    platform_ = platform_ if platform_ else platform.uname().machine

    config = Config(platform_=platform_)
    config.verbose_ = verbose
    config.load_shell_common_config()
    config.context_dir_ = context_dir
    config.load_yaml(config_file)
    config.target_image_name_ = target_image_name
    config.base_image_ = base_image

    # If a context directory is provided, add it to the beginning of the docker search directories.
    if config.context_dir_:
        config.docker_search_dirs_.insert(0, config.context_dir_)

    # Process extra build args (expected as KEY=VALUE strings)
    if build_args:
        for arg in build_args:
            if '=' in arg:
                key, value = arg.split('=', 1)
                config.build_args_[key] = value

    print(config.__dict__)
    image_key = ImageKey.from_key_set(image_key_set, key_order=config.image_key_order_)
    print(f'Image key = {image_key}')
    build_plan = resolve_dockerfiles(
        image_key,
        config.docker_search_dirs_,
        context_overrides=config.context_overrides_,
        verbose=verbose
    )
    if not build_plan:
        print("Error: Could not resolve all Dockerfiles.")
        exit(1)
    for d in build_plan.dockerfiles_:
        print(f'Dockerfile: {d}')
    print('\n')

    cache_to_registry_name = check_docker_logins(
        config.cache_to_registry_names_, fail_on_anon=False
    )
    cache_from_registry_name = check_docker_logins(
        config.cache_from_registry_names_, fail_on_anon=True
    )

    print(f"cache_from_registry_name: {cache_from_registry_name}")

    # Pass base_image, context_dir and extra build args (if any) to the bake dict generation.
    docker_bake_dict = build_plan.generate_bake_dict(
        config.platform_,
        cache_from_registry=cache_from_registry_name,
        cache_to_registry=cache_to_registry_name,
        target_image_name=config.target_image_name_,
        base_image=config.base_image_,
        context_dir=config.context_dir_,
        extra_build_args=config.build_args_,
        nvcr_tag=nvcr_tag,
        s3_cache_config=config.s3_cache_,
        use_kubernetes_driver=use_kubernetes_driver
    )
    docker_bake = ImageBuildPlan.as_hcl_str(docker_bake_dict)
    print(redact_bake_hcl(docker_bake))

    build_target_names = []
    for target_name in build_plan.target_names():
        target = docker_bake_dict['targets'][target_name]
        tag = target['tags'][0]
        if (not skip_registry_check) and (check_docker_image_exists(tag) and not no_cache):
            print(f"Tag: {tag} exists, skipping")
            continue
        build_target_names.append(target_name)

    # Exit early if all tags exist and there's nothing to build
    if not build_target_names and not config.target_image_name_:
        print("All target images already exist. Nothing to build.")
        return

    with tempfile.TemporaryDirectory() as tempdir:
        bake_filepath = os.path.join(tempdir, 'docker-bake.hcl')
        with open(bake_filepath, mode='wt') as f:
            f.write(docker_bake)
        env_dict = {'BUILDX_BAKE_ENTITLEMENTS_FS': '0'}

        # Make builder name unique for parallel/repeated builds if using Kubernetes driver.
        # Otherwise buildx can fail with:
        #   "existing instance for <name> but no append mode ..."
        if use_kubernetes_driver:
            import random
            import string
            random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
            builder_name = f'isaaceks-{config.platform_}-{random_suffix}'
        else:
            builder_name = f'isaaceks-{config.platform_}'
        no_cache_flag = '--no-cache' if no_cache else ''
        debug_flag = '--debug' if verbose else ''

        try:
            if not build_local and use_kubernetes_driver:
                # Use Kubernetes driver - deploys BuildKit pods on-demand in cluster
                print("Using Kubernetes driver (bypasses NLB, fixes EOF errors)")
                k8s_arch = "amd64" if config.platform_ in ["x86_64", "amd64"] else "arm64"
                run_shell(
                    f'docker buildx create --driver kubernetes --name {builder_name} '
                    f'--driver-opt namespace=docker-builder '
                    f'--driver-opt nodeselector=kubernetes.io/arch={k8s_arch} '
                    f'--driver-opt requests.cpu=4 '
                    f'--driver-opt requests.memory=12Gi '
                    f'--driver-opt requests.ephemeral-storage=64Gi '
                    f'--driver-opt limits.cpu=7500m '
                    f'--driver-opt limits.memory=24Gi '
                    f'--driver-opt limits.ephemeral-storage=128Gi '
                    f'--driver-opt timeout=5m '
                    f'--driver-opt "annotations=janitor/ttl=6h" '
                    f'--buildkitd-flags "--oci-worker-snapshotter=native" '
                    f'--bootstrap',
                    verbose=True,
                    env=env_dict,
                    check=True
                )
            elif not build_local and config.remote_builder_:
                run_shell(
                    f'docker buildx create --driver remote --name {builder_name} '
                    f'{config.remote_builder_}',
                    verbose=True,
                    env=env_dict
                )
            else:
                if not build_local and not config.remote_builder_:
                    countdown_warning(
                        "Remote build specification not found in config file.",
                        seconds=5
                    )
                run_shell(
                    f'docker buildx create --name {builder_name}',
                    verbose=True,
                    env=env_dict
                )

            progress_flag = "--progress=plain"

            for target_name in build_target_names:
                try:
                    print(f"Building image {target_name}")

                    # Set platform for multi-arch builds
                    if use_kubernetes_driver:
                        platform_str = config.platform_.replace("x86_64", "amd64") \
                                                       .replace("aarch64", "arm64")
                        platform_flag = f'--set *.platform=linux/{platform_str}'
                    else:
                        platform_flag = ''

                    build_cmd = (
                        f'docker {debug_flag} buildx bake {target_name} '
                        f'{no_cache_flag} {progress_flag} {platform_flag} '
                        f'--builder {builder_name if push else "default"} '
                        f'--provenance=false '
                        f'{"--push" if push else "--load"} '
                        f'--file {bake_filepath}'
                    )
                    run_shell(build_cmd, capture_output=False, env=env_dict, check=True)
                except subprocess.CalledProcessError as e:
                    raise e

            if config.target_image_name_:
                try:
                    print(f"Building image {config.target_image_name_}")

                    final_cmd = (
                        f'docker {debug_flag} buildx bake final_target '
                        f'{no_cache_flag} {progress_flag} '
                        f'--builder {builder_name if push else "default"} '
                        f'--provenance=false '
                        f'{"--push" if push else "--load"} '
                        f'--file {bake_filepath}'
                    )
                    run_shell(final_cmd, capture_output=False, env=env_dict, check=True)
                except subprocess.CalledProcessError as e:
                    raise e

        finally:
            run_shell(f'docker buildx rm {builder_name}', verbose=True, env=env_dict, check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Resolve dockerfiles and build image layers"
    )
    parser.add_argument(
        '-i',
        '--image_key',
        type=str,
        action='append',
        dest='image_keys',
        help='Image key to resolve (can be specified multiple times)'
    )
    parser.add_argument(
        '-b',
        '--build_arg',
        type=str,
        action='append',
        dest='build_args',
        help='Additional build args as KEY=VALUE'
    )
    parser.add_argument(
        '-n',
        '--image_name',
        type=str,
        dest='image_name',
        default=None,
        help='Set final image name'
    )
    parser.add_argument(
        '-c',
        '--config_file',
        type=str,
        dest='config_file',
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '.build_image_layers.yaml'
        ),
        help='Config YAML file'
    )
    parser.add_argument(
        '-v',
        '--verbose',
        action="store_true",
        dest="verbose",
        help="Verbose mode"
    )
    parser.add_argument(
        '--no-cache',
        action="store_true",
        dest="no_cache",
        help="Do not use cached layers for image build."
    )
    parser.add_argument(
        '-p',
        '--platform',
        type=str,
        default=None,
        help=('Target platform architecture (e.g. "aarch64" or "x86_64"). '
              'Overrides auto-detection from image keys.')
    )
    parser.add_argument(
        '--base_image',
        type=str,
        dest='base_image',
        default=None,
        help="Override base image for the first build layer."
    )
    parser.add_argument(
        '--context_dir',
        type=str,
        dest='context_dir',
        default=None,
        help="Override context directory for the final build target."
    )
    parser.add_argument(
        '--nvcr',
        action="store_true",
        dest="nvcr",
        help="Push an nvcr.io image.",
        default=False
    )
    parser.add_argument(
        '--skip-registry-check',
        action="store_true",
        dest="skip_registry_check",
        help="Skip registry check for the final build target."
    )
    parser.add_argument(
        '--build-local',
        action="store_true",
        dest="build_local",
        help="Force local building instead of remote.",
        default=False
    )
    parser.add_argument(
        '--push',
        action="store_true",
        dest="push",
        help="Push the image to the target registry when complete.",
        default=False
    )
    parser.add_argument(
        '--kubernetes',
        action="store_true",
        dest="use_kubernetes_driver",
        help="Use Kubernetes driver (deploy BuildKit pods on-demand, bypasses NLB).",
        default=False
    )

    args = parser.parse_args()

    # Ensure that --nvcr and --image_name are not used together.
    assert not (args.nvcr and args.image_name), (
        "Cannot use --nvcr and --image_name simultaneously"
    )

    image_key_set = set(
        part for key in args.image_keys for part in key.split('.')
    )
    main(
        image_key_set,
        target_image_name=args.image_name,
        config_file=args.config_file,
        verbose=args.verbose,
        no_cache=args.no_cache,
        base_image=args.base_image,
        context_dir=args.context_dir,
        build_args=args.build_args,
        push=args.push,
        platform_=args.platform,
        nvcr_tag=args.nvcr,
        skip_registry_check=args.skip_registry_check,
        build_local=args.build_local,
        use_kubernetes_driver=args.use_kubernetes_driver
    )
