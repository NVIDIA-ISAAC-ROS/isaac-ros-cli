# Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

# Simple packaging utility for isaac-ros-cli

PACKAGE_NAME := isaac-ros-cli

DISTRIBUTION ?= noble
COMPONENT ?= main
ARCHITECTURE ?= all

# Convenience variable for the built .deb (lives one dir up when using dpkg-buildpackage)
DEB_GLOB := ../$(PACKAGE_NAME)_*.deb

.PHONY: help all build upload clean distclean release print-deb build-wheel install-pipx install-local install-system-link uninstall-system-link

help:
	@echo "Targets:"
	@echo "  make build                - Build Debian package (.deb)"
	@echo "  make build-wheel          - Build Python wheel for pip/pipx installation"
	@echo "  make install-local        - Install locally in development mode (pip install -e .)"
	@echo "  make install-pipx         - Install using pipx (recommended for CLI tools)"
	@echo "  make install-system-link  - Create symlink in /usr/local/bin for sudo access"
	@echo "  make uninstall-system-link- Remove symlink from /usr/local/bin"
	@echo "  make clean                - Remove staged packaging artifacts inside debian/"
	@echo "  make distclean            - Clean and remove built files in parent dir"
	@echo "  make print-deb            - Print the path to the built .deb (expects exactly one)"
	@echo ""
	@echo "Variables (override with VAR=value):"
	@echo "  DISTRIBUTION=$(DISTRIBUTION)  COMPONENT=$(COMPONENT)  ARCHITECTURE=$(ARCHITECTURE)"

all: build

build:
	@echo "Building Debian package for $(PACKAGE_NAME)..."
	DEB_BUILD_OPTIONS=nocheck dpkg-buildpackage -us -uc -b
	@echo "Build complete. Use 'make print-deb' to locate the .deb file."

print-deb:
	@set -e; \
	count=$$(ls -1 $(DEB_GLOB) 2>/dev/null | wc -l | tr -d ' '); \
	if [ "$$count" -ne 1 ]; then \
		echo "Error: expected exactly one .deb matching $(DEB_GLOB), found $$count" 1>&2; \
		exit 1; \
	fi; \
	ls -1 $(DEB_GLOB)

clean:
	@echo "Removing staged packaging artifacts under debian/..."
	rm -rf debian/$(PACKAGE_NAME) debian/.debhelper debian/debhelper-build-stamp debian/files

distclean: clean
	@echo "Removing built artifacts in parent directory (if any)..."
	rm -f ../$(PACKAGE_NAME)_*.deb ../$(PACKAGE_NAME)_*.buildinfo ../$(PACKAGE_NAME)_*.changes
	@echo "Removing Python build artifacts..."
	rm -rf build/ dist/ *.egg-info src/*.egg-info

build-wheel:
	@echo "Building Python wheel package..."
	python3 -m pip install --upgrade build
	python3 -m build --wheel
	@echo "Wheel built successfully in dist/"
	@ls -lh dist/*.whl

install-local:
	@echo "Installing in development mode..."
	pip3 install -e .
	@echo "Development installation complete. Changes to source code will be reflected immediately."

install-pipx:
	@echo "Installing with pipx (isolated environment for CLI tools)..."
	@if ! command -v pipx &> /dev/null; then \
		echo "pipx not found. Installing pipx..."; \
		python3 -m pip install --user pipx; \
		python3 -m pipx ensurepath; \
		echo "Please restart your shell or run: source ~/.bashrc"; \
	fi
	pipx install .
	@echo ""
	@echo "Installation complete! You can now run: isaac-ros --help"
	@echo ""
	@echo "Note: Some commands require sudo. To enable sudo access, run:"
	@echo "  make install-system-link"
	@echo ""
	@echo "Or use one of these alternatives:"
	@echo "  sudo ~/.local/bin/isaac-ros init docker"
	@echo "  sudo env \"PATH=\$$PATH\" isaac-ros init docker"

install-system-link:
	@echo "Creating system-level symlink for sudo access..."
	@if [ -f ~/.local/bin/isaac-ros ]; then \
		sudo ln -sf ~/.local/bin/isaac-ros /usr/local/bin/isaac-ros; \
		echo "Symlink created: /usr/local/bin/isaac-ros -> ~/.local/bin/isaac-ros"; \
		echo "Now you can use: sudo isaac-ros init docker"; \
	elif command -v isaac-ros &> /dev/null; then \
		ISAAC_PATH=$$(which isaac-ros); \
		sudo ln -sf $$ISAAC_PATH /usr/local/bin/isaac-ros; \
		echo "Symlink created: /usr/local/bin/isaac-ros -> $$ISAAC_PATH"; \
		echo "Now you can use: sudo isaac-ros init docker"; \
	else \
		echo "Error: isaac-ros not found. Please install it first with 'make install-pipx'."; \
		exit 1; \
	fi

uninstall-system-link:
	@echo "Removing system-level symlink..."
	@sudo rm -f /usr/local/bin/isaac-ros
	@echo "Symlink removed."
