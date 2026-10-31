#!/usr/bin/env python3
"""Back up MK8 settings and test synchronous pipeline compilation; restore without losing newer edits."""
import argparse
from pathlib import Path
import subprocess

PACKAGE = 'org.nx2a.t0100152000022000'
REMOTE = f'/sdcard/Android/data/{PACKAGE}/files/env.txt'


def sync_settings(original):
    rows = original.decode('utf-8').splitlines()
    settings = dict(row.strip().split('=', 1) for row in rows if '=' in row and not row.lstrip().startswith('#'))
    if settings.get('DM_VK_DRIVER') != 'turnip' or settings.get('DM_VK_BC_DECODE') != '1':
        raise ValueError('Expected the working Turnip and CPU BC settings; nothing changed.')
    if settings.get('DM_VK_X_SKIPVS', '').strip():
        raise ValueError('Restore the shadow-map-off experiment before this comparison; nothing changed.')
    rows = [row for row in rows if row.strip().split('=', 1)[0] not in ('DM_VK_ASYNC_PIPE', 'DM_VK_NOPREWARM')]
    return ('\n'.join(rows)+'\nDM_VK_ASYNC_PIPE=0\nDM_VK_NOPREWARM=1\n').encode()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['start', 'restore'])
    ap.add_argument('--output', type=Path, default=Path('work/mk8-sync-pipeline-test'))
    ap.add_argument('--adb', default='adb')
    ap.add_argument('--serial')
    a = ap.parse_args()
    adb = [a.adb]+(['-s', a.serial] if a.serial else [])
    out = a.output.resolve()

    def run(*parts):
        return subprocess.run(adb+list(parts), check=True, capture_output=True).stdout

    if a.action == 'start':
        out.mkdir(parents=True, exist_ok=False)
        run('pull', REMOTE, str(out/'env-before.txt'))
        updated = sync_settings((out/'env-before.txt').read_bytes())
        (out/'env-test.txt').write_bytes(updated)
        run('shell', 'am', 'force-stop', PACKAGE)
        run('push', str(out/'env-test.txt'), REMOTE)
        print('Synchronous test enabled. Open the game and enter Time Trials normally.')
        print('Compilation stalls may increase. Caches and saves were not removed.')
    else:
        current = run('exec-out', 'cat', REMOTE)
        if current.replace(b'\r\n', b'\n') != (out/'env-test.txt').read_bytes().replace(b'\r\n', b'\n'):
            raise ValueError('env.txt changed since start; refusing to overwrite newer settings. Backup is env-before.txt.')
        run('shell', 'am', 'force-stop', PACKAGE)
        run('push', str(out/'env-before.txt'), REMOTE)
        print('Original settings restored. You can reopen the game.')
    print(f'Backup: {out / "env-before.txt"}')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Error: {error}')
