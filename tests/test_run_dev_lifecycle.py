# Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

"""Tests for run_dev.py lifecycle modes (build / start / run).

These tests verify that the --mode argument correctly separates image
acquisition from container lifecycle management.
"""

import contextlib
import importlib
import io
import os
import sys
import types
import unittest
from unittest import mock


@contextlib.contextmanager
def _silence_stdio():
    """Suppress incidental CLI output so unittest logs only reflect pass/fail state."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


def _import_run_dev():
    """Import run_dev.py while stubbing its heavy dependencies."""
    run_dev_dir = os.path.join(
        os.path.dirname(__file__), '..', 'scripts', 'run_dev')
    run_dev_dir = os.path.abspath(run_dev_dir)

    stub_build = types.ModuleType('build_image_layers')
    stub_build.main = mock.MagicMock()
    stub_build.check_docker_logins = mock.MagicMock(return_value='registry.example.com')
    stub_build.get_image_name = mock.MagicMock(return_value='registry.example.com/image:latest')

    stub_config = types.ModuleType('isaac_ros_common_config_utils')
    stub_config.get_isaac_ros_common_config_path = mock.MagicMock(return_value='/fake/config.yaml')
    stub_config.get_isaac_ros_common_config_values = mock.MagicMock(return_value={
        'image_key_order': ['isaac_ros'],
        'cache_from_registry_names': ['registry.example.com'],
    })
    stub_config.get_build_order = mock.MagicMock(
        return_value=['isaac_ros', 'realsense'])

    sys.modules['build_image_layers'] = stub_build
    sys.modules['isaac_ros_common_config_utils'] = stub_config

    if run_dev_dir not in sys.path:
        sys.path.insert(0, run_dev_dir)

    if 'run_dev' in sys.modules:
        mod = importlib.reload(sys.modules['run_dev'])
    else:
        mod = importlib.import_module('run_dev')

    return mod


class TestParseArgsMode(unittest.TestCase):
    """Verify --mode argument parsing."""

    @classmethod
    def setUpClass(cls):
        cls.run_dev = _import_run_dev()

    def _parse(self, extra_args=None):
        argv = ['run_dev.py', '--isaac-dir', '/tmp/fake']
        if extra_args:
            argv.extend(extra_args)
        with mock.patch('sys.argv', argv), _silence_stdio():
            return self.run_dev.parse_args()

    def test_default_mode_is_run(self):
        args = self._parse()
        self.assertEqual(args.mode, 'run')

    def test_default_env_uses_consolidated_base_image(self):
        args = self._parse()
        self.assertEqual(args.env, ['isaac_ros', 'realsense'])

    def test_default_push_is_false(self):
        args = self._parse()
        self.assertFalse(args.push)

    def test_push_flag_sets_push_true(self):
        args = self._parse(['--push'])
        self.assertTrue(args.push)

    def test_no_push_flag_sets_push_false(self):
        args = self._parse(['--no-push'])
        self.assertFalse(args.push)

    def test_mode_build(self):
        args = self._parse(['--mode', 'build'])
        self.assertEqual(args.mode, 'build')

    def test_mode_start(self):
        args = self._parse(['--mode', 'start'])
        self.assertEqual(args.mode, 'start')

    def test_mode_run_explicit(self):
        args = self._parse(['--mode', 'run'])
        self.assertEqual(args.mode, 'run')

    def test_invalid_mode_rejected(self):
        with self.assertRaises(SystemExit):
            self._parse(['--mode', 'bogus'])

    def test_build_arg_can_be_repeated(self):
        args = self._parse([
            '--build-arg', 'ISAAC_DEBIAN_REPOSITORY=https://apt.example.test/isaac-ros',
            '--build-arg', 'ISAAC_DEBIAN_COMPONENTS=main preview',
        ])

        self.assertEqual(
            args.build_args,
            [
                'ISAAC_DEBIAN_REPOSITORY=https://apt.example.test/isaac-ros',
                'ISAAC_DEBIAN_COMPONENTS=main preview',
            ],
        )


class TestRunDevBuildArgs(unittest.TestCase):
    """Verify run_dev.py forwards Docker build args without interpreting them."""

    @classmethod
    def setUpClass(cls):
        cls.run_dev = _import_run_dev()

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/tmp/fake'})
    def test_build_mode_forwards_cli_build_args(self):
        build_args = [
            'ISAAC_DEBIAN_REPOSITORY=https://apt.example.test/isaac-ros',
            'ISAAC_DEBIAN_COMPONENTS=main preview',
        ]
        with mock.patch('sys.argv', [
            'run_dev.py', '--mode', 'build', '--build',
            '--isaac-dir', '/tmp/fake',
            '--build-arg', build_args[0],
            '--build-arg', build_args[1],
        ]):
            with contextlib.ExitStack() as stack:
                stack.enter_context(
                    mock.patch.object(self.run_dev, 'validate_prerequisites')
                )
                m_resolve = stack.enter_context(
                    mock.patch.object(
                        self.run_dev,
                        'resolve_target_image',
                        return_value=('img:latest', 'reg', 'cached:latest'),
                    )
                )
                m_ensure = stack.enter_context(
                    mock.patch.object(self.run_dev, 'ensure_image_available')
                )
                with _silence_stdio():
                    self.run_dev.main()

        self.assertEqual(m_resolve.call_args.kwargs['build_args'], build_args)
        self.assertEqual(m_ensure.call_args.kwargs['build_args'], build_args)

    def test_resolve_target_image_hashes_build_args(self):
        build_args = ['ISAAC_DEBIAN_REPOSITORY=https://apt.example.test/isaac-ros']
        args = types.SimpleNamespace(
            no_cache=False,
            use_cached_build_image=False,
            isaac_ros_platform='amd64',
        )
        config = {'cache_from_registry_names': ['registry.example.com']}

        with mock.patch.object(self.run_dev, 'check_docker_logins',
                               return_value='registry.example.com'), \
             mock.patch.object(self.run_dev, 'get_image_name',
                               return_value='img:latest') as m_get_image_name:
            result = self.run_dev.resolve_target_image(
                args, config, ['isaac_ros'], build_args=build_args)

        self.assertEqual(result, ('img:latest', 'registry.example.com',
                                  'cached_isaac_run_dev_image_local:latest'))
        m_get_image_name.assert_called_once_with(
            'registry.example.com',
            ['isaac_ros'],
            'amd64',
            include_hash=True,
            build_args=build_args,
        )

    def test_ensure_image_available_forwards_build_args_to_builder(self):
        build_args = ['ISAAC_DEBIAN_REPOSITORY=https://apt.example.test/isaac-ros']
        args = types.SimpleNamespace(
            use_cached_build_image=False,
            build=True,
            build_local=False,
            push=False,
            verbose=False,
            no_cache=False,
            isaac_ros_platform='amd64',
        )

        with mock.patch.object(self.run_dev, 'make_docker_image_available',
                               side_effect=[False, True]), \
             mock.patch.object(self.run_dev, 'build_image_layers') as m_build:
            self.run_dev.ensure_image_available(
                args,
                'img:latest',
                'cached:latest',
                '/fake/config.yaml',
                ['isaac_ros'],
                build_args=build_args,
            )

        self.assertEqual(m_build.call_args.kwargs['build_args'], build_args)


class TestBuildModeSkipsContainer(unittest.TestCase):
    """build mode must resolve/build the image and never touch containers."""

    @classmethod
    def setUpClass(cls):
        cls.run_dev = _import_run_dev()

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/tmp/fake'})
    def test_build_mode_does_not_start_container(self):
        with mock.patch('sys.argv', [
            'run_dev.py', '--mode', 'build', '--build',
            '--isaac-dir', '/tmp/fake',
        ]):
            with mock.patch.object(self.run_dev, 'validate_prerequisites'), \
                 mock.patch.object(self.run_dev, 'resolve_target_image',
                                   return_value=('img:latest', 'reg', 'cached:latest')), \
                 mock.patch.object(self.run_dev, 'ensure_image_available') as m_ensure, \
                 mock.patch.object(self.run_dev, 'start_container') as m_start, \
                 mock.patch.object(self.run_dev, 'remove_exited_container') as m_remove, \
                 mock.patch.object(self.run_dev, 'attach_to_running_container') as m_attach:

                with _silence_stdio():
                    self.run_dev.main()

                m_ensure.assert_called_once()
                m_start.assert_not_called()
                m_remove.assert_not_called()
                m_attach.assert_not_called()


class TestStartModeSkipsBuild(unittest.TestCase):
    """start mode must not trigger a build; it should fail if image is missing."""

    @classmethod
    def setUpClass(cls):
        cls.run_dev = _import_run_dev()

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/tmp/fake'})
    def test_start_mode_does_not_build(self):
        with mock.patch('sys.argv', [
            'run_dev.py', '--mode', 'start', '--isaac-dir', '/tmp/fake',
        ]):
            with mock.patch.object(self.run_dev, 'validate_prerequisites'), \
                 mock.patch.object(self.run_dev, 'resolve_target_image',
                                   return_value=('img:latest', 'reg', 'cached:latest')), \
                 mock.patch.object(self.run_dev, 'check_local_image_exists',
                                   return_value=True), \
                 mock.patch.object(self.run_dev, 'ensure_image_available') as m_ensure, \
                 mock.patch.object(self.run_dev, 'start_container') as m_start:

                with _silence_stdio():
                    self.run_dev.main()

                m_ensure.assert_not_called()
                m_start.assert_called_once()

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/tmp/fake'})
    def test_start_mode_exits_when_image_missing(self):
        with mock.patch('sys.argv', [
            'run_dev.py', '--mode', 'start', '--isaac-dir', '/tmp/fake',
        ]):
            with mock.patch.object(self.run_dev, 'validate_prerequisites'), \
                 mock.patch.object(self.run_dev, 'resolve_target_image',
                                   return_value=('img:latest', 'reg', 'cached:latest')), \
                 mock.patch.object(self.run_dev, 'check_local_image_exists',
                                   return_value=False), \
                 mock.patch.object(self.run_dev, 'start_container') as m_start:

                with self.assertRaises(SystemExit) as ctx, _silence_stdio():
                    self.run_dev.main()

                self.assertEqual(ctx.exception.code, 1)
                m_start.assert_not_called()


class TestCheckLocalImageExists(unittest.TestCase):
    """Verify the local image probe uses a valid subprocess.run signature."""

    @classmethod
    def setUpClass(cls):
        cls.run_dev = _import_run_dev()

    def test_uses_devnull_without_capture_output(self):
        completed = mock.Mock(returncode=0)
        with mock.patch.object(self.run_dev.subprocess, 'run', return_value=completed) as m_run:
            self.assertTrue(self.run_dev.check_local_image_exists('img:latest'))

        m_run.assert_called_once_with(
            ['docker', 'image', 'inspect', 'img:latest'],
            stdout=self.run_dev.subprocess.DEVNULL,
            stderr=self.run_dev.subprocess.DEVNULL,
        )


class TestGpuDockerArgs(unittest.TestCase):
    """Verify GPU device injection for IGX and other supported hosts."""

    @classmethod
    def setUpClass(cls):
        cls.run_dev = _import_run_dev()

    def test_non_igx_uses_gpus_flag(self):
        with mock.patch.object(self.run_dev.os.path, 'isfile', return_value=False), \
             mock.patch.object(self.run_dev.subprocess, 'check_output') as m_check_output:
            result = self.run_dev.get_gpu_docker_args('aarch64')

        self.assertEqual(result, ['--gpus all'])
        m_check_output.assert_not_called()

    def test_x86_ignores_igx_release_marker(self):
        with mock.patch.object(self.run_dev.os.path, 'isfile', return_value=True), \
             mock.patch.object(self.run_dev.subprocess, 'check_output') as m_check_output:
            result = self.run_dev.get_gpu_docker_args('x86_64')

        self.assertEqual(result, ['--gpus all'])
        m_check_output.assert_not_called()

    def test_igx_uses_cdi_gpu_device(self):
        cdi_output = 'nvidia.com/gpu=0\nnvidia.com/gpu=all\nnvidia.com/pva=all\n'
        with mock.patch.object(self.run_dev.os.path, 'isfile', return_value=True), \
             mock.patch.object(
                 self.run_dev.subprocess, 'check_output', return_value=cdi_output
             ) as m_check_output:
            result = self.run_dev.get_gpu_docker_args('aarch64')

        self.assertEqual(result, ['--device=nvidia.com/gpu=all'])
        m_check_output.assert_called_once_with(
            ['/usr/bin/nvidia-ctk', 'cdi', 'list'],
            text=True,
            stderr=self.run_dev.subprocess.DEVNULL,
        )

    def test_igx_falls_back_to_explicit_nvidia_runtime(self):
        with mock.patch.object(self.run_dev.os.path, 'isfile', return_value=True), \
             mock.patch.object(
                 self.run_dev.subprocess, 'check_output', side_effect=FileNotFoundError
             ):
            result = self.run_dev.get_gpu_docker_args('aarch64')

        self.assertEqual(result, ['--runtime=nvidia', '--gpus all'])

    def test_igx_falls_back_when_cdi_list_fails(self):
        cdi_error = self.run_dev.subprocess.CalledProcessError(
            1, ['/usr/bin/nvidia-ctk', 'cdi', 'list'])
        with mock.patch.object(self.run_dev.os.path, 'isfile', return_value=True), \
             mock.patch.object(
                 self.run_dev.subprocess, 'check_output', side_effect=cdi_error
             ):
            result = self.run_dev.get_gpu_docker_args('aarch64')

        self.assertEqual(result, ['--runtime=nvidia', '--gpus all'])

    def test_igx_without_all_cdi_device_uses_explicit_nvidia_runtime(self):
        with mock.patch.object(self.run_dev.os.path, 'isfile', return_value=True), \
             mock.patch.object(
                 self.run_dev.subprocess,
                 'check_output',
                 return_value='nvidia.com/gpu=0\nnvidia.com/pva=all\n',
             ):
            result = self.run_dev.get_gpu_docker_args('aarch64')

        self.assertEqual(result, ['--runtime=nvidia', '--gpus all'])

    def test_run_container_uses_selected_gpu_arguments(self):
        args = types.SimpleNamespace(
            platform='aarch64',
            isaac_ros_platform='arm64-jetpack',
            verbose=False,
        )
        with (
            mock.patch.object(self.run_dev, 'get_docker_args', return_value=[]),
            mock.patch.object(self.run_dev, 'load_docker_args_from_file', return_value=[]),
            mock.patch.object(
                self.run_dev,
                'get_gpu_docker_args',
                return_value=['--device=nvidia.com/gpu=all'],
            ),
            mock.patch.object(self.run_dev.subprocess, 'run') as m_run,
            _silence_stdio(),
        ):
            self.run_dev.run_docker_container(
                args,
                'isaac_ros_dev_container',
                'isaac_ros:latest',
                '/workspaces/isaac_ros-dev',
            )

        command = m_run.call_args.args[0]
        self.assertIn('--device=nvidia.com/gpu=all', command)
        self.assertNotIn('--gpus all', command)


class TestRunModePreservesDefaultBehavior(unittest.TestCase):
    """Default run mode must attach first, otherwise ensure the image and start."""

    @classmethod
    def setUpClass(cls):
        cls.run_dev = _import_run_dev()

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/tmp/fake'})
    def test_run_mode_ensures_image_and_starts(self):
        with mock.patch('sys.argv', [
            'run_dev.py', '--mode', 'run', '--build',
            '--isaac-dir', '/tmp/fake',
        ]):
            with mock.patch.object(self.run_dev, 'validate_prerequisites'), \
                 mock.patch.object(self.run_dev, 'remove_exited_container') as m_remove, \
                 mock.patch.object(self.run_dev, 'attach_to_running_container',
                                   return_value=False) as m_attach, \
                 mock.patch.object(self.run_dev, 'resolve_target_image',
                                   return_value=('img:latest', 'reg', 'cached:latest')), \
                 mock.patch.object(self.run_dev, 'ensure_image_available') as m_ensure, \
                 mock.patch.object(self.run_dev, 'start_container') as m_start:

                with _silence_stdio():
                    self.run_dev.main()

                m_remove.assert_called_once()
                m_attach.assert_called_once()
                m_ensure.assert_called_once()
                m_start.assert_called_once()

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/tmp/fake'})
    def test_run_mode_attaches_before_image_resolution(self):
        with mock.patch('sys.argv', [
            'run_dev.py', '--mode', 'run', '--build', '--isaac-dir', '/tmp/fake',
        ]):
            with mock.patch.object(self.run_dev, 'validate_prerequisites'), \
                 mock.patch.object(self.run_dev, 'remove_exited_container') as m_remove, \
                 mock.patch.object(self.run_dev, 'attach_to_running_container',
                                   return_value=True) as m_attach, \
                 mock.patch.object(self.run_dev, 'resolve_target_image') as m_resolve, \
                 mock.patch.object(self.run_dev, 'ensure_image_available') as m_ensure, \
                 mock.patch.object(self.run_dev, 'start_container') as m_start:

                with _silence_stdio():
                    self.run_dev.main()

                m_remove.assert_called_once()
                m_attach.assert_called_once()
                m_resolve.assert_not_called()
                m_ensure.assert_not_called()
                m_start.assert_not_called()

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/tmp/fake'})
    def test_implicit_default_is_run_mode(self):
        """Omitting --mode should behave identically to --mode run."""
        with mock.patch('sys.argv', [
            'run_dev.py', '--build', '--isaac-dir', '/tmp/fake',
        ]):
            with mock.patch.object(self.run_dev, 'validate_prerequisites'), \
                 mock.patch.object(self.run_dev, 'remove_exited_container') as m_remove, \
                 mock.patch.object(self.run_dev, 'attach_to_running_container',
                                   return_value=False) as m_attach, \
                 mock.patch.object(self.run_dev, 'resolve_target_image',
                                   return_value=('img:latest', 'reg', 'cached:latest')), \
                 mock.patch.object(self.run_dev, 'ensure_image_available') as m_ensure, \
                 mock.patch.object(self.run_dev, 'start_container') as m_start:

                with _silence_stdio():
                    self.run_dev.main()

                m_remove.assert_called_once()
                m_attach.assert_called_once()
                m_ensure.assert_called_once()
                m_start.assert_called_once()


if __name__ == '__main__':
    unittest.main()
