#!/usr/bin/env python3
# Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

"""Validate Isaac ROS CLI apt preference activation and resolver behavior."""

from __future__ import annotations

import argparse
import filecmp
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlparse


ISAAC_DEBIAN_REPOSITORY = "http://isaac-debian-repo.nvidia.com:8080"
ISAAC_DEBIAN_COMPONENTS = "main external-main"
ISAAC_DEBIAN_ORIGIN = "isaac-debian-repo.nvidia.com"
JETSON_ORIGIN = "repo.download.nvidia.com"
JETSON_RELEASE = "r39.2"
CUDA_TOOLKIT_13_0 = "cuda-toolkit-13-0"
CUDA_TOOLKIT_13_2 = "cuda-toolkit-13-2"
CUDA_TOOLKIT_13_3 = "cuda-toolkit-13-3"
CUDA_13_2_TOOLKIT_RELEASE_PACKAGES = (
    "cuda-command-line-tools-13-2",
    "cuda-compiler-13-2",
    "cuda-libraries-13-2",
    "cuda-libraries-dev-13-2",
    "cuda-nsight-compute-13-2",
    "cuda-nsight-systems-13-2",
    "cuda-tools-13-2",
    "cuda-visual-tools-13-2",
)
CUDA_13_2_CONFIG_PACKAGES = (
    "cuda-toolkit-13-config-common",
    "cuda-toolkit-config-common",
)
CUDA_13_0_TOOLKIT_RELEASE_PACKAGES = (
    "cuda-command-line-tools-13-0",
    "cuda-compiler-13-0",
    "cuda-libraries-13-0",
    "cuda-libraries-dev-13-0",
    "cuda-nsight-compute-13-0",
    "cuda-nsight-systems-13-0",
    "cuda-tools-13-0",
    "cuda-visual-tools-13-0",
)
CUDA_13_0_CONFIG_PACKAGES = (
    "cuda-toolkit-13-0-config-common",
    "cuda-toolkit-config-common",
)
CUDA_RELATED_PACKAGE_PREFIXES = ("cuda-", "libcu", "libnv")
CUDA_VERSIONED_PACKAGE_SUFFIX_RE = re.compile(r"-13-[0-9]+$")
TENSORRT_PACKAGES = ("tensorrt", "python3-libnvinfer")
DGX_SPARK_REPO_PACKAGES = ("vpi4-dev", "libnvvpi4", "deepstream-spark")
CUDA_13_0_PREF = "/etc/apt/preferences.d/isaac-ros-cuda-13-0.pref"
CUDA_13_2_PREF = "/etc/apt/preferences.d/20-isaac-ros-cuda-13-2.pref"
DGX_SPARK_PREF = "/etc/apt/preferences.d/20-isaac-ros-dgx-spark.pref"
JETSON_PREF = "/etc/apt/preferences.d/20-isaac-ros-jetson.pref"
LEGACY_DGX_SPARK_PREF = "/etc/apt/preferences.d/isaac-ros-dgx-spark.pref"
PACKAGED_CUDA_13_0_PREF = (
    "/etc/isaac-ros-cli/docker/packaging/isaac-ros-cuda-13-0.pref"
)
PACKAGED_CUDA_13_2_PREF = (
    "/etc/isaac-ros-cli/docker/packaging/20-isaac-ros-cuda-13-2.pref"
)
PACKAGED_DGX_SPARK_PREF = (
    "/etc/isaac-ros-cli/docker/packaging/20-isaac-ros-dgx-spark.pref"
)
PACKAGED_JETSON_PREF = "/etc/isaac-ros-cli/docker/packaging/20-isaac-ros-jetson.pref"

ARCH_REPOS = {
    "amd64": {
        "ubuntu_mirror_env": "UBUNTU_MIRROR_AMD64",
        "ubuntu_mirror": "http://archive.ubuntu.com/ubuntu",
        "security_mirror_env": "UBUNTU_SECURITY_MIRROR_AMD64",
        "security_mirror": "http://security.ubuntu.com/ubuntu",
        "cuda_repo_arch": "x86_64",
    },
    "arm64": {
        "ubuntu_mirror_env": "UBUNTU_MIRROR_ARM64",
        "ubuntu_mirror": "http://ports.ubuntu.com/ubuntu-ports",
        "security_mirror_env": "UBUNTU_SECURITY_MIRROR_ARM64",
        "security_mirror": "http://ports.ubuntu.com/ubuntu-ports",
        "cuda_repo_arch": "sbsa",
    },
}

PLATFORM_CONFIG = {
    "amd64": {
        "target_arch": "amd64",
        "debian_dist": "noble",
        "cuda_prefix": "13.2.",
        "cuda_package_suffix": "13-2",
        "cuda_toolkit_package": CUDA_TOOLKIT_13_2,
        "installed_cuda_version_to_keep": "13.2.86-1",
        "active_prefs": ((PACKAGED_CUDA_13_2_PREF, CUDA_13_2_PREF),),
        "package_version_prefixes": {
            **{
                package: "13.2."
                for package in CUDA_13_2_TOOLKIT_RELEASE_PACKAGES
            },
            **{package: "13.2." for package in CUDA_13_2_CONFIG_PACKAGES},
        },
    },
    "arm64-fastos": {
        "target_arch": "arm64",
        "debian_dist": "noble-fastos",
        "cuda_prefix": "13.0.",
        "cuda_package_suffix": "13-0",
        "cuda_toolkit_package": CUDA_TOOLKIT_13_0,
        "installed_cuda_version_to_keep": "13.0.86-1",
        "active_prefs": (
            (PACKAGED_CUDA_13_0_PREF, CUDA_13_0_PREF),
            (PACKAGED_DGX_SPARK_PREF, DGX_SPARK_PREF),
        ),
        "package_version_prefixes": {
            **{
                package: "13.0."
                for package in CUDA_13_0_TOOLKIT_RELEASE_PACKAGES
            },
            **{package: "13.0." for package in CUDA_13_0_CONFIG_PACKAGES},
        },
        "origin_uri_packages": DGX_SPARK_REPO_PACKAGES,
        "required_origin": ISAAC_DEBIAN_ORIGIN,
    },
    "arm64-jetpack": {
        "target_arch": "arm64",
        "debian_dist": "noble-jetpack",
        "cuda_prefix": "13.2.",
        "cuda_package_suffix": "13-2",
        "cuda_toolkit_package": CUDA_TOOLKIT_13_2,
        "installed_cuda_version_to_keep": "13.2.86-1",
        "active_prefs": (
            (PACKAGED_CUDA_13_2_PREF, CUDA_13_2_PREF),
            (PACKAGED_JETSON_PREF, JETSON_PREF),
        ),
        "jetson_repo_paths": ("common",),
        "package_version_prefixes": {
            **{
                package: "13.2."
                for package in CUDA_13_2_TOOLKIT_RELEASE_PACKAGES
            },
            **{package: "13.2." for package in CUDA_13_2_CONFIG_PACKAGES},
            **{package: "10.16." for package in TENSORRT_PACKAGES},
        },
        "origin_uri_packages": TENSORRT_PACKAGES,
        "required_origin": JETSON_ORIGIN,
    },
}

DEB_SEARCH_DIRS = (
    Path("scripts"),
    Path("bazel-bin/scripts/isaac-ros-cli/isaac_ros_cli_deb"),
)

PREF_CLEANUP_PATTERNS = (
    CUDA_13_0_PREF,
    f"{CUDA_13_0_PREF}.dpkg-*",
    CUDA_13_2_PREF,
    f"{CUDA_13_2_PREF}.dpkg-*",
    DGX_SPARK_PREF,
    f"{DGX_SPARK_PREF}.dpkg-*",
    JETSON_PREF,
    f"{JETSON_PREF}.dpkg-*",
    LEGACY_DGX_SPARK_PREF,
    f"{LEGACY_DGX_SPARK_PREF}.dpkg-*",
)


def log(message: str) -> None:
    print(f"==> {message}", flush=True)


def command_to_string(command: list[str]) -> str:
    return shlex.join(command)


def run_command(
    command: list[str],
    *,
    label: str,
    env: dict[str, str] | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
    capture_output: bool = False,
) -> str:
    if capture_output:
        stdout = subprocess.PIPE
        stderr = subprocess.STDOUT

    result = subprocess.run(
        command,
        env=env,
        stdout=stdout,
        stderr=stderr,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        captured_stdout = result.stdout if isinstance(result.stdout, str) else ""
        captured_stderr = result.stderr if isinstance(result.stderr, str) else ""
        if captured_stdout:
            print(captured_stdout, file=sys.stderr, end="")
        if captured_stderr:
            print(captured_stderr, file=sys.stderr, end="")
        raise AssertionError(
            f"{label} failed with exit code {result.returncode}: "
            f"{command_to_string(command)}"
        )
    return result.stdout if isinstance(result.stdout, str) else ""


def remove_matching_paths(pattern: str) -> None:
    path = Path(pattern)
    if "*" in path.name:
        paths = path.parent.glob(path.name)
    else:
        paths = (path,)

    for matched_path in paths:
        if matched_path.exists() or matched_path.is_symlink():
            matched_path.unlink()


def tail_text(path: Path, line_count: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    return "\n".join(lines[-line_count:]) + "\n"


def candidate_for(policy: str) -> str:
    for line in policy.splitlines():
        if line.startswith("  Candidate: "):
            return line.removeprefix("  Candidate: ")
    raise AssertionError("apt policy output did not include a Candidate line")


def version_priorities(policy: str) -> list[tuple[str, int]]:
    priorities = []
    for line in policy.splitlines():
        fields = line.split()
        if fields and fields[0] == "***":
            fields = fields[1:]
        if len(fields) >= 2 and re.match(r"^[0-9][^ ]*$", fields[0]):
            try:
                priority = int(fields[1])
            except ValueError:
                continue
            priorities.append((fields[0], priority))
    return priorities


def priority_for_version(policy: str, version: str) -> int:
    for policy_version, priority in version_priorities(policy):
        if policy_version == version:
            return priority
    raise AssertionError(f"apt policy output did not include version {version}\n{policy}")


def find_isaac_ros_cli_deb() -> Path:
    explicit_deb = os.environ.get("ISAAC_ROS_CLI_DEB")
    if explicit_deb:
        deb_path = Path(explicit_deb)
        if not deb_path.is_file():
            raise AssertionError(f"ISAAC_ROS_CLI_DEB does not exist: {deb_path}")
        return deb_path.resolve()

    candidates: list[Path] = []
    for search_dir in DEB_SEARCH_DIRS:
        if not search_dir.is_dir():
            continue
        candidates.extend(sorted(search_dir.glob("isaac-ros-cli_*.deb")))

    if len(candidates) != 1:
        print("Found deb candidates:", file=sys.stderr)
        if candidates:
            for candidate in candidates:
                print(f"  {candidate}", file=sys.stderr)
        else:
            print("  <none>", file=sys.stderr)
        raise AssertionError(
            "expected exactly one isaac-ros-cli deb; "
            "set ISAAC_ROS_CLI_DEB to choose explicitly"
        )

    return candidates[0].resolve()


class AptResolverHarness:
    def __init__(self, platform: str) -> None:
        self.platform = platform
        self.target_arch = PLATFORM_CONFIG[platform]["target_arch"]
        self.apt_root_context: tempfile.TemporaryDirectory[str] | None = None
        self.apt_root: Path | None = None
        self.apt_options: list[str] = []

    def cleanup(self) -> None:
        if self.apt_root_context is not None:
            self.apt_root_context.cleanup()
            self.apt_root_context = None
            self.apt_root = None

    def apt_get_command(self, *args: str) -> list[str]:
        return ["apt-get", *self.apt_options, *args]

    def apt_cache_command(self, *args: str) -> list[str]:
        return ["apt-cache", *self.apt_options, *args]

    def apt_policy(self, package: str) -> str:
        return run_command(
            self.apt_cache_command("policy", package),
            label=f"apt-cache policy {package}",
            capture_output=True,
        )

    def apt_sim_install(self, package: str) -> str:
        return run_command(
            self.apt_get_command("-s", "--no-install-recommends", "install", package),
            label=f"apt-get simulated install {package}",
            capture_output=True,
        )

    def apt_print_uris(self, package: str) -> str:
        return run_command(
            self.apt_get_command(
                "--print-uris",
                "--download-only",
                "--no-install-recommends",
                "install",
                package,
            ),
            label=f"apt-get print URIs {package}",
            capture_output=True,
        )

    def installed_package_status(
        self,
        installed_packages: tuple[tuple[str, str], ...],
    ) -> str:
        stanzas = []
        for package, version in installed_packages:
            stanzas.append(
                "\n".join(
                    [
                        f"Package: {package}",
                        "Status: install ok installed",
                        "Priority: optional",
                        "Section: misc",
                        "Installed-Size: 1",
                        "Maintainer: NVIDIA <no-reply@nvidia.com>",
                        f"Architecture: {self.target_arch}",
                        f"Version: {version}",
                        "Description: installed package for apt resolver tests",
                    ]
                )
            )
        return "\n\n".join(stanzas) + ("\n" if stanzas else "")

    def configure_apt_resolver(
        self,
        installed_packages: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.cleanup()
        self.apt_root_context = tempfile.TemporaryDirectory(prefix="isaac-ros-cli-apt-")
        self.apt_root = Path(self.apt_root_context.name)

        (self.apt_root / "etc/apt/sources.list.d").mkdir(parents=True)
        (self.apt_root / "state/lists/partial").mkdir(parents=True)
        (self.apt_root / "cache/archives/partial").mkdir(parents=True)
        (self.apt_root / "status").write_text(
            self.installed_package_status(installed_packages),
            encoding="utf-8",
        )

        isaac_debian_repository = os.environ.get(
            "ISAAC_DEBIAN_REPOSITORY",
            ISAAC_DEBIAN_REPOSITORY,
        )
        isaac_debian_components = os.environ.get(
            "ISAAC_DEBIAN_COMPONENTS",
            ISAAC_DEBIAN_COMPONENTS,
        )
        jetson_release = os.environ.get("JETSON_RELEASE", JETSON_RELEASE)

        arch_config = ARCH_REPOS.get(self.target_arch)
        platform_config = PLATFORM_CONFIG.get(self.platform)
        if arch_config is None:
            raise AssertionError(f"unsupported target architecture: {self.target_arch}")
        if platform_config is None:
            raise AssertionError(f"unsupported platform: {self.platform}")

        ubuntu_mirror = os.environ.get(
            arch_config["ubuntu_mirror_env"],
            arch_config["ubuntu_mirror"],
        )
        ubuntu_security_mirror = os.environ.get(
            arch_config["security_mirror_env"],
            arch_config["security_mirror"],
        )
        debian_dist = platform_config["debian_dist"]
        cuda_repo_arch = arch_config["cuda_repo_arch"]

        sources = [
            (
                f"deb [arch={self.target_arch} trusted=yes] "
                f"{ubuntu_mirror} noble main restricted universe multiverse"
            ),
            (
                f"deb [arch={self.target_arch} trusted=yes] "
                f"{ubuntu_mirror} noble-updates main restricted universe multiverse"
            ),
            (
                f"deb [arch={self.target_arch} trusted=yes] "
                f"{ubuntu_security_mirror} noble-security main restricted universe multiverse"
            ),
            (
                f"deb [arch={self.target_arch} trusted=yes] "
                f"https://developer.download.nvidia.com/compute/cuda/repos/"
                f"ubuntu2404/{cuda_repo_arch} /"
            ),
            (
                f"deb [arch={self.target_arch} trusted=yes] "
                f"{isaac_debian_repository} {debian_dist} {isaac_debian_components}"
            ),
        ]
        for jetson_repo_path in platform_config.get("jetson_repo_paths", ()):
            sources.append(
                (
                    f"deb [arch={self.target_arch} trusted=yes] "
                    f"http://{JETSON_ORIGIN}/jetson/{jetson_repo_path} "
                    f"{jetson_release} main"
                )
            )

        sources_list = self.apt_root / "etc/apt/sources.list"
        sources_list.write_text("\n".join(sources) + "\n", encoding="utf-8")

        self.apt_options = [
            "-o",
            f"APT::Architecture={self.target_arch}",
            "-o",
            f"Dir::Etc::sourcelist={sources_list}",
            "-o",
            f"Dir::Etc::sourceparts={self.apt_root}/etc/apt/sources.list.d",
            "-o",
            "Dir::Etc::preferencesparts=/etc/apt/preferences.d",
            "-o",
            f"Dir::State::status={self.apt_root}/status",
            "-o",
            f"Dir::State::lists={self.apt_root}/state/lists",
            "-o",
            f"Dir::Cache::archives={self.apt_root}/cache/archives",
            "-o",
            f"Dir::Cache::pkgcache={self.apt_root}/cache/pkgcache.bin",
            "-o",
            f"Dir::Cache::srcpkgcache={self.apt_root}/cache/srcpkgcache.bin",
            "-o",
            "Acquire::AllowInsecureRepositories=true",
            "-o",
            "Acquire::AllowDowngradeToInsecureRepositories=true",
            "-o",
            "Debug::NoLocking=1",
        ]

        log(f"apt resolver sources for {self.platform}/{self.target_arch}:")
        for source in sources:
            print(f"  {source}")

        update_log = self.apt_root / "update.log"
        with update_log.open("w", encoding="utf-8") as update_output:
            result = subprocess.run(
                self.apt_get_command("update"),
                stdout=update_output,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        if result.returncode != 0:
            print(tail_text(update_log, 120), file=sys.stderr, end="")
            raise AssertionError(
                f"apt-get update failed for {self.platform}/{self.target_arch}"
            )


class IsaacRosCliPlatformTest(unittest.TestCase):
    platform = ""
    apt_harness: AptResolverHarness | None = None

    @classmethod
    def setUpClass(cls) -> None:
        if not cls.platform:
            raise RuntimeError("test platform was not configured")
        if os.geteuid() != 0:
            raise RuntimeError("run inside a root CI/container environment")

        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
        install_deb(cls.platform)
        cls.apt_harness = AptResolverHarness(cls.platform)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.apt_harness is not None:
            cls.apt_harness.cleanup()
            cls.apt_harness = None

    @property
    def apt(self) -> AptResolverHarness:
        if self.__class__.apt_harness is None:
            self.fail("apt resolver harness was not initialized")
        return self.__class__.apt_harness

    def assert_candidate_prefix(self, package: str, prefix: str) -> None:
        policy = self.apt.apt_policy(package)
        candidate = candidate_for(policy)
        self.assertTrue(
            candidate.startswith(prefix),
            f"{package} candidate '{candidate}' does not start with '{prefix}'\n{policy}",
        )

    def assert_no_candidate(self, package: str) -> None:
        policy = self.apt.apt_policy(package)
        candidate = candidate_for(policy)
        self.assertEqual(
            candidate,
            "(none)",
            f"{package} unexpectedly has candidate '{candidate}'\n{policy}",
        )

    def assert_package_origin(self, package: str, expected_origin: str) -> None:
        print_uris = self.apt.apt_print_uris(package)
        package_uris = []
        for line in print_uris.splitlines():
            fields = shlex.split(line)
            if len(fields) >= 2 and fields[1].startswith(f"{package}_"):
                package_uris.append(fields[0])

        self.assertTrue(
            package_uris,
            f"apt-get did not print a URI for {package}\n{print_uris}",
        )
        for uri in package_uris:
            self.assertEqual(
                urlparse(uri).hostname,
                expected_origin,
                f"{package} would be downloaded from {uri}",
            )

    def assert_cuda_package_suffixes(
        self,
        install_output: str,
        expected_suffix: str,
    ) -> None:
        unexpected_packages = []
        for line in install_output.splitlines():
            fields = line.split()
            if len(fields) < 2 or fields[0] != "Inst":
                continue

            package = fields[1]
            if not package.startswith(CUDA_RELATED_PACKAGE_PREFIXES):
                continue

            suffix = CUDA_VERSIONED_PACKAGE_SUFFIX_RE.search(package)
            if suffix is not None and suffix.group(0).lstrip("-") != expected_suffix:
                unexpected_packages.append(package)

        self.assertEqual(
            unexpected_packages,
            [],
            (
                f"CUDA-related transitive packages do not use {expected_suffix}: "
                f"{', '.join(unexpected_packages)}\n{install_output}"
            ),
        )

    def assert_file_absent(self, path: str) -> None:
        self.assertFalse(Path(path).exists(), f"unexpected file exists: {path}")

    def assert_file_matches_source(
        self,
        source: str,
        destination: str,
    ) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        self.assertTrue(source_path.is_file(), f"missing source file: {source}")
        self.assertTrue(
            destination_path.is_file(),
            f"missing destination file: {destination}",
        )
        self.assertTrue(
            filecmp.cmp(source_path, destination_path, shallow=False),
            f"{destination} differs from {source}",
        )

    def test_active_platform_preference_files(self) -> None:
        active_prefs = PLATFORM_CONFIG[self.platform].get("active_prefs", ())
        active_pref_destinations = {active_pref[1] for active_pref in active_prefs}

        for active_pref in active_prefs:
            self.assert_file_matches_source(*active_pref)

        for pref in (
            CUDA_13_0_PREF,
            CUDA_13_2_PREF,
            DGX_SPARK_PREF,
            JETSON_PREF,
        ):
            if pref not in active_pref_destinations:
                self.assert_file_absent(pref)
        self.assert_file_absent(LEGACY_DGX_SPARK_PREF)

    def test_apt_policy_resolves_expected_packages(self) -> None:
        self.apt.configure_apt_resolver()

        platform_config = PLATFORM_CONFIG[self.platform]
        cuda_prefix = platform_config["cuda_prefix"]
        cuda_toolkit_package = platform_config["cuda_toolkit_package"]
        cuda_toolkit_install = self.apt.apt_sim_install(cuda_toolkit_package)
        self.assert_candidate_prefix(cuda_toolkit_package, cuda_prefix)
        self.assert_no_candidate(CUDA_TOOLKIT_13_3)
        self.assertIn(
            f"Inst {cuda_toolkit_package} ({cuda_prefix}",
            cuda_toolkit_install,
        )
        self.assert_cuda_package_suffixes(
            cuda_toolkit_install,
            platform_config["cuda_package_suffix"],
        )

        for package, prefix in platform_config.get(
            "package_version_prefixes", {}
        ).items():
            self.assert_candidate_prefix(package, prefix)
            self.apt.apt_sim_install(package)

        required_origin = platform_config.get("required_origin")
        for package in platform_config.get("origin_uri_packages", ()):
            self.assert_package_origin(package, required_origin)

    def test_installed_cuda_toolkit_package_outprioritizes_repository(self) -> None:
        platform_config = PLATFORM_CONFIG[self.platform]
        cuda_toolkit_package = platform_config["cuda_toolkit_package"]
        installed_version = platform_config["installed_cuda_version_to_keep"]
        cuda_prefix = platform_config["cuda_prefix"]
        self.apt.configure_apt_resolver(
            installed_packages=((cuda_toolkit_package, installed_version),)
        )

        policy = self.apt.apt_policy(cuda_toolkit_package)
        installed_priority = priority_for_version(policy, installed_version)
        repository_priorities = [
            (version, priority)
            for version, priority in version_priorities(policy)
            if version.startswith(cuda_prefix) and version != installed_version
        ]

        self.assertEqual(candidate_for(policy), installed_version, policy)
        self.assertEqual(installed_priority, 999, policy)
        self.assertTrue(repository_priorities, policy)
        self.assertTrue(
            all(priority < installed_priority for _, priority in repository_priorities),
            f"Repository versions should not outrank installed CUDA\n{policy}",
        )

        install_output = self.apt.apt_sim_install(cuda_toolkit_package)
        self.assertNotIn(f"Inst {cuda_toolkit_package}", install_output)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install a built isaac-ros-cli Debian package, verify activated apt "
            "preference files, and validate resolver behavior for a target platform."
        )
    )
    parser.add_argument(
        "platform",
        nargs="?",
        help="Target platform: amd64, arm64-fastos, or arm64-jetpack.",
    )
    return parser.parse_args()


def resolve_platform(argument_platform: str | None) -> str:
    platform = (
        argument_platform
        or os.environ.get("ISAAC_ROS_PLATFORM_UNDER_TEST")
        or os.environ.get("ISAAC_ROS_PLATFORM")
        or ""
    )
    if not platform:
        raise ValueError(
            "usage: isaac_ros_cli_platforms.py <amd64|arm64-fastos|arm64-jetpack>"
        )
    if platform not in PLATFORM_CONFIG:
        raise ValueError(f"unsupported platform: {platform}")
    return platform


def install_deb(platform: str) -> None:
    deb_path = find_isaac_ros_cli_deb()
    log(f"Installing {deb_path} with ISAAC_ROS_PLATFORM={platform}")

    for pattern in PREF_CLEANUP_PATTERNS:
        remove_matching_paths(pattern)

    run_command(
        ["apt-get", "update"],
        label="apt-get update",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    run_command(
        ["apt-get", "install", "-y", "--no-install-recommends", "adduser"],
        label="apt-get install adduser",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    env = os.environ.copy()
    env["ISAAC_ROS_PLATFORM"] = platform
    run_command(
        [
            "apt-get",
            "install",
            "-y",
            "--allow-downgrades",
            "--no-install-recommends",
            str(deb_path),
        ],
        label=f"apt-get install {deb_path}",
        env=env,
    )


def main() -> int:
    args = parse_args()
    try:
        platform = resolve_platform(args.platform)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    IsaacRosCliPlatformTest.platform = platform

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(IsaacRosCliPlatformTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
