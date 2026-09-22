# Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

"""Tests for candidate image arguments derived from the packaged CLI config."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from isaac_ros_cli.commands.activate.docker import _get_isaac_debian_build_args
from isaac_ros_cli.config import IsaacRosCliConfig
import yaml


CLI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLI_ROOT / "scripts"))

from isaac_debian_build_args import (  # noqa: E402,I100
    ConfigError,
    isaac_debian_build_args,
)


class IsaacDebianBuildArgsTest(unittest.TestCase):
    """Keep candidate image inputs identical to activation inputs."""

    def test_shipped_config_matches_activation_build_args(self) -> None:
        config_path = CLI_ROOT / "config" / "config.yaml"
        config = IsaacRosCliConfig.parse_obj(
            yaml.safe_load(config_path.read_text(encoding="utf-8"))
        )

        self.assertEqual(
            isaac_debian_build_args(config_path),
            _get_isaac_debian_build_args(config),
        )

    def test_debian_package_installs_the_same_config(self) -> None:
        install_manifest = (
            CLI_ROOT / "debian" / "isaac-ros-cli.install"
        ).read_text(encoding="utf-8").splitlines()

        self.assertIn(
            "config/config.yaml usr/share/isaac-ros-cli/",
            install_manifest,
        )

    def test_rejects_missing_apt_configuration(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("version: 2\n", encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "apt mapping"):
                isaac_debian_build_args(config_path)


if __name__ == "__main__":
    unittest.main()
