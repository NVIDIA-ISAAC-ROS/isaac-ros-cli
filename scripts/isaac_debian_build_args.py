#!/usr/bin/env python3

# Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

"""Print Docker build arguments from the packaged Isaac ROS CLI config."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when the canonical apt configuration is incomplete."""


def _nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value:
        raise ConfigError(f"apt.{name} must be a non-empty single-line string")
    return value


def isaac_debian_build_args(config_path: Path) -> list[str]:
    """Convert one canonical Isaac ROS CLI config into Docker build arguments."""
    with config_path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict) or not isinstance(config.get("apt"), dict):
        raise ConfigError("config must contain an apt mapping")

    apt = config["apt"]
    key_url = _nonempty_string(apt.get("key_url"), "key_url")
    repository = _nonempty_string(apt.get("repository"), "repository")
    distro = _nonempty_string(apt.get("distro"), "distro")
    components = apt.get("components")
    if not isinstance(components, list) or not components:
        raise ConfigError("apt.components must be a non-empty array")
    component_values = [
        _nonempty_string(component, "components[]")
        for component in components
    ]

    build_args = [
        f"ISAAC_DEBIAN_KEY_URL={key_url}",
        f"ISAAC_DEBIAN_REPOSITORY={repository}",
        "ISAAC_DEBIAN_COMPONENTS=" + " ".join(component_values),
    ]
    if distro != "auto":
        build_args.append(f"ISAAC_DEBIAN_DIST={distro}")
    return build_args


def main() -> int:
    """Print one build argument per line for consumption by a shell array."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        build_args = isaac_debian_build_args(args.config)
    except (ConfigError, OSError, UnicodeError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    for build_arg in build_args:
        print(build_arg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
