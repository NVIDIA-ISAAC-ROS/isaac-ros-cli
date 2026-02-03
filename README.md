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
sudo isaac-ros init <docker|venv|baremetal>

# Activate environment
isaac-ros activate
```

## Rebuilding Debian Package

To build a new local copy:
```bash
make build
```
