# Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from isaac_ros_cli.config import (
    ConfigScope,
    InvalidConfigError,
    parse_config_override,
    SUPPORTED_CONFIG_VERSION,
)
from isaac_ros_cli.config import loader as config_loader
import yaml


class ConfigLoaderTests(unittest.TestCase):

    def setUp(self):
        self._tmpdir = TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.env_file = self.root / "environment.conf"
        self.read_only = self.root / "usr-share-config.yaml"
        self.system = self.root / "etc-config.yaml"
        self.user = self.root / "user-config.yaml"
        self.workspace = self.root / "workspace-config.yaml"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _patch_sources(self):
        return patch.object(
            config_loader,
            "_CONFIG_SOURCE_CANDIDATES",
            {
                ConfigScope.READ_ONLY: self.read_only,
                ConfigScope.SYSTEM: self.system,
                ConfigScope.USER: self.user,
                ConfigScope.WORKSPACE: self.workspace,
            },
        )

    def _full_config(self):
        return {
            "version": SUPPORTED_CONFIG_VERSION,
            "docker": {
                "image": {
                    "base_image_keys": ["base"],
                    "additional_image_keys": [],
                    "push": False,
                },
                "run": {
                    "container_name": "read_only",
                    "entrypoint": "/entrypoint.sh",
                    "workdir": "/workspace",
                    "platform": "auto",
                    "use_cached_build_image": False,
                },
            },
            "apt": {
                "key_url": "https://apt.example.test/repos.key",
                "repository": "https://apt.example.test/default",
                "distro": "auto",
                "components": ["main"],
            },
        }

    def test_load_environment_mode_reads_expected_key(self):
        """Prove mode parsing ignores file shape noise and reads the canonical environment key."""
        self.env_file.write_text("ISAAC_ROS_ENVIRONMENT=venv\n", encoding="utf-8")

        with patch.object(config_loader, "ENVIRONMENT_MODE_CONFIG_PATH", self.env_file):
            self.assertEqual(config_loader.load_environment_mode(), "venv")

    def test_load_environment_mode_requires_file(self):
        """Missing mode state should be treated as setup corruption, not silently defaulted."""
        with patch.object(config_loader, "ENVIRONMENT_MODE_CONFIG_PATH", self.env_file):
            with self.assertRaises(FileNotFoundError):
                config_loader.load_environment_mode()

    def test_load_environment_mode_requires_expected_key(self):
        """Reject malformed environment files so stale shell snippets do not masquerade as config.
        """
        self.env_file.write_text("NOT_THE_RIGHT_KEY=docker\n", encoding="utf-8")

        with patch.object(config_loader, "ENVIRONMENT_MODE_CONFIG_PATH", self.env_file):
            with self.assertRaises(KeyError):
                config_loader.load_environment_mode()

    def test_update_environment_mode_overwrites_file(self):
        """Assert that mode updates replace stale state instead of appending ambiguous entries."""
        self.env_file.write_text("ISAAC_ROS_ENVIRONMENT=uninitialized\n", encoding="utf-8")

        with patch.object(config_loader, "ENVIRONMENT_MODE_CONFIG_PATH", self.env_file):
            config_loader.update_environment_mode("docker")

        self.assertEqual(
            self.env_file.read_text(encoding="utf-8"),
            "ISAAC_ROS_ENVIRONMENT=docker\n",
        )

    def test_repo_default_config_uses_supported_schema_version(self):
        """Keep the shipped default YAML aligned with the validator's declared schema version."""
        shipped_config_path = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
        shipped_config = yaml.safe_load(shipped_config_path.read_text(encoding="utf-8"))

        self.assertEqual(
            shipped_config["version"],
            SUPPORTED_CONFIG_VERSION,
        )
        self.assertEqual(
            shipped_config["apt"]["key_url"],
            "https://isaac.download.nvidia.com/isaac-ros/repos.key",
        )
        self.assertEqual(
            shipped_config["apt"]["repository"],
            "https://isaac.download.nvidia.com/isaac-ros/release-5.0",
        )
        self.assertEqual(shipped_config["apt"]["distro"], "noble")
        self.assertEqual(shipped_config["apt"]["components"], ["main"])
        self.assertNotIn("snapshot", shipped_config["apt"])

    def test_repo_workspace_config_enables_internal_push_default(self):
        """Keep the monorepo workspace override aligned with internal image publishing."""
        workspace_config_path = (
            Path(__file__).resolve().parents[3] / ".isaac-ros-cli" / "config.yaml"
        )
        workspace_config = yaml.safe_load(workspace_config_path.read_text(encoding="utf-8"))

        self.assertEqual(workspace_config["version"], SUPPORTED_CONFIG_VERSION)
        self.assertTrue(workspace_config["docker"]["image"]["push"])

    def test_load_config_merges_all_available_sources_in_precedence_order(self):
        """Lock down the core precedence contract across read-only, system, user, and workspace."""
        self.read_only.write_text(
            yaml.safe_dump(self._full_config(), sort_keys=False),
            encoding="utf-8",
        )
        self.system.write_text(
            yaml.safe_dump({"docker": {"run": {"platform": "x86_64"}}}, sort_keys=False),
            encoding="utf-8",
        )
        self.user.write_text(
            yaml.safe_dump({"docker": {"run": {"container_name": "user_name"}}}, sort_keys=False),
            encoding="utf-8",
        )
        self.workspace.write_text(
            yaml.safe_dump(
                {"docker": {"image": {"additional_image_keys": ["zed"], "push": True}}},
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        with self._patch_sources():
            cfg = config_loader.load_config()

        self.assertEqual(cfg.version, SUPPORTED_CONFIG_VERSION)
        self.assertEqual(cfg.docker.run.container_name, "user_name")
        self.assertEqual(cfg.docker.run.platform, "x86_64")
        self.assertEqual(cfg.docker.image.base_image_keys, ["base"])
        self.assertEqual(cfg.docker.image.additional_image_keys, ["zed"])
        self.assertTrue(cfg.docker.image.push)

    def test_load_config_merges_apt_overlay(self):
        """APT source config uses the same overlay semantics as the rest of the config."""
        self.read_only.write_text(
            yaml.safe_dump(self._full_config(), sort_keys=False),
            encoding="utf-8",
        )
        self.user.write_text(
            yaml.safe_dump(
                {
                    "apt": {
                        "repository": "https://apt.example.test/override",
                        "components": ["main", "preview"],
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        with self._patch_sources():
            cfg = config_loader.load_config()

        self.assertEqual(cfg.apt.key_url, "https://apt.example.test/repos.key")
        self.assertEqual(cfg.apt.repository, "https://apt.example.test/override")
        self.assertEqual(cfg.apt.distro, "auto")
        self.assertEqual(cfg.apt.components, ["main", "preview"])

    def test_load_config_applies_command_line_overrides_last(self):
        """Command-line config overrides are the final non-persistent overlay."""
        self.read_only.write_text(
            yaml.safe_dump(self._full_config(), sort_keys=False),
            encoding="utf-8",
        )
        self.workspace.write_text(
            yaml.safe_dump({"docker": {"run": {"container_name": "workspace_name"}}},
                           sort_keys=False),
            encoding="utf-8",
        )

        with self._patch_sources():
            cfg = config_loader.load_config(
                extra_overlays=[
                    parse_config_override("docker.run.container_name=cli_name"),
                    parse_config_override("docker.run.use_cached_build_image=true"),
                    parse_config_override(
                        "docker.image.additional_image_keys=[zed, realsense]"
                    ),
                    parse_config_override("docker.image.push=true"),
                ]
            )

        self.assertEqual(cfg.docker.run.container_name, "cli_name")
        self.assertEqual(cfg.docker.run.platform, "auto")
        self.assertTrue(cfg.docker.run.use_cached_build_image)
        self.assertEqual(
            cfg.docker.image.additional_image_keys,
            ["zed", "realsense"],
        )
        self.assertTrue(cfg.docker.image.push)

    def test_load_config_rejects_unknown_command_line_override_keys(self):
        """Validate parsed command-line overrides against the same schema as config files."""
        self.read_only.write_text(
            yaml.safe_dump(self._full_config(), sort_keys=False),
            encoding="utf-8",
        )

        with self._patch_sources():
            with self.assertRaises(InvalidConfigError):
                config_loader.load_config(
                    extra_overlays=[
                        parse_config_override("docker.run.platfrom=x86_64")
                    ]
                )

    def test_load_config_raises_when_no_sources_exist(self):
        """Treat missing config layers as a hard setup problem so later consumers are not guessing.
        """
        with patch.object(
            config_loader,
            "_CONFIG_SOURCE_CANDIDATES",
            {
                ConfigScope.READ_ONLY: self.read_only,
                ConfigScope.SYSTEM: self.system,
                ConfigScope.USER: self.user,
                ConfigScope.WORKSPACE: None,
            },
        ):
            with self.assertRaises(FileNotFoundError) as ctx:
                config_loader.load_config()
        self.assertNotIn("None", str(ctx.exception))

    def test_load_config_rejects_non_mapping_yaml(self):
        """Reject structurally invalid YAML before any command tries to consume partial state."""
        self.read_only.write_text("- not-a-mapping\n", encoding="utf-8")

        with self._patch_sources():
            with self.assertRaises(InvalidConfigError):
                config_loader.load_config()

    def test_load_config_rejects_unknown_nested_key(self):
        """Typos in nested overrides must fail loudly instead of being ignored downstream."""
        self.read_only.write_text(
            yaml.safe_dump(self._full_config(), sort_keys=False),
            encoding="utf-8",
        )
        self.user.write_text(
            yaml.safe_dump({"docker": {"run": {"platfrom": "aarch64"}}}, sort_keys=False),
            encoding="utf-8",
        )

        with self._patch_sources():
            with self.assertRaises(InvalidConfigError):
                config_loader.load_config()

    def test_load_config_rejects_yaml_coerced_wrong_type(self):
        """Implicit YAML typing must not sneak non-strings into string-valued schema fields."""
        self.read_only.write_text(
            yaml.safe_dump(self._full_config(), sort_keys=False),
            encoding="utf-8",
        )
        self.user.write_text(
            "docker:\n  run:\n    workdir: 2026-04-15\n",
            encoding="utf-8",
        )

        with self._patch_sources():
            with self.assertRaises(InvalidConfigError):
                config_loader.load_config()

    def test_update_config_rejects_read_only_scope(self):
        """Protect the packaged defaults from accidental mutation through the writer helper."""
        with self._patch_sources():
            with self.assertRaises(ValueError):
                config_loader.update_config({"docker": {}}, ConfigScope.READ_ONLY)

    def test_update_config_rejects_workspace_scope_without_workspace_path(self):
        """Fail cleanly when workspace config is requested without ISAAC_ROS_WS set."""
        with patch.object(
            config_loader,
            "_CONFIG_SOURCE_CANDIDATES",
            {
                ConfigScope.READ_ONLY: self.read_only,
                ConfigScope.SYSTEM: self.system,
                ConfigScope.USER: self.user,
                ConfigScope.WORKSPACE: None,
            },
        ):
            with self.assertRaises(ValueError) as ctx:
                config_loader.update_config(
                    {"docker": {"run": {"platform": "aarch64"}}},
                    ConfigScope.WORKSPACE,
                )
        self.assertIn("ISAAC_ROS_WS", str(ctx.exception))

    def test_update_config_merges_existing_yaml(self):
        """Preserve user intent already on disk while applying a narrower overlay update."""
        self.user.write_text(
            yaml.safe_dump({"docker": {"run": {"container_name": "before"}}}, sort_keys=False),
            encoding="utf-8",
        )

        with self._patch_sources():
            target = config_loader.update_config(
                {"docker": {"run": {"platform": "aarch64"}}},
                ConfigScope.USER,
            )

        written = yaml.safe_load(target.read_text(encoding="utf-8"))
        self.assertEqual(target, self.user)
        self.assertEqual(written["docker"]["run"]["container_name"], "before")
        self.assertEqual(written["docker"]["run"]["platform"], "aarch64")

    def test_update_config_preserves_existing_permissions(self):
        """Keep config writes from silently broadening access on system-managed files."""
        self.system.write_text(
            yaml.safe_dump({"docker": {"run": {"container_name": "before"}}}, sort_keys=False),
            encoding="utf-8",
        )
        self.system.chmod(0o640)

        with self._patch_sources():
            config_loader.update_config({"docker": {"run": {"platform": "auto"}}},
                                        ConfigScope.SYSTEM)

        mode = stat.S_IMODE(self.system.stat().st_mode)
        self.assertEqual(mode, 0o640)

    def test_update_config_rejects_unknown_overlay_keys_without_writing(self):
        """Overlay writers should block typos before they persist broken partial config on disk."""
        original = {"docker": {"run": {"container_name": "before"}}}
        self.user.write_text(yaml.safe_dump(original, sort_keys=False), encoding="utf-8")

        with self._patch_sources():
            with self.assertRaises(InvalidConfigError):
                config_loader.update_config(
                    {"docker": {"run": {"platfrom": "aarch64"}}},
                    ConfigScope.USER,
                )

        self.assertEqual(yaml.safe_load(self.user.read_text(encoding="utf-8")), original)

    def test_deep_merge_replaces_scalars_and_merges_nested_mappings(self):
        """Capture the recursive overlay semantics the CLI layer depends on for nested config."""
        merged = config_loader._deep_merge(
            {"docker": {"run": {"container_name": "before", "platform": "auto"}}},
            {"docker": {"run": {"platform": "aarch64"}}},
        )

        self.assertEqual(
            merged,
            {"docker": {"run": {"container_name": "before", "platform": "aarch64"}}},
        )


if __name__ == "__main__":
    unittest.main()
