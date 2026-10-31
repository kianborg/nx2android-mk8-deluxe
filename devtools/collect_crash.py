#!/usr/bin/env python3
"""Collect MK8's current log, settings and Android crash/exit history without changing the app."""
import argparse
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import subprocess
import zipfile

PACKAGE = 'org.nx2a.t0100152000022000'
ROOT = f'/sdcard/Android/data/{PACKAGE}/files'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    out = args.output or Path('work')/datetime.now(timezone.utc).strftime('mk8-crash-%Y%m%d-%H%M%S')
    out.mkdir(parents=True, exist_ok=False)
    adb = [args.adb]+(['-s', args.serial] if args.serial else [])
    commands = {
        'log.txt': ['exec-out', 'cat', ROOT+'/log.txt'],
        'log.prev.txt': ['exec-out', 'cat', ROOT+'/log.prev.txt'],
        'env.txt': ['exec-out', 'cat', ROOT+'/env.txt'],
        'android-crash.txt': ['logcat', '-b', 'crash', '-d', '-t', '2000'],
        'android-exits.txt': ['shell', 'dumpsys', 'activity', 'exit-info', PACKAGE],
    }
    status = {}
    for name, command in commands.items():
        result = subprocess.run(adb+command, capture_output=True, timeout=30)
        (out/name).write_bytes(result.stdout)
        status[name] = {'exit_code': result.returncode, 'stderr': result.stderr.decode(errors='replace')}
    # Our signal handler exits itself, so Mesa's original submission error can
    # be in the normal Android log rather than the native crash buffer.
    exits = (out/'android-exits.txt').read_text(errors='replace')
    for record in exits.split('ApplicationExitInfo #')[1:]:
        if f'process={PACKAGE} ' not in record or 'status=139' not in record:
            continue
        pid = re.search(r'\bpid=(\d+)', record)
        if pid:
            name = 'android-failed-process.txt'
            command = ['logcat', '-b', 'all', '-d', '-t', '4000', '--pid='+pid[1]]
            result = subprocess.run(adb+command, capture_output=True, timeout=30)
            (out/name).write_bytes(result.stdout)
            status[name] = {'exit_code': result.returncode, 'pid': int(pid[1]),
                            'stderr': result.stderr.decode(errors='replace')}
            commands[name] = command
        break
    (out/'collection.json').write_text(json.dumps(status, indent=2)+'\n')
    archive = out/'mk8-crash-diagnostics.zip'
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        for name in [*commands, 'collection.json']:
            z.write(out/name, name)
    print(archive.resolve())
    print('No settings, pipeline caches, saves or app state were changed.')
    if any(row['exit_code'] for row in status.values()):
        print('Some reads failed; collection.json records the errors. Send the ZIP with the available evidence.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, subprocess.SubprocessError) as error:
        raise SystemExit(f'Error: {error}')
