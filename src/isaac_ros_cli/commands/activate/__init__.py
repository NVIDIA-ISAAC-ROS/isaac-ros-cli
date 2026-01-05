# Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

import click
import sys

# Import mode-specific implementations
from .docker import activate_docker

from isaac_ros_cli.config_loader import load_config


@click.command()
@click.option('--build', is_flag=True, help='Build the image remotely if missing.')
@click.option('--build-local', is_flag=True, help='Build the image locally if missing.')
@click.option('--push', is_flag=True, help='Push the image to the target registry when complete.')
@click.option('--use-cached-build-image', is_flag=True,
              help='Use cached build image if available.')
@click.option('--no-cache', is_flag=True, help='Do not use docker layer cache.')
@click.option('--build-only', is_flag=True, help='Build the image only without starting a container.')
@click.option('--verbose', is_flag=True, help='Enable verbose output.')
def activate(
        build: bool,
        build_local: bool,
        push: bool,
        use_cached_build_image: bool,
        no_cache: bool,
        build_only: bool,
        verbose: bool
):
    """Activate Isaac ROS development environment based on saved configuration."""

    cfg = load_config()
    try:
        mode = cfg['environment']['mode']
    except KeyError:
        click.echo("Error: Configuration is missing '.environment.mode' key", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: Failed to read configuration: {e}", err=True)
        sys.exit(1)

    match mode:
        case 'uninitialized':
            click.echo(
                "Error: Environment mode is not set.",
                err=True
            )
            click.echo(
                "Please run 'sudo isaac-ros init <environment>' first.",
                err=True
            )
            sys.exit(1)
        case 'docker':
            activate_docker(
                build=build,
                build_local=build_local,
                push=push,
                use_cached_build_image=use_cached_build_image,
                no_cache=no_cache,
                build_only=build_only,
                verbose=verbose
            )
        case _:
            click.echo(f"Error: Invalid environment configuration: {mode}", err=True)
            sys.exit(1)
