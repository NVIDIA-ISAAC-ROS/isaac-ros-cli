#!/usr/bin/env python3
#
# Copyright (c) 2025, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

import os
import sys
import subprocess
import shlex
from build_image_layers import (
    main as build_image_layers,
    check_docker_logins,
    get_image_name)
from isaac_ros_common_config_utils import (
    get_isaac_ros_common_config_path,
    get_isaac_ros_common_config_values,
    get_build_order)


def validate_isaac_dir(isaac_dir):
    if not os.path.isdir(isaac_dir):
        print(f"Specified Isaac ROS dev directory does not exist: {isaac_dir}")
        sys.exit(1)


def check_user_in_docker_group():
    output = subprocess.check_output(["groups", os.getenv("USER")], universal_newlines=True)
    if "docker" not in output:
        print(
            f"User {os.getenv('USER')} is not a member of the 'docker' group "
            "and cannot run docker commands without sudo."
        )
        print(
            "Run 'sudo usermod -aG docker $USER && newgrp docker' to add user to "
            "'docker' group, then re-run this script."
        )
        print("See: https://docs.docker.com/engine/install/linux-postinstall/")
        sys.exit(1)


def check_docker_running():
    try:
        subprocess.check_output(["docker", "ps"], stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print(
            "Unable to run docker commands. If you have recently added $USER to "
            "'docker' group, you may need to log out and log back in for it to take effect."
        )
        print("Otherwise, please check your Docker installation.")
        sys.exit(1)


def check_docker_buildx_containerd_cache_enabled():
    try:
        subprocess.check_output(["docker", "buildx", "inspect", "--bootstrap"])
    except subprocess.CalledProcessError:
        print(
            "Unable to detect docker buildx containerd cache. "
            "Please follow these instructions: "
            "https://docs.docker.com/engine/storage/containerd/#enable-containerd-image-store-on-docker-engine"  # noqa:E501
        )
        sys.exit(1)


def check_git_lfs_installed():
    try:
        subprocess.check_output(["git", "lfs"], stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print(
            "git-lfs is not installed. Please make sure git-lfs is installed before "
            "you clone the repo."
        )
        sys.exit(1)


def check_lfs_files(isaac_dir):
    print(isaac_dir)
    try:
        output = subprocess.check_output(
            ["git", "lfs", "ls-files"],
            cwd=isaac_dir,
            universal_newlines=True
        )
        lfs_files = [line for line in output.splitlines()]

        output = subprocess.check_output(
            ["git", "lfs", "status"],
            cwd=isaac_dir,
            universal_newlines=True
        )
        lfs_files_status = [line for line in output.splitlines()]

        for line in lfs_files:
            if "-" in line.split()[1]:
                file = line.split()[2]
                if not any(file in line for line in lfs_files_status):
                    if not os.path.exists(os.path.join(isaac_dir, file)):
                        print(f"LFS file {file} is missing. "
                              "Please run `git lfs pull` after installing git-lfs.")
                        sys.exit(1)
            else:
                pass

    except subprocess.CalledProcessError:
        pass


def remove_exited_container(container_name):
    output = subprocess.check_output(
        [
            "docker",
            "ps",
            "-a",
            "--quiet",
            "--filter",
            "status=exited",
            "--filter",
            f"name={container_name}"
        ]
    )
    if output:
        subprocess.run(["docker", "rm", container_name], stdout=subprocess.DEVNULL)


def attach_to_running_container(container_name):
    output = subprocess.check_output(
        [
            "docker",
            "ps",
            "-a",
            "--quiet",
            "--filter",
            "status=running",
            "--filter",
            f"name={container_name}"
        ]
    )
    if output:
        print(f"Attaching to running container: {container_name}")
        isaac_ros_ws = subprocess.check_output(
            ["docker", "exec", container_name, "printenv", "ISAAC_ROS_WS"],
            universal_newlines=True
        ).strip()
        print(f"Docker workspace: {isaac_ros_ws}")
        subprocess.run(
            [
                "docker", "exec", "-i", "-t",
                "-e", "TERM=xterm-256color",
                "-e", "COLORTERM=truecolor",
                "-e", "FORCE_COLOR=true",
                "-u", "admin",
                "--workdir", isaac_ros_ws,
                container_name, "/bin/bash"
            ],
            env={
                **os.environ,
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
                "FORCE_COLOR": "true"
            }
        )
        sys.exit(0)


def make_docker_image_available(base_name, cached_image_name):
    pull_result = subprocess.run(
        [f"docker pull {base_name}"],
        shell=True,
        env={**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
    )

    local_image_result = subprocess.run(
        ["docker", "image", "inspect", base_name],
        capture_output=True,
        env={**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
    )

    if pull_result.returncode == 0 or local_image_result.returncode == 0:
        # Remove any existing cached image
        subprocess.run(
            ["docker", "rmi", cached_image_name],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL
        )
        # Tag the image as our cached image name
        tag_result = subprocess.run(
            ["docker", "tag", base_name, cached_image_name]
        )

        return tag_result.returncode == 0

    return False


def get_existing_bash_configs():
    """Returns a list of existing bash configuration files in the user's home directory."""
    config_files = ['.bashrc', '.bash_profile', '.profile', '.dircolors']
    existing_configs = []
    for file in config_files:
        if os.path.isfile(os.path.expanduser(f'~/{file}')):
            existing_configs.append(file)
    return existing_configs


def get_docker_args(platform):
    # Return arguments as complete flag-value pairs for shell=True usage
    home_path = os.path.expanduser('~')
    docker_args = [
        "-v /tmp/.X11-unix:/tmp/.X11-unix",
        f"-v {shlex.quote(home_path)}/.Xauthority:/home/admin/.Xauthority:rw",
    ]
    # Add existing bash config files
    for config in get_existing_bash_configs():
        docker_args.append(
            f"-v {shlex.quote(home_path)}/{config}:/home/admin/{config}:ro"
        )
    docker_args.extend([
        "-e DISPLAY",
        "-e NVIDIA_VISIBLE_DEVICES=all",
        "-e NVIDIA_DRIVER_CAPABILITIES=all",
        "-e ROS_DOMAIN_ID",
        "-e USER",
        "-e ISAAC_ROS_WS=/workspaces/isaac_ros-dev",
        f"-e HOST_USER_UID={os.getuid()}",
        f"-e HOST_USER_GID={os.getgid()}",
    ])
    if platform == "aarch64":
        if "SSH_AUTH_SOCK" in os.environ:
            ssh_auth_sock = os.environ['SSH_AUTH_SOCK']
            docker_args.extend([
                f"-v {shlex.quote(ssh_auth_sock)}:/ssh-agent",
                "-e SSH_AUTH_SOCK=/ssh-agent",
            ])
        docker_args.extend([
            "-v /usr/bin/tegrastats:/usr/bin/tegrastats",
            "-v /sys/kernel/debug:/sys/kernel/debug:ro",  # Required for tegrastats
            "-v /tmp/:/tmp/",
            "-v /usr/lib/aarch64-linux-gnu/tegra:/usr/lib/aarch64-linux-gnu/tegra",
            "-v /usr/src/jetson_multimedia_api:/usr/src/jetson_multimedia_api",
            "--pid=host",
            "-v /usr/share/vpi3:/usr/share/vpi3",
            "-v /dev/input:/dev/input",
            "-v /dev/bus/usb:/dev/bus/usb",
        ])
        try:
            output = subprocess.check_output(
                ["getent", "group", "jtop"], text=True
            ).strip()
            if output:
                group_id = output.split(":")[2]
                docker_args.extend([
                    "-v /run/jtop.sock:/run/jtop.sock:ro",
                    f"--group-add {group_id}",
                ])
        except subprocess.CalledProcessError:
            pass

    return docker_args


def realpath(path):
    return subprocess.check_output(['realpath', os.path.expanduser(path)]).decode().strip()


def load_docker_args_from_file():
    docker_args_files = [os.getenv("DOCKER_ARGS_FILE", "")]
    docker_args_files.append("~/.isaac_ros_dev-dockerargs")

    if os.path.isfile(os.path.join(os.path.dirname(__file__), ".isaac_ros_dev-dockerargs")):
        docker_args_files.append(os.path.join(
            os.path.dirname(__file__), ".isaac_ros_dev-dockerargs"))
    elif "ISAAC_ROS_WS" in os.environ and os.path.isfile(
        os.path.expandvars("$ISAAC_ROS_WS/../scripts/.isaac_ros_dev-dockerargs")
    ):
        docker_args_files.append(os.path.expandvars(
            "$ISAAC_ROS_WS/../scripts/.isaac_ros_dev-dockerargs"))
    else:
        docker_args_files.append("/etc/isaac-ros-cli/.isaac_ros_dev-dockerargs")

    docker_args_filepaths = []
    for docker_args_file in docker_args_files:
        if os.path.isfile(docker_args_file):
            docker_args_filepaths.append(docker_args_file)
        elif os.path.isfile(os.path.join(os.path.dirname(__file__), docker_args_file)):
            docker_args_filepaths.append(os.path.join(os.path.dirname(__file__), docker_args_file))
        elif os.path.isfile(os.path.expanduser(docker_args_file)):
            docker_args_filepaths.append(os.path.expanduser(docker_args_file))

    if docker_args_filepaths:
        docker_args = []
        print(f"Using additional Docker run arguments from {docker_args_filepaths}")
        for docker_args_filepath in docker_args_filepaths:
            with open(docker_args_filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    # Handle arguments wrapped in quotes for backward compatibility
                    if ((line.startswith('"') and line.endswith('"')) or
                            (line.startswith("'") and line.endswith("'"))):
                        # Strip the outer quotes for old run_dev.sh-style arguments
                        line = line[1:-1]

                    if "`realpath" in line:
                        # Replace `realpath` expressions with evaluated real paths
                        start = line.find("`realpath") + len("`realpath ")
                        end = line.find("`", start)
                        path = line[start:end]
                        resolved_path = realpath(path)
                        # Quote the resolved path to handle spaces
                        quoted_path = shlex.quote(resolved_path)
                        line = line.replace(f"`realpath {path}`", quoted_path)
                    # Make sure each line is a complete argument for shell=True
                    docker_args.append(os.path.expandvars(line))
        print(docker_args)
        return docker_args
    return []


def run_docker_container(args, container_name, base_name, isaac_dir):
    docker_args = get_docker_args(args.platform)
    file_args = load_docker_args_from_file()

    docker_args.extend(file_args)

    # Build the command as a single string for shell=True
    # Use proper shell quoting for arguments that might contain spaces
    docker_command_parts = [
        "docker run -it --rm",
        "--privileged",
        "--network host",
        "--ipc=host",
        "-e TERM=xterm-256color",
        "-e COLORTERM=truecolor",
        "-e FORCE_COLOR=true",
        "--workdir /workspaces/isaac_ros-dev",
    ]

    # Pass ISAAC_ROS_PLATFORM if specified
    if args.isaac_ros_platform:
        docker_command_parts.append(
            f"-e ISAAC_ROS_PLATFORM={shlex.quote(args.isaac_ros_platform)}"
        )

    # Add Docker arguments as strings
    docker_command_parts.extend(docker_args)

    # Add remaining arguments
    docker_command_parts.extend([
        f"-v {shlex.quote(isaac_dir)}:/workspaces/isaac_ros-dev",
        "-v /etc/localtime:/etc/localtime:ro",
        f"--name {shlex.quote(container_name)}",
        "--runtime nvidia",
        "--entrypoint /usr/local/bin/scripts/workspace-entrypoint.sh",
        shlex.quote(base_name),
        "/bin/bash"
    ])

    # Join all command parts with spaces to create a single command string
    docker_command_str = " ".join(docker_command_parts)

    print(f"Running {container_name}")
    if args.verbose:
        print(docker_command_str)

    subprocess.run(
        docker_command_str,
        shell=True,
        env={
            **os.environ,
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "FORCE_COLOR": "true"
        }
    )


def parse_args():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--env", action="append", required=False,
                        default=None)  # Keep default=None so user-provided envs override defaults
    DEFAULT_ENV_LIST = ["noble", "ros2_jazzy", "ros_eng", "realsense"]

    parser.add_argument("--extra_env",
                        action="append",
                        required=False,
                        default=None,
                        help="Additional environments to append after default environments")
    parser.add_argument("--verbose", action="store_true", required=False, default=False)
    parser.add_argument(
        "--no-cache",
        action="store_true",
        required=False,
        default=False,
        help="Do not use docker layer cache"
    )
    parser.add_argument(
        "--build",
        action="store_true",
        required=False,
        default=False,
        help="Build the image if it doesn't exist"
    )
    parser.add_argument(
        "--build-local",
        action="store_true",
        required=False,
        default=False,
        help="Build the image locally if it doesn't exist"
    )
    parser.add_argument(
        "--push",
        action="store_true",
        required=False,
        default=False,
        help="Push the image to the target registry when complete"
    )
    parser.add_argument(
        "--container-name",
        default="isaac_ros_dev_container",
        help="Name of the Docker container"
    )
    parser.add_argument(
        "-b", "--use-cached-build-image",
        action="store_true",
        required=False,
        default=False,
        help="Use the cached build image"
    )
    parser.add_argument(
        "--platform",
        choices=["x86_64", "aarch64"],
        default=os.uname().machine,
        help="Override the platform architecture (default: auto-detected)"
    )
    parser.add_argument(
        "-d", "--isaac-dir",
        help="Specify the ISAAC directory path (overrides ISAAC_DIR environment variable)"
    )
    parser.add_argument(
        "--isaac-ros-platform",
        default=None,
        help="Isaac ROS platform identifier (e.g., amd64, arm64)"
    )
    args = parser.parse_args()

    # Apply default env values only if nothing was provided
    if args.env is None:
        args.env = DEFAULT_ENV_LIST.copy()

    # Append extra environments if provided
    if args.extra_env:
        args.env.extend([e for e in args.extra_env if e not in args.env])

    return args


def get_isaac_dir():
    """
    Returns the absolute path of the ISAAC directory.

    The directory is determined in the following order:
    1. Command line argument --isaac-dir if provided
    2. ISAAC_DIR environment variable if set
    3. Auto-detection by walking up from script location

    Returns:
        str: The absolute path of the ISAAC directory.
    """
    args = parse_args()
    if args.isaac_dir:
        isaac_dir = args.isaac_dir
    elif "ISAAC_DIR" in os.environ:
        isaac_dir = os.environ.get("ISAAC_DIR")
    else:
        isaac_dir = os.path.dirname(os.path.abspath(__file__))
        max_depth = 10
        while (
            not os.path.basename(isaac_dir) == "isaac"
            and max_depth > 0
        ):
            isaac_dir = os.path.dirname(isaac_dir)
            max_depth -= 1
        if max_depth == 0:
            raise ValueError("Could not find ISAAC directory")
    return os.path.abspath(isaac_dir)


def main():
    args = parse_args()
    config_path = get_isaac_ros_common_config_path()
    config = get_isaac_ros_common_config_values(config_path)
    platform = args.platform

    file_arch = (
        'amd64' if platform == 'x86_64'
        else 'arm64' if platform == 'aarch64'
        else None
    )

    env_list = get_build_order(
        str(config['image_key_order'][0]).split('.'),
        args.env
    )
    isaac_dir = get_isaac_dir()
    container_name = args.container_name

    validate_isaac_dir(isaac_dir)
    check_user_in_docker_group()
    check_docker_running()
    check_git_lfs_installed()
    check_lfs_files(isaac_dir)

    remove_exited_container(container_name)
    attach_to_running_container(container_name)

    if args.no_cache:
        cache_from_registry_name = "local"
    else:
        cache_from_registry_name = check_docker_logins(
            config["cache_from_registry_names"], fail_on_anon=True
        )

    print(env_list)

    cached_image_name = "cached_isaac_run_dev_image_local:latest"
    base_name = get_image_name(cache_from_registry_name, env_list, file_arch, include_hash=True)
    if args.use_cached_build_image:
        # Check if cached image exists before using it

        cached_image_exists = subprocess.run(
            ["docker", "image", "inspect", cached_image_name],
            capture_output=True
        ).returncode == 0

        if not cached_image_exists:
            print("No cached image found. "
                  "Perhaps you cleaned docker cache, or you haven't yet "
                  "run run_dev.py on this system?")
            sys.exit(1)
        base_name = cached_image_name

    elif not make_docker_image_available(base_name, cached_image_name):
        if not (args.build or args.build_local):
            print(f"Error: Docker image {base_name} not found.")
            print("Use --build to build remotely or --build-local to build locally.")
            sys.exit(1)

        build_args = {
            'image_key_set': env_list,
            'config_file': config_path,
            'target_image_name': base_name,
            'verbose': args.verbose,
            'no_cache': args.no_cache,
        }

        if args.build_local:
            build_args['build_local'] = True

        if args.push:
            build_args['push'] = True

        build_image_layers(**build_args)
        if not make_docker_image_available(base_name, cached_image_name):
            print(f"Error: Failed to build or pull image {base_name}")
            sys.exit(1)

    print(f"Using image: {base_name}")

    run_docker_container(args, container_name, base_name, isaac_dir)


if __name__ == "__main__":
    main()
