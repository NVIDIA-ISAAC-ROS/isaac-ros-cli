# Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

"""Tests for the Docker activation CLI layer.

Covers _build_run_dev_command flag forwarding and the Click-level
--build-only / --start-only options.
"""

import os
import unittest
from unittest import mock

from isaac_ros_cli.commands.activate.docker import (
    _build_run_dev_command,
    _get_isaac_debian_build_args,
)
from isaac_ros_cli.config import IsaacRosCliConfig, SUPPORTED_CONFIG_VERSION
from isaac_ros_cli.platform import Platform


def _make_cfg(apt=None):
    cfg = {
        'version': SUPPORTED_CONFIG_VERSION,
        'docker': {
            'image': {
                'base_image_keys': ['isaac_ros'],
                'additional_image_keys': ['custom'],
                'push': False,
            },
            'run': {
                'container_name': 'test_container',
                'entrypoint': '/entrypoint.sh',
                'workdir': '/workspace',
                'platform': 'auto',
                'use_cached_build_image': False,
            },
        },
    }
    if apt is not None:
        cfg['apt'] = apt
    return IsaacRosCliConfig.parse_obj(cfg)


class TestBuildRunDevCommand(unittest.TestCase):
    """Verify _build_run_dev_command produces correct argument lists."""

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/ws/isaac'})
    def test_build_only_forwards_mode_build(self):
        cmd = _build_run_dev_command(
            _make_cfg(),
            build=True, build_local=False, push=False,
            use_cached_build_image=False, no_cache=False, verbose=False,
            isaac_ros_platform=Platform.AMD64,
            build_only=True, start_only=False,
        )
        self.assertIn('--mode', cmd)
        mode_idx = cmd.index('--mode')
        self.assertEqual(cmd[mode_idx + 1], 'build')
        self.assertIn('--no-push', cmd)
        self.assertNotIn('--push', cmd)

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/ws/isaac'})
    def test_start_only_forwards_mode_start(self):
        cmd = _build_run_dev_command(
            _make_cfg(),
            build=False, build_local=False, push=False,
            use_cached_build_image=False, no_cache=False, verbose=False,
            isaac_ros_platform=Platform.AMD64,
            build_only=False, start_only=True,
        )
        self.assertIn('--mode', cmd)
        mode_idx = cmd.index('--mode')
        self.assertEqual(cmd[mode_idx + 1], 'start')

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/ws/isaac'})
    def test_default_omits_mode_flag(self):
        cmd = _build_run_dev_command(
            _make_cfg(),
            build=False, build_local=False, push=False,
            use_cached_build_image=False, no_cache=False, verbose=False,
            isaac_ros_platform=Platform.AMD64,
            build_only=False, start_only=False,
        )
        self.assertNotIn('--mode', cmd)

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/ws/isaac'})
    def test_build_local_flag_forwarded(self):
        cmd = _build_run_dev_command(
            _make_cfg(),
            build=False, build_local=True, push=False,
            use_cached_build_image=False, no_cache=False, verbose=False,
            isaac_ros_platform=Platform.AMD64,
            build_only=True, start_only=False,
        )
        self.assertIn('--build-local', cmd)
        mode_idx = cmd.index('--mode')
        self.assertEqual(cmd[mode_idx + 1], 'build')

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/ws/isaac'})
    def test_build_remote_flag_forwarded(self):
        cmd = _build_run_dev_command(
            _make_cfg(),
            build=True, build_local=False, push=False,
            use_cached_build_image=False, no_cache=False, verbose=False,
            isaac_ros_platform=Platform.AMD64,
            build_only=True, start_only=False,
        )
        self.assertIn('--build', cmd)
        self.assertNotIn('--build-local', cmd)

    @mock.patch.dict(os.environ, {'ISAAC_DIR': '/ws/isaac'})
    def test_push_flag_forwarded_explicitly(self):
        cmd = _build_run_dev_command(
            _make_cfg(),
            build=True, build_local=False, push=True,
            use_cached_build_image=False, no_cache=False, verbose=False,
            isaac_ros_platform=Platform.AMD64,
            build_only=True, start_only=False,
        )
        self.assertIn('--push', cmd)
        self.assertNotIn('--no-push', cmd)

    @mock.patch.dict(os.environ, {'ISAAC_ROS_WS': '/ws/isaac_ros_ws'}, clear=True)
    def test_isaac_ros_ws_forwarded_as_run_dev_isaac_dir(self):
        cmd = _build_run_dev_command(
            _make_cfg(),
            build=False, build_local=False, push=False,
            use_cached_build_image=False, no_cache=False, verbose=False,
            isaac_ros_platform=Platform.AMD64,
            build_only=False, start_only=False,
        )
        isaac_dir_idx = cmd.index('--isaac-dir')
        self.assertEqual(cmd[isaac_dir_idx + 1], '/ws/isaac_ros_ws')

    @mock.patch.dict(os.environ, {'ISAAC_ROS_WS': '/ws/isaac'}, clear=True)
    def test_configured_apt_build_args_are_forwarded_to_run_dev(self):
        cmd = _build_run_dev_command(
            _make_cfg(apt={
                'key_url': 'https://apt.example.test/repos.key',
                'repository': 'https://apt.example.test/isaac-ros',
                'distro': 'auto',
                'components': ['main', 'extra-main'],
            }),
            build=True, build_local=False, push=False,
            use_cached_build_image=False, no_cache=False, verbose=False,
            isaac_ros_platform=Platform.AMD64,
            build_only=True, start_only=False,
        )

        build_arg_values = [
            cmd[i + 1] for i, value in enumerate(cmd)
            if value == '--build-arg'
        ]
        self.assertEqual(
            build_arg_values,
            [
                'ISAAC_DEBIAN_KEY_URL=https://apt.example.test/repos.key',
                'ISAAC_DEBIAN_REPOSITORY=https://apt.example.test/isaac-ros',
                'ISAAC_DEBIAN_COMPONENTS=main extra-main',
            ],
        )


class TestIsaacDebianBuildArgs(unittest.TestCase):
    """Verify apt config becomes Docker build args without policy in run_dev.py."""

    def test_literal_distro_is_forwarded_when_configured(self):
        build_args = _get_isaac_debian_build_args(
            _make_cfg(apt={
                'key_url': 'https://apt.example.test/repos.key',
                'repository': 'https://apt.example.test/isaac-ros',
                'distro': 'noble',
                'components': ['main'],
            })
        )

        self.assertEqual(
            build_args,
            [
                'ISAAC_DEBIAN_KEY_URL=https://apt.example.test/repos.key',
                'ISAAC_DEBIAN_REPOSITORY=https://apt.example.test/isaac-ros',
                'ISAAC_DEBIAN_COMPONENTS=main',
                'ISAAC_DEBIAN_DIST=noble',
            ],
        )

    def test_config_without_apt_omits_apt_build_args(self):
        self.assertEqual(_get_isaac_debian_build_args(_make_cfg()), [])


if __name__ == '__main__':
    unittest.main()
