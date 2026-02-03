# Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

import click
import subprocess
import os

from isaac_ros_cli.platform import Platform

BAREMETAL_ACTIVATED_ENV_VAR = "ISAAC_ROS_BAREMETAL_ACTIVATED"


def is_baremetal_activated():
    """Check if the baremetal environment is already activated."""
    return os.environ.get(BAREMETAL_ACTIVATED_ENV_VAR) == "1"


def activate_baremetal(platform: Platform):
    """Activate baremetal Isaac ROS environment (directly on host system)."""

    click.echo("🤖 Isaac ROS Environment Active")
    click.echo("   Type 'exit' or press Ctrl+D to exit and return to your original shell")
    click.echo()

    # Set environment variables
    env = os.environ.copy()
    env[BAREMETAL_ACTIVATED_ENV_VAR] = "1"
    env['ISAAC_ROS_PLATFORM'] = str(platform)

    # Spawn a new bash shell with the environment variables set
    subprocess.call(['bash'], env=env)

    # Display exit message once the shell exits
    click.echo("Exiting Isaac ROS Environment...")
