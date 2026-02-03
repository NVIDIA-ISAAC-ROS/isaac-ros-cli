# Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

import click
import sys

from isaac_ros_cli.config_loader import load_environment_mode
from isaac_ros_cli.platform import detect_platform

# Import mode-specific implementations
from .docker import activate_docker
from .venv import activate_venv, is_venv_activated
from .baremetal import activate_baremetal, is_baremetal_activated


def _docker_only_validator(_ctx, _param, value):
    """Validate that Docker-only arguments are only used in the Docker environment mode."""
    if value and load_environment_mode() != "docker":
        raise click.UsageError("This argument is only valid for the Docker environment mode.")
    return value


@click.command()
@click.option('--verbose', is_flag=True, help='Enable verbose output.')
# Docker only options
@click.option('--build', is_flag=True,
              help='Docker only: Build the requested Docker image remotely if missing.',
              callback=_docker_only_validator)
@click.option('--build-local', is_flag=True,
              help='Docker only: Build the requested Docker image locally if missing.',
              callback=_docker_only_validator)
@click.option('--push', is_flag=True,
              help='Docker only: Push the image to the target registry when complete.',
              callback=_docker_only_validator)
@click.option('--use-cached-build-image', is_flag=True,
              help='Docker only: Use cached Docker image if available.',
              callback=_docker_only_validator)
@click.option('--no-cache', is_flag=True,
              help='Docker only: Do not use Docker layer cache.',
              callback=_docker_only_validator)
def activate(
        build: bool,
        build_local: bool,
        push: bool,
        use_cached_build_image: bool,
        no_cache: bool,
        verbose: bool
):
    """Activate Isaac ROS development environment based on saved configuration."""

    mode = load_environment_mode()

    # Refuse to activate if not initialized
    if mode == "uninitialized":
        click.echo("Error: Environment mode is not set.", err=True)
        click.echo("Please run 'sudo isaac-ros init <environment>' first.", err=True)
        sys.exit(1)

    # Refuse to activate if already activated
    if mode == "docker-activated":
        click.echo("Isaac ROS Docker environment is already activated in this shell.", err=True)
        sys.exit(1)
    elif is_venv_activated():
        click.echo("Isaac ROS virtual environment is already activated in this shell.", err=True)
        sys.exit(1)
    elif is_baremetal_activated():
        click.echo("Isaac ROS baremetal environment is already activated in this shell.", err=True)
        sys.exit(1)

    # Detect platform to forward as ISAAC_ROS_PLATFORM environment variable
    platform = detect_platform()

    match mode:
        case 'docker':
            activate_docker(
                platform=platform,
                build=build,
                build_local=build_local,
                push=push,
                use_cached_build_image=use_cached_build_image,
                no_cache=no_cache,
                verbose=verbose
            )
        case 'venv':
            activate_venv(platform)
        case 'baremetal':
            activate_baremetal(platform)
        case _:
            click.echo(f"Error: Invalid environment configuration: {mode}", err=True)
            sys.exit(1)
