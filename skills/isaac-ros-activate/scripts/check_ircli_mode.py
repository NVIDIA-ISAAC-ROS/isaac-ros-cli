#!/usr/bin/env python3
# Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

"""Validate the externally visible Isaac ROS CLI environment mode."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


ENVIRONMENT_CONF = Path("/etc/isaac-ros-cli/environment.conf")
VALID_MODES = {
    "uninitialized",
    "docker",
    "docker-activated",
    "venv",
    "baremetal",
}


def _fail(message: str) -> int:
    print(f"[check-ircli-mode] {message}", file=sys.stderr)
    return 1


def _load_mode(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(
            f"expected Isaac ROS CLI environment file at {path}"
        )

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep and key == "ISAAC_ROS_ENVIRONMENT":
            mode = value.strip()
            if mode not in VALID_MODES:
                raise ValueError(
                    f"unsupported ISAAC_ROS_ENVIRONMENT value '{mode}'"
                )
            return mode

    raise KeyError("ISAAC_ROS_ENVIRONMENT not found")


def _load_status_payload() -> dict[str, str]:
    isaac_ros = shutil.which("isaac-ros")
    if isaac_ros is None:
        raise FileNotFoundError("isaac-ros command not found")

    completed = subprocess.run(
        [isaac_ros, "status", "--output", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise ValueError("isaac-ros status returned non-object JSON")
    mode = payload.get("mode")
    activation = payload.get("activation")
    if not isinstance(mode, str) or not isinstance(activation, str):
        raise ValueError("isaac-ros status JSON missing mode/activation strings")
    return {
        "mode": mode,
        "activation": activation,
    }


def _check_via_status(expected: str) -> tuple[bool, str]:
    payload = _load_status_payload()
    actual_mode = payload["mode"]
    activation = payload["activation"]

    if expected == "docker":
        if actual_mode != "docker":
            return False, _explain_mismatch(expected, actual_mode)
        if activation == "active":
            return False, (
                "isaac-ros status reports Docker already active; this check is "
                "meant for the host before running 'isaac-ros activate'"
            )
        if activation == "inactive":
            return True, "OK: mode=docker activation=inactive"
        return False, f"unexpected Docker activation state '{activation}'"

    if actual_mode != "docker":
        return False, _explain_mismatch(expected, actual_mode)
    if activation == "active":
        return True, "OK: mode=docker activation=active"
    if activation == "inactive":
        return False, (
            "isaac-ros status reports Docker configured but not active in this shell yet"
        )
    return False, f"unexpected Docker activation state '{activation}'"


def _explain_mismatch(expected: str, actual: str) -> str:
    if expected == "docker" and actual in {"venv", "baremetal"}:
        return (
            f"mode is '{actual}', not 'docker'; refusing because non-Docker modes "
            "can install packages on the host"
        )
    if expected == "docker" and actual == "docker-activated":
        return (
            "mode is 'docker-activated'; this check is meant for the host before "
            "running 'isaac-ros activate'"
        )
    if expected == "docker-activated" and actual == "docker":
        return (
            "mode is 'docker' on this system, but the current shell is not the "
            "activated Docker environment yet"
        )
    if actual == "uninitialized":
        return (
            "Isaac ROS CLI is uninitialized; run 'sudo isaac-ros init docker' first"
        )
    return f"expected '{expected}' but found '{actual}'"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check the configured or active Isaac ROS CLI mode without invoking "
            "any mutating CLI commands."
        )
    )
    parser.add_argument(
        "--expected",
        choices=("docker", "docker-activated"),
        default="docker",
        help=(
            "Expected mode. Use 'docker' on the host before activation, or "
            "'docker-activated' inside the activated container shell."
        ),
    )
    args = parser.parse_args(argv)

    try:
        ok, message = _check_via_status(args.expected)
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
        ValueError,
    ):
        try:
            actual = _load_mode(ENVIRONMENT_CONF)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            return _fail(str(exc))
        if actual != args.expected:
            return _fail(_explain_mismatch(args.expected, actual))
        print(f"[check-ircli-mode] OK: ISAAC_ROS_ENVIRONMENT={actual}")
        return 0

    if not ok:
        return _fail(message)

    print(f"[check-ircli-mode] {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
