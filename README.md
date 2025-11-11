# Isaac ROS CLI

A command-line interface for managing Isaac ROS development environments.

## Installation

### Using pipx (Recommended)

```bash 
git clone <repository-url>
cd isaac-ros-cli
make install-pipx

# Enable sudo access (required for sudo command)
make install-system-link
```

### Using pip

```bash
pip3 install --user .
```

### Debian/Ubuntu

```bash
sudo apt-get install isaac-ros-cli
```

## Sudo Access

Some commands (like `init`) require sudo. After pipx/pip installation:

```bash
# Option 1: Create system symlink (recommended, one-time)
make install-system-link

# Option 2: Use full path each time
sudo ~/.local/bin/isaac-ros init docker

# Option 3: Preserve PATH
sudo env "PATH=$PATH" isaac-ros init docker
```

## Usage

```bash
# Show help
isaac-ros --help

# Initialize environment (pick a mode)
sudo isaac-ros init docker

# Activate environment
isaac-ros activate
```

## Rebuilding Debian Package

To build a new local copy:
```bash
make build
```

## Develop and build

### build wheel
```bash
make build-wheel
```

### install in edit mode
```bash
make install-local
```

### 清理构建文件
```bash
make distclean
```
