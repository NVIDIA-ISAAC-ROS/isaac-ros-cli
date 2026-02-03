# Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

import click
import subprocess
import sys
import os
from pathlib import Path

from isaac_ros_cli.platform import Platform

VENV_PATH = Path("/var/lib/isaac-ros-cli/isaac-ros")


def is_venv_activated():
    """Check if the specific isaac-ros venv is already activated."""
    current_venv = os.environ.get('VIRTUAL_ENV')
    try:
        return current_venv and Path(current_venv).resolve() == VENV_PATH.resolve()
    except Exception:
        return False


def activate_venv(platform: Platform):
    """Activate Python virtual environment for Isaac ROS."""

    if not VENV_PATH.exists():
        click.echo("Error: Isaac ROS virtual environment not found", err=True)
        click.echo("This venv should be created during package installation.", err=True)
        click.echo("Please reinstall the isaac-ros-cli package.", err=True)
        sys.exit(1)

    click.echo(f"Found Isaac ROS virtual environment at '{VENV_PATH}'")

    activate_script = VENV_PATH / "bin" / "activate"

    if not activate_script.exists():
        click.echo(
            f"Error: Virtual environment at '{VENV_PATH}' appears to be corrupted", err=True)
        click.echo("Please reinstall the isaac-ros-cli package.", err=True)
        sys.exit(1)

    # Start a new bash shell with the virtual environment activated
    click.echo("Activating Isaac ROS virtual environment...")

    # Use the installed activation script
    activation_script = "/usr/lib/isaac-ros-cli/activate-venv.sh"

    if not Path(activation_script).exists():
        click.echo("Error: Activation script not found", err=True)
        click.echo("Please reinstall the isaac-ros-cli package.", err=True)
        sys.exit(1)

    # Set environment variables for the script to use
    env = os.environ.copy()
    env['ISAAC_ROS_VENV_PATH'] = str(VENV_PATH)
    env['ISAAC_ROS_PLATFORM'] = str(platform)
    env['PYTHONEXECUTABLE'] = str(VENV_PATH / "bin/python3")

    # Run the activation script
    subprocess.call(['bash', '--rcfile', activation_script], env=env)
