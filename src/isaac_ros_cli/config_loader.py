# Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

from enum import Enum, auto
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping

import yaml

ENVIRONMENT_MODE_CONFIG_PATH = Path("/etc/isaac-ros-cli/environment.conf")


class ConfigScope(Enum):
    # In order of precedence
    READ_ONLY = auto()
    SYSTEM = auto()
    USER = auto()
    WORKSPACE = auto()


_CONFIG_SOURCE_CANDIDATES: Dict[ConfigScope, Path] = {
    # Read-only default config, shipped with the package
    ConfigScope.READ_ONLY: Path("/usr/share/isaac-ros-cli/config.yaml"),

    # System-level overrides, written to by the CLI
    ConfigScope.SYSTEM: Path("/etc/isaac-ros-cli/config.yaml"),

    # User-level overrides, written to by the user and mentioned in the documentation
    ConfigScope.USER: Path.home() / ".config" / "isaac-ros-cli" / "config.yaml",

    # Workspace-level overrides, for power users
    ConfigScope.WORKSPACE: (
        Path(os.getenv("ISAAC_ROS_WS", "")) / ".isaac-ros-cli" / "config.yaml"
    ) if os.getenv("ISAAC_ROS_WS") else None,
}


def load_environment_mode() -> str:
    """Load the environment mode from the environment mode configuration file."""
    if not ENVIRONMENT_MODE_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Environment mode configuration file not found at {ENVIRONMENT_MODE_CONFIG_PATH}.")
    with open(ENVIRONMENT_MODE_CONFIG_PATH, "r") as f:
        for line in f:
            key, _, value = line.strip().partition("=")
            if key == "ISAAC_ROS_ENVIRONMENT":
                return value
    raise KeyError("ISAAC_ROS_ENVIRONMENT not found in environment mode configuration file.")


def update_environment_mode(mode: str) -> None:
    """Update the environment mode in the environment mode configuration file."""
    if not ENVIRONMENT_MODE_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Environment mode configuration file not found at {ENVIRONMENT_MODE_CONFIG_PATH}.")
    with open(ENVIRONMENT_MODE_CONFIG_PATH, "w") as f:
        f.write(f"ISAAC_ROS_ENVIRONMENT={mode}\n")


def load_config() -> Dict[str, Any]:
    """Load the merged Isaac ROS CLI configuration."""
    sources: List[Path] = []
    for path in _CONFIG_SOURCE_CANDIDATES.values():
        # Skip unavailable paths
        if path is None:
            continue

        if path.exists():
            sources.append(path)

    if not sources:
        raise FileNotFoundError(
            "No Isaac ROS CLI configuration files found. Tried: "
            + ", ".join(str(path) for path in _CONFIG_SOURCE_CANDIDATES.values())
        )

    merged: Dict[str, Any] = {}
    for path in sources:

        with path.open("r", encoding="utf-8") as f:
            overlay = yaml.safe_load(f)

        if not isinstance(overlay, Mapping):
            raise ValueError(
                f"Configuration file {path} must contain a valid YAML mapping at the top level."
            )

        merged = _deep_merge(merged, overlay)

    return merged


def update_config(overlay: Dict[str, Any], scope: ConfigScope) -> Path:
    """Update requested scope configuration with the given overlay.

    Parameters
    ----------
    overlay
        Mapping to update the configuration with.
    scope
        Scope to write the configuration to.

    Returns
    -------
    target
        Path to the updated configuration file.
    """

    if scope == ConfigScope.READ_ONLY:
        raise ValueError("Cannot write to read-only config.")

    target = _CONFIG_SOURCE_CANDIDATES[scope]
    target.parent.mkdir(parents=True, exist_ok=True)

    # Load the existing configuration if it exists
    config = {}
    original_permissions = None
    if target.exists():
        original_permissions = target.stat().st_mode
        with target.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

    # Merge the overlay with the existing configuration
    config = _deep_merge(config, overlay)

    # Write the updated configuration to the target
    with target.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False)

    if original_permissions is not None:
        target.chmod(original_permissions)

    return target


def _deep_merge(base: Dict[str, Any], overlay: Mapping[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries."""
    result: Dict[str, Any] = dict(base)

    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value

    return result
