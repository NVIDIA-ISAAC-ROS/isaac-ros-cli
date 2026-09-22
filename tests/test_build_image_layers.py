# Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

"""Tests for build_image_layers.py bake graph generation."""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest import mock


@contextlib.contextmanager
def _silence_stdio():
    """Suppress incidental CLI output so unittest logs only reflect pass/fail state."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


def _import_build_image_layers():
    stub_termcolor = types.ModuleType('termcolor')
    stub_termcolor.cprint = lambda *args, **kwargs: None

    module_path = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', 'scripts', 'run_dev', 'build_image_layers.py'))
    spec = importlib.util.spec_from_file_location('build_image_layers_under_test', module_path)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {'termcolor': stub_termcolor}):
        spec.loader.exec_module(module)
    return module


class TestBakeLayerDependsOn(unittest.TestCase):
    """Verify layer dependency edges can be omitted for registry-backed builds."""

    @classmethod
    def setUpClass(cls):
        cls.build_image_layers = _import_build_image_layers()

    def _make_plan(self):
        mod = self.build_image_layers
        with _silence_stdio():
            dockerfiles = [
                mod.Dockerfile(
                    Path('/tmp/Dockerfile.isaac_ros'),
                    Path('/tmp/context'),
                    mod.ImageKey(['isaac_ros'])
                ),
                mod.Dockerfile(
                    Path('/tmp/Dockerfile.realsense'),
                    Path('/tmp/context'),
                    mod.ImageKey(['realsense'])
                ),
            ]
        return mod.ImageBuildPlan(dockerfiles)

    def test_layer_depends_on_edges_are_optional(self):
        mod = self.build_image_layers
        plan = self._make_plan()

        def fake_md5hash(image_build_plan):
            return 'hash_' + '-'.join(
                dockerfile.image_key() for dockerfile in image_build_plan.dockerfiles_)

        with mock.patch.object(mod.ImageBuildPlan, 'md5hash', fake_md5hash):
            with_deps = plan.generate_bake_dict(
                'x86_64',
                'registry.example.com/cache',
                'registry.example.com/cache',
                isaac_ros_platform='amd64',
                include_layer_depends_on=True,
            )
            without_deps = plan.generate_bake_dict(
                'x86_64',
                'registry.example.com/cache',
                'registry.example.com/cache',
                isaac_ros_platform='amd64',
                include_layer_depends_on=False,
            )
            second_target_name = plan.target_names()[-1]

        self.assertIn('depends_on', with_deps['targets'][second_target_name])
        self.assertNotIn('depends_on', without_deps['targets'][second_target_name])
        self.assertEqual(
            without_deps['targets'][second_target_name]['args']['BASE_IMAGE'],
            'registry.example.com/cache/isaac_ros_hash_isaac_ros-amd64:latest'
        )

    def test_s3_cache_is_enabled_only_for_kubernetes_builds_with_credentials(self):
        mod = self.build_image_layers
        plan = self._make_plan()

        def fake_md5hash(image_build_plan):
            return 'hash_' + '-'.join(
                dockerfile.image_key() for dockerfile in image_build_plan.dockerfiles_)

        env = {
            'AWS_ACCESS_KEY_ID': 'test-access-key',
            'AWS_SECRET_ACCESS_KEY': 'test-secret-key',
            'AWS_SESSION_TOKEN': 'test-session-token',
        }
        with (
            mock.patch.dict(os.environ, env, clear=False),
            mock.patch.object(mod.ImageBuildPlan, 'md5hash', fake_md5hash),
        ):
            bake_dict = plan.generate_bake_dict(
                'x86_64',
                'registry.example.com/cache',
                'registry.example.com/cache',
                s3_cache_config={'bucket': 'isaac-cache', 'region': 'us-west-2'},
                use_kubernetes_driver=True,
                isaac_ros_platform='amd64',
            )
            target_name = plan.target_names()[0]

        target = bake_dict['targets'][target_name]
        self.assertIn('cache-to', target)
        self.assertIn('cache-from', target)
        cache_opts = target['cache-to'][0]
        self.assertIn('type=s3', cache_opts)
        self.assertIn('bucket=isaac-cache', cache_opts)
        self.assertIn('region=us-west-2', cache_opts)
        self.assertIn('access_key_id=test-access-key', cache_opts)
        self.assertIn('secret_access_key=test-secret-key', cache_opts)
        self.assertIn('session_token=test-session-token', cache_opts)

        with mock.patch.object(mod.ImageBuildPlan, 'md5hash', fake_md5hash):
            without_kubernetes = plan.generate_bake_dict(
                'x86_64',
                'registry.example.com/cache',
                'registry.example.com/cache',
                s3_cache_config={'bucket': 'isaac-cache', 'region': 'us-west-2'},
                use_kubernetes_driver=False,
                isaac_ros_platform='amd64',
            )
            without_credentials_env = {
                'AWS_ACCESS_KEY_ID': '',
                'AWS_SECRET_ACCESS_KEY': '',
                'AWS_SESSION_TOKEN': '',
            }
            with mock.patch.dict(os.environ, without_credentials_env, clear=False):
                with _silence_stdio():
                    without_credentials = plan.generate_bake_dict(
                        'x86_64',
                        'registry.example.com/cache',
                        'registry.example.com/cache',
                        s3_cache_config={'bucket': 'isaac-cache', 'region': 'us-west-2'},
                        use_kubernetes_driver=True,
                        isaac_ros_platform='amd64',
                    )

        self.assertNotIn('cache-to', without_kubernetes['targets'][target_name])
        self.assertNotIn('cache-to', without_credentials['targets'][target_name])

    def test_redact_bake_hcl_removes_inline_aws_credentials(self):
        mod = self.build_image_layers
        hcl = (
            'cache-to = ["type=s3,access_key_id=AKIA_TEST,'
            'secret_access_key=secret-value,session_token=session-value,mode=max"]'
        )

        redacted = mod.redact_bake_hcl(hcl)

        self.assertIn('access_key_id=***', redacted)
        self.assertIn('secret_access_key=***', redacted)
        self.assertIn('session_token=***', redacted)
        self.assertNotIn('AKIA_TEST', redacted)
        self.assertNotIn('secret-value', redacted)
        self.assertNotIn('session-value', redacted)

    def test_parse_build_args_rejects_malformed_values(self):
        mod = self.build_image_layers

        with self.assertRaises(ValueError):
            mod.parse_build_args(['ISAAC_DEBIAN_REPOSITORY'])
        with self.assertRaises(ValueError):
            mod.parse_build_args(['=https://apt.example.test/isaac-ros'])

        self.assertEqual(
            mod.parse_build_args([
                'ISAAC_DEBIAN_REPOSITORY=https://apt.example.test/isaac-ros',
                'ISAAC_DEBIAN_COMPONENTS=main preview',
            ]),
            {
                'ISAAC_DEBIAN_REPOSITORY': 'https://apt.example.test/isaac-ros',
                'ISAAC_DEBIAN_COMPONENTS': 'main preview',
            },
        )

    def test_build_variables_affect_target_hashes(self):
        mod = self.build_image_layers
        first = self._make_plan()
        second = self._make_plan()
        first.build_variables_['ISAAC_DEBIAN_REPOSITORY'] = (
            'https://apt.example.test/one'
        )
        second.build_variables_['ISAAC_DEBIAN_REPOSITORY'] = (
            'https://apt.example.test/two'
        )

        with mock.patch.object(
            mod.Dockerfile,
            'md5_hash',
            lambda dockerfile: f'filehash_{dockerfile.image_key()}',
        ):
            self.assertNotEqual(first.target_names(), second.target_names())

    def test_cli_image_name_matches_pushed_nvcr_tag_with_snapshot_args(self):
        mod = self.build_image_layers
        build_args = [
            'ISAAC_DEBIAN_KEY_URL=https://apt.example.test/repos.key',
            'ISAAC_DEBIAN_REPOSITORY=https://apt.example.test/snapshot/',
            'ISAAC_DEBIAN_DIST=noble',
            'ISAAC_DEBIAN_COMPONENTS=main',
        ]

        with TemporaryDirectory() as tmpdir:
            context = Path(tmpdir)
            (context / 'Dockerfile.isaac_ros').write_text(
                'FROM scratch\n', encoding='utf-8'
            )

            class FakeConfig:
                def __init__(self, platform_):
                    self.platform_ = platform_
                    self.image_key_order_ = ['isaac_ros']
                    self.docker_search_dirs_ = [str(context)]
                    self.context_overrides_ = {}

                def load_shell_common_config(self):
                    return True

            plan = mod.resolve_dockerfiles(
                mod.ImageKey(['isaac_ros']),
                [str(context)],
            )
            plan.build_variables_.update(mod.parse_build_args(build_args))
            bake = plan.generate_bake_dict(
                'aarch64',
                'registry.example.test/cache',
                'registry.example.test/cache',
                extra_build_args=mod.parse_build_args(build_args),
                nvcr_tag=True,
                isaac_ros_platform='arm64-jetpack',
            )

            target = bake['targets'][plan.target_names()[0]]
            pushed_ref = target['tags'][-1]
            pushed_registry = pushed_ref.rsplit(':', maxsplit=1)[0]
            with mock.patch.object(mod, 'Config', FakeConfig), _silence_stdio():
                cli_ref = mod.get_image_name(
                    pushed_registry,
                    ['isaac_ros'],
                    'arm64-jetpack',
                    include_hash=True,
                    build_args=build_args,
                )
            self.assertIn(cli_ref, target['tags'])

    def test_isaac_ros_hash_inputs_include_local_cli_debian(self):
        mod = self.build_image_layers

        with TemporaryDirectory() as tmpdir:
            context = Path(tmpdir)
            dockerfile_path = context / 'Dockerfile.isaac_ros'
            dockerfile_path.write_text('FROM scratch\n', encoding='utf-8')

            base_hash = mod.Dockerfile(
                dockerfile_path,
                context,
                mod.ImageKey(['isaac_ros']),
            ).md5_hash()

            override_dir = context / '.docker-deb-overrides'
            override_dir.mkdir()
            override_deb = override_dir / 'isaac-ros-cli_1.0.0_all.deb'
            override_deb.write_text('first local package\n', encoding='utf-8')
            first_override_hash = mod.Dockerfile(
                dockerfile_path,
                context,
                mod.ImageKey(['isaac_ros']),
            ).md5_hash()

            override_deb.write_text('second local package\n', encoding='utf-8')
            second_override_hash = mod.Dockerfile(
                dockerfile_path,
                context,
                mod.ImageKey(['isaac_ros']),
            ).md5_hash()

        self.assertNotEqual(base_hash, first_override_hash)
        self.assertNotEqual(first_override_hash, second_override_hash)

    def test_apt_build_args_are_applied_to_each_bake_target(self):
        mod = self.build_image_layers
        plan = self._make_plan()
        build_args = {
            'ISAAC_DEBIAN_REPOSITORY': 'https://apt.example.test/isaac-ros',
            'ISAAC_DEBIAN_COMPONENTS': 'main preview',
        }

        def fake_md5hash(image_build_plan):
            return 'hash_' + '-'.join(
                dockerfile.image_key() for dockerfile in image_build_plan.dockerfiles_)

        with mock.patch.object(mod.ImageBuildPlan, 'md5hash', fake_md5hash):
            bake_dict = plan.generate_bake_dict(
                'aarch64',
                'registry.example.com/cache',
                'registry.example.com/cache',
                extra_build_args=build_args,
                isaac_ros_platform='arm64-jetpack',
            )

        for target in bake_dict['targets'].values():
            self.assertEqual(
                target['args']['ISAAC_DEBIAN_REPOSITORY'],
                'https://apt.example.test/isaac-ros',
            )
            self.assertEqual(
                target['args']['ISAAC_DEBIAN_COMPONENTS'],
                'main preview',
            )
            self.assertEqual(
                target['args']['ISAAC_DEBIAN_DISTRO_SUFFIX'],
                '-jetpack',
            )

    def test_fastos_uses_fastos_apt_distro_suffix(self):
        mod = self.build_image_layers
        plan = self._make_plan()

        def fake_md5hash(image_build_plan):
            return 'hash_' + '-'.join(
                dockerfile.image_key() for dockerfile in image_build_plan.dockerfiles_)

        with mock.patch.object(mod.ImageBuildPlan, 'md5hash', fake_md5hash):
            bake_dict = plan.generate_bake_dict(
                'aarch64',
                'registry.example.com/cache',
                'registry.example.com/cache',
                isaac_ros_platform='arm64-fastos',
            )

        for target in bake_dict['targets'].values():
            self.assertEqual(target['args']['ISAAC_DEBIAN_DISTRO_SUFFIX'], '-fastos')


class TestBuildImageLayersMain(unittest.TestCase):
    """Verify high-risk orchestration behavior in main()."""

    @classmethod
    def setUpClass(cls):
        cls.build_image_layers = _import_build_image_layers()

    def _make_plan(self):
        mod = self.build_image_layers
        with _silence_stdio():
            dockerfiles = [
                mod.Dockerfile(
                    Path('/tmp/Dockerfile.isaac_ros'),
                    Path('/tmp/context'),
                    mod.ImageKey(['isaac_ros'])
                ),
                mod.Dockerfile(
                    Path('/tmp/Dockerfile.realsense'),
                    Path('/tmp/context'),
                    mod.ImageKey(['realsense'])
                ),
                mod.Dockerfile(
                    Path('/tmp/Dockerfile.custom'),
                    Path('/tmp/context'),
                    mod.ImageKey(['custom'])
                ),
            ]
        return mod.ImageBuildPlan(dockerfiles)

    def _patch_config(self, platform_):
        class FakeConfig:
            def __init__(self, platform_):
                self.target_image_name_ = None
                self.image_key_order_ = ['isaac_ros', 'realsense', 'custom']
                self.docker_search_dirs_ = ['/tmp/context']
                self.cache_to_registry_names_ = ['registry.example.com/cache']
                self.cache_from_registry_names_ = ['registry.example.com/cache']
                self.remote_builder_ = None
                self.build_args_ = {}
                self.verbose_ = False
                self.platform_ = platform_
                self.base_image_ = None
                self.context_dir_ = None
                self.context_overrides_ = {}
                self.s3_cache_ = None

            def load_shell_common_config(self):
                return False

            def load_yaml(self, config_file):
                return False

        return mock.patch.object(self.build_image_layers, 'Config', FakeConfig)

    def _run_main(self, **kwargs):
        mod = self.build_image_layers
        plan = self._make_plan()
        commands = []

        def fake_md5hash(image_build_plan):
            return 'hash_' + '-'.join(
                dockerfile.image_key() for dockerfile in image_build_plan.dockerfiles_)

        def fake_run_shell(command, *args, **kwargs):
            commands.append(command)
            return True, '', ''

        with (
            self._patch_config(kwargs.get('platform_', 'x86_64')),
            mock.patch.object(mod, 'resolve_dockerfiles', return_value=plan),
            mock.patch.object(
                mod, 'check_docker_logins', return_value='registry.example.com/cache'),
            mock.patch.object(
                mod, 'check_docker_image_exists', return_value=False) as image_exists,
            mock.patch.object(
                mod.Dockerfile,
                'md5_hash',
                lambda dockerfile: f'filehash_{dockerfile.image_key()}'
            ),
            mock.patch.object(mod.ImageBuildPlan, 'md5hash', fake_md5hash),
            mock.patch.object(mod, 'run_shell', side_effect=fake_run_shell),
            _silence_stdio(),
        ):
            mod.main({'isaac_ros', 'realsense', 'custom'}, **kwargs)
            target_names = plan.target_names()

        return target_names, commands, image_exists

    def test_leaf_only_builds_only_final_layer_target(self):
        target_names, commands, image_exists = self._run_main(
            platform_='x86_64',
            push=True,
            use_kubernetes_driver=True,
            isaac_ros_platform='amd64',
            leaf_only=True,
            include_layer_depends_on=False,
        )

        bake_commands = [command for command in commands if ' buildx bake ' in command]

        self.assertEqual(len(bake_commands), 1)
        self.assertIn(target_names[-1], bake_commands[0])
        self.assertNotIn(target_names[0], bake_commands[0])
        self.assertNotIn(target_names[1], bake_commands[0])
        image_exists.assert_called_once_with(
            f'registry.example.com/cache/{target_names[-1]}-amd64:latest'
        )

    def test_kubernetes_builder_uses_ttl_annotation_and_is_removed(self):
        _, commands, _ = self._run_main(
            platform_='x86_64',
            push=True,
            use_kubernetes_driver=True,
            isaac_ros_platform='amd64',
            leaf_only=True,
            include_layer_depends_on=False,
        )

        create_commands = [
            command for command in commands
            if command.startswith('docker buildx create --driver kubernetes')
        ]
        remove_commands = [
            command for command in commands
            if command.startswith('docker buildx rm ')
        ]

        self.assertEqual(len(create_commands), 1)
        self.assertIn('--driver-opt "annotations=janitor/ttl=6h"', create_commands[0])
        self.assertIn(
            '\'--driver-opt="nodeselector='
            'kubernetes.io/arch=amd64,'
            'eks.amazonaws.com/nodegroup=x86-node-group-m6i-4xlarge-v1"\'',
            create_commands[0]
        )
        self.assertIn('--driver-opt timeout=10m', create_commands[0])
        self.assertEqual(len(remove_commands), 1)
        self.assertRegex(remove_commands[0], r'^docker buildx rm isaaceks-x86_64-[a-z0-9]{8}$')

    def test_kubernetes_builder_uses_arm_nodegroup_for_arm_builds(self):
        _, commands, _ = self._run_main(
            platform_='aarch64',
            push=True,
            use_kubernetes_driver=True,
            isaac_ros_platform='arm64',
            leaf_only=True,
            include_layer_depends_on=False,
        )

        create_commands = [
            command for command in commands
            if command.startswith('docker buildx create --driver kubernetes')
        ]

        self.assertEqual(len(create_commands), 1)
        self.assertIn(
            '\'--driver-opt="nodeselector='
            'kubernetes.io/arch=arm64,'
            'eks.amazonaws.com/nodegroup=arm-node-group-m7g-4xlarge-v1"\'',
            create_commands[0]
        )

    def test_non_leaf_builds_each_resolved_layer_target(self):
        target_names, commands, _ = self._run_main(
            platform_='x86_64',
            push=True,
            use_kubernetes_driver=True,
            isaac_ros_platform='amd64',
            leaf_only=False,
        )

        bake_commands = [command for command in commands if ' buildx bake ' in command]

        self.assertEqual(len(bake_commands), 3)
        self.assertEqual(len(target_names), len(bake_commands))
        for target_name, command in zip(target_names, bake_commands):
            self.assertIn(target_name, command)


if __name__ == '__main__':
    unittest.main()
