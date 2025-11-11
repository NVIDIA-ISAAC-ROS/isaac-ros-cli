# Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

import click
import sys
import os

from isaac_ros_cli.config_loader import update_config, ConfigScope


@click.command()
@click.argument('environment', type=click.Choice(['docker']))
@click.option('--yes', is_flag=True, help='Do not prompt for confirmation (non-interactive).')
def init(environment, yes):
    """
    Initialize Isaac ROS development environment mode.

    Requires sudo to modify system configuration.
    """
    # Require root privileges
    try:
        is_root = os.geteuid() == 0
    except AttributeError:
        click.echo("Error: os.geteuid() failed -- are you in a UNIX environment?", err=True)
        sys.exit(1)

    if not is_root:
        click.echo("Error: This command requires administrator (sudo) privileges.", err=True)
        click.echo("Please rerun with sudo.", err=True)
        click.echo("", err=True)
        click.echo("If installed with pipx/pip --user, try one of these:", err=True)
        click.echo("  sudo ~/.local/bin/isaac-ros init docker", err=True)
        click.echo("  sudo env \"PATH=$PATH\" isaac-ros init docker", err=True)
        click.echo("", err=True)
        click.echo("Or create a system-level symlink (one-time setup):", err=True)
        click.echo("  sudo ln -s ~/.local/bin/isaac-ros /usr/local/bin/isaac-ros", err=True)
        sys.exit(1)

    try:
        patch = {'environment': {'mode': environment}}

        target = update_config(patch, ConfigScope.SYSTEM)

        click.echo(f"Set environment mode to {environment} in '{target}'.")
    except Exception as e:
        click.echo(f"Error: Failed to write configuration: {e}", err=True)
        sys.exit(1)
