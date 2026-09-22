#!/usr/bin/env python3
# Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

"""Inventory likely copies and rosidl Buffer evidence in ROS 2 node source."""

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys


SOURCE_SUFFIXES = {'.c', '.cc', '.cpp', '.cu', '.cuh', '.h', '.hh', '.hpp', '.py'}


@dataclass(frozen=True)
class Rule:
    category: str
    expression: re.Pattern[str]
    explanation: str
    python_only: bool = False


RULES = (
    Rule('host-boundary', re.compile(r'\.cpu\s*\('), 'Torch device-to-host materialization'),
    Rule('host-boundary', re.compile(r'\.numpy\s*\('), 'Torch/array host materialization'),
    Rule('host-boundary', re.compile(r'\.item\s*\('), 'scalar host materialization and sync'),
    Rule('host-boundary', re.compile(r'cv_bridge|imgmsg_to_cv2|cv2_to_imgmsg'),
         'host image conversion boundary'),
    Rule('host-boundary', re.compile(r'cv::(remap|resize|cvtColor)|ImgProc::toRGB'),
         'CPU image preprocessing boundary; verify the concrete implementation'),
    Rule('host-boundary', re.compile(r'cp\.asnumpy|cupy\.asnumpy'),
         'CuPy device-to-host materialization', python_only=True),
    Rule('host-boundary', re.compile(r'pcl::fromROSMsg|pcl::toROSMsg|ros2_numpy\.numpify'),
         'host point-cloud conversion boundary'),
    Rule('host-boundary', re.compile(r'convert_torch2numpy|\.to\s*\(\s*["\']cpu["\']'),
         'framework helper that may materialize on the host', python_only=True),
    Rule('host-view', re.compile(r'np\.frombuffer|np\.ndarray\s*\([^\n]*buffer\s*='),
         'host array view; inspect the backing message memory domain', python_only=True),
    Rule('host-view', re.compile(r'\.data\.assign\s*\('),
         'message payload assignment from host iterators'),
    Rule('device-boundary', re.compile(r'cp\.asarray|\.to\s*\(\s*["\']cuda'),
         'possible host-to-device conversion hidden by a framework helper', python_only=True),
    Rule('copy-or-sync', re.compile(r'clone\s*=\s*True|\.clone\s*\('), 'explicit clone'),
    Rule('copy-or-sync', re.compile(r'to_tensor_msg\s*\('), 'copy into tensor message'),
    Rule('copy-or-sync', re.compile(r'cuda(Device|Stream)Synchronize\s*\('),
         'explicit CUDA synchronization'),
    Rule('copy-or-sync', re.compile(r'cudaMemcpy\w*\s*\(|\bmemcpy\s*\('), 'explicit memory copy'),
    Rule('buffer-evidence', re.compile(r'acceptable_buffer_backends'),
         'subscriber backend selection'),
    Rule('buffer-evidence', re.compile(r'backend_type|get_backend_type'),
         'runtime backend inspection'),
    Rule('buffer-evidence', re.compile(r'clone\s*=\s*False'), 'zero-copy Torch input request'),
    Rule('buffer-evidence', re.compile(r'allocate_tensor_msg|allocate_buffer'),
         'message-owned buffer allocation'),
    Rule('buffer-evidence', re.compile(r'from_(input|output)_(tensor_msg|buffer)'),
         'stream-aware buffer handle/view'),
)


def source_files(paths: list[Path]):
    for path in paths:
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (
                candidate for candidate in sorted(path.rglob('*'))
                if candidate.is_file() and candidate.suffix in SOURCE_SUFFIXES
            )
        else:
            raise FileNotFoundError(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Find likely host copies, synchronization, and buffer contract evidence.')
    parser.add_argument('paths', nargs='+', type=Path, help='Source files or directories to scan')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    findings = 0
    files = []
    missing_paths = []
    for path in args.paths:
        try:
            files.extend(source_files([path]))
        except FileNotFoundError:
            missing_paths.append(path)
            print(f'error: path does not exist: {path}', file=sys.stderr)

    for path in files:
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            for rule in RULES:
                if rule.python_only and path.suffix != '.py':
                    continue
                if rule.expression.search(line):
                    findings += 1
                    print(
                        f'{rule.category}\t{path}:{line_number}\t'
                        f'{rule.explanation}\t{line.strip()}')
    print(
        f'summary\tfiles={len(files)}\tfindings={findings}\t'
        f'missing_paths={len(missing_paths)}')
    return 2 if missing_paths else 0


if __name__ == '__main__':
    raise SystemExit(main())
