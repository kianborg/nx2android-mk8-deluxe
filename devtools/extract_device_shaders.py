#!/usr/bin/env python3
"""Read only a trace's shaders from the installed APK's DMSV bundle over ADB."""
import argparse
from pathlib import Path
import re
import shlex
import struct
import subprocess
import tempfile

from extract_graphics_shaders import ENTRY, extract


def selected_entries(header, table, size, keys):
    magic, version, count = struct.unpack('<4sII', header)
    if magic != b'DMSV' or version != 1 or count > 100000 or len(table) != count*ENTRY.size:
        raise ValueError('Invalid or oversized DMSV table.')
    entries = []
    total = 0
    seen = set()
    for i in range(count):
        key, stage, off, length, roff, rlength, _ = ENTRY.unpack_from(table, i*ENTRY.size)
        if key not in keys:
            continue
        if key in seen or stage > 5 or length < 20 or length % 4:
            raise ValueError('Invalid selected shader entry.')
        seen.add(key)
        for start, n in ((off, length), (roff, rlength)):
            if start < 12+len(table) or start+n > size:
                raise ValueError('Selected shader range is outside the bundle.')
            total += n
            entries.append((start, n))
    if not entries or total > 256*1024*1024:
        raise ValueError('No matching shaders, or selected shaders exceed 256 MiB.')
    return entries


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--trace', type=Path, required=True)
    ap.add_argument('--output', type=Path, default=Path('mk8-shadow-shaders.zip'))
    ap.add_argument('--adb', default='adb')
    ap.add_argument('--serial')
    args = ap.parse_args()
    if args.output.exists():
        ap.error('Output exists; choose a fresh --output filename.')
    log = args.trace.read_text(encoding='utf-8', errors='replace')
    keys = {int(k, 16) for row in re.findall(r'\bshaders ([0-9a-fA-F]{16}) ([0-9a-fA-F]{16}) ([0-9a-fA-F]{16})\b', log)
            for k in row if int(k, 16)}
    if not keys:
        ap.error('No shader keys in trace.')
    adb = [args.adb] + (['-s', args.serial] if args.serial else [])
    remote = '/sdcard/Android/data/org.nx2a.t0100152000022000/files/shaders.dmsv'

    def run(parts):
        return subprocess.run(adb+['exec-out', shlex.join(parts)], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    size = int(run(['stat', '-c', '%s', remote]).strip())
    if size < 12 or size > 4*1024**3:
        raise ValueError('Invalid bundle size.')

    def read(start, n):
        if not n:
            return b''
        block = 4096
        first = start//block
        count = (start+n+block-1)//block-first
        data = run(['dd', 'if='+remote, 'bs=4096', f'skip={first}', f'count={count}'])
        data = data[start % block:start % block+n]
        if len(data) != n:
            raise ValueError('Short ADB read from shader bundle.')
        return data

    header = read(0, 12)
    magic, version, count = struct.unpack('<4sII', header)
    if magic != b'DMSV' or version != 1 or count > 100000 or 12+count*ENTRY.size > size:
        raise ValueError('Invalid DMSV header.')
    table = read(12, count*ENTRY.size)
    entries = selected_entries(header, table, size, keys)
    print(f'Reading {len(keys)} traced shader keys; {sum(n for _, n in entries):,} selected bytes, not the entire bundle.', flush=True)
    # A sparse temporary file lets the existing validated extractor keep its
    # original offsets. Only the table and selected ranges occupy disk blocks.
    with tempfile.TemporaryDirectory() as folder:
        local = Path(folder)/'shaders.dmsv'
        with local.open('wb') as f:
            f.truncate(size)
            f.write(header+table)
            for i, (start, n) in enumerate(entries):
                f.seek(start)
                f.write(read(start, n))
                if i % 20 == 0:
                    print(f'Read {i+1}/{len(entries)} ranges', flush=True)
        extract(local, args.trace, args.output)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        raise SystemExit(f'Error: {e}')
