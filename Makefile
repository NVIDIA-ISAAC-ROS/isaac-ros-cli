# Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

# Simple packaging utility for isaac-ros-cli

PACKAGE_NAME := isaac-ros-cli

# Convenience variable for the built .deb (lives one dir up when using dpkg-buildpackage)
DEB_GLOB := ../$(PACKAGE_NAME)_*.deb

.PHONY: help all build upload clean distclean release print-deb

help:
	@echo "Targets:"
	@echo "  make build           - Build Debian package (.deb)"
	@echo "  make build-stamped   - Build Debian package (.deb) with timestamped version"
	@echo "  make timestamp       - Append timestamp suffix to debian/changelog"
	@echo "  make clean           - Remove staged packaging artifacts inside debian/"
	@echo "  make distclean       - Clean and remove built files in parent dir"
	@echo "  make print-deb       - Print the path to the built .deb (expects exactly one)"
	@echo ""

all: build

timestamp:
	@set -e; \
	timestamp=$$(date +%Y%m%d%H%M%S); \
	sed -i "1s/)/.$$timestamp)/" debian/changelog; \
	echo "Updated debian version with timestamp suffix .$$timestamp"; \
	head -1 debian/changelog

build:
	@echo "Building Debian package for $(PACKAGE_NAME)..."
	DEB_BUILD_OPTIONS=nocheck dpkg-buildpackage -us -uc -b
	@echo "Build complete. Use 'make print-deb' to locate the .deb file."

build-stamped:
	cp debian/changelog debian/changelog.original
	make timestamp
	make build
	mv debian/changelog.original debian/changelog

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
	rm -rf debian/$(PACKAGE_NAME) debian/*.debhelper debian/*.substvars debian/debhelper-build-stamp debian/files

distclean: clean
	@echo "Removing built artifacts in parent directory (if any)..."
	rm -f ../$(PACKAGE_NAME)_*.deb ../$(PACKAGE_NAME)_*.buildinfo ../$(PACKAGE_NAME)_*.changes
