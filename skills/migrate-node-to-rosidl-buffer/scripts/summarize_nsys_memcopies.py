#!/usr/bin/env python3
# Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto. Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

"""Summarize CUDA memcpy direction, byte size, and count for Buffer validation."""

import argparse
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile


COPY_KINDS = {
    0: 'unknown',
    1: 'H2D',
    2: 'D2H',
    3: 'H2A',
    4: 'A2H',
    5: 'A2A',
    6: 'A2D',
    7: 'D2A',
    8: 'D2D',
    9: 'H2H',
    10: 'P2P',
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path, help='Nsight .nsys-rep or exported .sqlite file')
    return parser.parse_args()


def export_sqlite(trace: Path, destination: Path) -> None:
    nsys = shutil.which('nsys')
    if nsys is None:
        raise RuntimeError('nsys is required to export an .nsys-rep file')
    result = subprocess.run(
        [
            nsys, 'export', '--type=sqlite', '--force-overwrite=true',
            f'--output={destination}', str(trace),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or 'unknown export error'
        raise RuntimeError(f'nsys export failed: {detail}')


def summarize(database: Path, label: str) -> None:
    with sqlite3.connect(database) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='CUPTI_ACTIVITY_KIND_MEMCPY'"
        ).fetchone()
        if table is None:
            raise RuntimeError('trace has no CUPTI_ACTIVITY_KIND_MEMCPY table')
        rows = connection.execute(
            'SELECT copyKind, bytes, COUNT(*), SUM(bytes) '
            'FROM CUPTI_ACTIVITY_KIND_MEMCPY '
            'GROUP BY copyKind, bytes ORDER BY copyKind, bytes'
        ).fetchall()

    print('trace\tdirection\tbytes\tcount\ttotal_bytes')
    for copy_kind, byte_count, count, total_bytes in rows:
        direction = COPY_KINDS.get(copy_kind, f'kind-{copy_kind}')
        print(f'{label}\t{direction}\t{byte_count}\t{count}\t{total_bytes}')


def main() -> int:
    trace = parse_args().trace.resolve()
    if not trace.is_file():
        print(f'error: trace does not exist: {trace}', file=sys.stderr)
        return 2
    try:
        if trace.suffix == '.sqlite':
            summarize(trace, trace.stem)
        elif trace.name.endswith('.nsys-rep'):
            with tempfile.TemporaryDirectory(prefix='nsys-memcpy-') as directory:
                database = Path(directory) / 'trace.sqlite'
                export_sqlite(trace, database)
                summarize(database, trace.name.removesuffix('.nsys-rep'))
        else:
            print('error: expected an .nsys-rep or .sqlite file', file=sys.stderr)
            return 2
    except (RuntimeError, sqlite3.DatabaseError, subprocess.CalledProcessError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
