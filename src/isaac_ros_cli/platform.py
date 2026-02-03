# Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

"""Isaac ROS platform detection and identification."""

import os
from enum import Enum


class Platform(Enum):
    """
    Enumeration of supported Isaac ROS platforms.

    Each variant maps to a string identifier used in package.xml conditions and other external
    interfaces.
    """

    AMD64 = "amd64"
    """x86_64 systems with NVIDIA dGPU"""

    ARM64 = "arm64"
    """Jetson devices running JetPack"""

    def __str__(self) -> str:
        """Return the string value for external interfaces."""
        return self.value


def detect_platform() -> Platform:
    """
    Detect the Isaac ROS platform based on system characteristics.

    Returns:
        Platform: The detected platform enum value.

    Raises:
        RuntimeError: If the architecture is not supported.
    """
    machine = os.uname().machine

    if machine == "x86_64":
        return Platform.AMD64
    elif machine == "aarch64":
        return Platform.ARM64
    else:
        raise RuntimeError(f"Unsupported architecture: {machine}")
