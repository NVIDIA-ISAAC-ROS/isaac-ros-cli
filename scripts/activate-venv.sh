#!/bin/bash
# Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

# Isaac ROS Virtual Environment Activation Script
# This script sources the venv, customizes the environment, and starts an interactive shell

# Load standard bash config
[ -f /etc/bash.bashrc ] && source /etc/bash.bashrc
[ -f ~/.bashrc ] && source ~/.bashrc

# Validate ISAAC_ROS_VENV_PATH and source the virtual environment

# Ensure the environment variable is set
if [ -z "${ISAAC_ROS_VENV_PATH:-}" ]; then
    echo "Error: ISAAC_ROS_VENV_PATH is not set in the environment." 1>&2
    exit 1
fi

# Ensure the venv directory exists
if [ ! -d "${ISAAC_ROS_VENV_PATH}" ]; then
    echo "Error: ISAAC_ROS_VENV_PATH='${ISAAC_ROS_VENV_PATH}' does not exist or is not a directory." 1>&2
    exit 1
fi

ACTIVATE_SCRIPT="${ISAAC_ROS_VENV_PATH}/bin/activate"

# Ensure the activate script exists
if [ ! -f "${ACTIVATE_SCRIPT}" ]; then
    echo "Error: Expected activate script not found at '${ACTIVATE_SCRIPT}'." 1>&2
    echo "The virtual environment may be corrupted. Please reinstall isaac-ros-cli." 1>&2
    exit 1
fi

# Source the venv
source "${ACTIVATE_SCRIPT}"

# Set up exit trap to show goodbye message on any exit (including Ctrl+D)
trap 'echo "Exiting Isaac ROS Environment..."' EXIT

# Override deactivate to exit the shell (venv cleanup happens automatically)
deactivate() {
    exit 0
}

# Display activation message
echo "🤖 Isaac ROS Environment Active"
echo "   Type 'deactivate' or press Ctrl+D to exit and return to your original shell"
echo
