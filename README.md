# Isaac ROS CLI

A command-line interface for managing Isaac ROS development environments.

## Installation

```bash
sudo apt-get install isaac-ros-cli
```

## Usage

```bash
# Show help
isaac-ros --help

# Initialize environment (pick a mode)
sudo isaac-ros init docker

# Activate environment
isaac-ros activate

# Build image only (useful for VS Code dev containers)
isaac-ros activate --build-only
```

## Rebuilding Debian Package

To build a new local copy:
```bash
make build
```
