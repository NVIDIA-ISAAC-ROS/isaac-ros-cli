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
from pathlib import Path


class Platform(Enum):
    """
    Enumeration of supported Isaac ROS platforms.

    Each variant maps to a string identifier used in package.xml conditions and other external
    interfaces.
    """

    AMD64 = "amd64"
    """x86_64 systems with NVIDIA dGPU"""

    ARM64_JETPACK = "arm64-jetpack"
    """Jetson devices running JetPack"""

    ARM64_FASTOS = "arm64-fastos"
    """DGX Spark devices running FastOS"""

    def __str__(self) -> str:
        """Return the string value for external interfaces."""
        return self.value


def detect_platform() -> Platform:
    """
    Detect the Isaac ROS platform based on system characteristics.

    Returns:
        Platform: The detected platform enum value.

    Raises:
        RuntimeError: If the architecture is not supported or if the platform is not detected.
    """
    machine = os.uname().machine

    if machine == "x86_64":
        return Platform.AMD64
    elif machine == "aarch64":
        # Distinguish between Jetson (JetPack) and DGX Spark (FastOS)
        if Path("/etc/fastos-release").exists():
            return Platform.ARM64_FASTOS
        elif Path("/etc/nv_tegra_release").exists():
            return Platform.ARM64_JETPACK
        else:
            raise RuntimeError(
                "Unknown ARM64 platform: expected /etc/fastos-release (DGX Spark) "
                "or /etc/nv_tegra_release (Jetson) but neither was found."
            )
    else:
        raise RuntimeError(f"Unsupported architecture: {machine}")
