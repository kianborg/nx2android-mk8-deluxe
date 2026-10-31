#!/usr/bin/env python3
"""Extract only a trace's translated shaders from DMSV into a diagnostic ZIP."""
import argparse
import json
import mmap
from pathlib import Path
import re
import struct
import zipfile

ENTRY = struct.Struct('<QIIIIII')


def extract(bundle, trace, output):
    text = trace.read_text(encoding='utf-8', errors='replace')
    keys = {int(key, 16) for row in re.findall(
        r'\bshaders ([0-9a-fA-F]{16}) ([0-9a-fA-F]{16}) ([0-9a-fA-F]{16})\b', text)
        for key in row if int(key, 16)}
    if not keys:
        raise ValueError('No traced draw shader keys found; use a frame-trace log.')
    if output.exists():
        raise ValueError(f'Output already exists: {output}; choose a new filename.')
    with bundle.open('rb') as f:
        if bundle.stat().st_size < 12:
            raise ValueError('Truncated shader bundle.')
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            magic, version, count = struct.unpack_from('<4sII', data)
            if magic != b'DMSV' or version != 1 or count > (len(data)-12)//ENTRY.size:
                raise ValueError('Invalid DMSV v1 header/table.')
            entries = {}
            for i in range(count):
                key, stage, off, size, roff, rsize, _ = ENTRY.unpack_from(data, 12+i*ENTRY.size)
                if key not in keys:
                    continue
                if key in entries:
                    raise ValueError(f'Duplicate shader key {key:016x}.')
                if (stage > 5 or size < 20 or size % 4 or off < 12+count*ENTRY.size
                        or off+size > len(data) or roff < 12+count*ENTRY.size
                        or roff+rsize > len(data) or data[off:off+4] != b'\x03\x02\x23\x07'):
                    raise ValueError(f'Invalid shader entry {key:016x}.')
                entries[key] = (stage, off, size, roff, rsize)
            if not entries:
                raise ValueError('None of the trace shader keys exist in this bundle.')
            manifest = {'bundle_version': version, 'trace': trace.name, 'shaders': [],
                        'missing_keys': [f'{k:016x}' for k in sorted(keys-entries.keys())]}
            try:
                with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as archive:
                    for key, (stage, off, size, roff, rsize) in sorted(entries.items()):
                        name = f'{key:016x}'
                        archive.writestr(name+'.spv', data[off:off+size])
                        archive.writestr(name+'.reflection.bin', data[roff:roff+rsize])
                        manifest['shaders'].append({'key': name, 'stage': stage, 'spv_bytes': size})
                    archive.writestr('manifest.json', json.dumps(manifest, indent=2)+'\n')
            except BaseException:
                output.unlink(missing_ok=True)
                raise
    print(f'Extracted {len(entries)} shaders to {output} ({output.stat().st_size:,} bytes).')
    if manifest['missing_keys']:
        print(f"Warning: {len(manifest['missing_keys'])} trace keys absent; check that the bundle matches the trace.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path, help='shaders.dmsv from the tested port')
    parser.add_argument('--trace', type=Path, required=True, help='log containing traced draw calls')
    parser.add_argument('--output', type=Path, default=Path('mk8-shader-diagnostics.zip'))
    args = parser.parse_args()
    try:
        extract(args.bundle, args.trace, args.output)
    except (OSError, ValueError) as e:
        parser.exit(1, f'Error: {e}\n')


if __name__ == '__main__':
    main()
