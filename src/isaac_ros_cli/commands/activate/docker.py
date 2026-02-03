# Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

import subprocess
import os

from isaac_ros_cli.config_loader import load_config
from isaac_ros_cli.platform import Platform

RUN_DEV_SCRIPT = '/usr/lib/isaac-ros-cli/run_dev.py'


def _build_run_dev_command(
    cfg,
    build: bool,
    build_local: bool,
    push: bool,
    use_cached_build_image: bool,
    no_cache: bool,
    verbose: bool,
    isaac_ros_platform: Platform
):
    cmd = [
        RUN_DEV_SCRIPT,
    ]

    env_keys = cfg['docker']['image']['base_image_keys'] + \
        cfg['docker']['image']['additional_image_keys']

    for key in env_keys:
        cmd.extend(["--env", key])

    container_name = cfg['docker']['run']['container_name']
    cmd.extend(["--container-name", container_name])

    platform = cfg['docker']['run']['platform']
    if platform == 'auto':
        platform = os.uname().machine
    cmd.extend(["--platform", platform])

    # Pass the Isaac ROS platform for setting inside the container (convert to string)
    cmd.extend(["--isaac-ros-platform", str(isaac_ros_platform)])

    if "ISAAC_DIR" in os.environ:
        isaac_dir = os.environ['ISAAC_DIR']
    elif "ISAAC_ROS_WS" in os.environ:
        isaac_dir = os.environ['ISAAC_ROS_WS']
    else:
        raise ValueError("ISAAC_DIR or ISAAC_ROS_WS environment variable is not set")
    cmd.extend(["--isaac-dir", isaac_dir])

    # Forward runtime flags
    if build:
        cmd.append("--build")
    if build_local:
        cmd.append("--build-local")
    if push:
        cmd.append("--push")
    if use_cached_build_image:
        cmd.append("--use-cached-build-image")
    if no_cache:
        cmd.append("--no-cache")
    if verbose:
        cmd.append("--verbose")
    return cmd


def activate_docker(
    platform: Platform,
    build: bool,
    build_local: bool,
    push: bool,
    use_cached_build_image: bool,
    no_cache: bool,
    verbose: bool
):
    """Activate Docker-based Isaac ROS environment by delegating to run_dev.py."""
    cfg = load_config()

    cmd = _build_run_dev_command(
        cfg, build, build_local, push, use_cached_build_image, no_cache, verbose,
        platform)

    # run run_dev.py
    subprocess.run(cmd, check=False)
