#!/usr/bin/env python3
"""Back up MK8 settings for a rendering comparison; restore without losing newer edits."""
import argparse
from pathlib import Path
import subprocess

PACKAGE = 'org.nx2a.t0100152000022000'
REMOTE = f'/sdcard/Android/data/{PACKAGE}/files/env.txt'


def comparison_settings(original, test='pipelines'):
    rows = original.decode('utf-8').splitlines()
    settings = dict(row.strip().split('=', 1) for row in rows if '=' in row and not row.lstrip().startswith('#'))
    if settings.get('DM_VK_DRIVER') != 'turnip' or settings.get('DM_VK_BC_DECODE') != '1':
        raise ValueError('Expected the working Turnip and CPU BC settings; nothing changed.')
    if settings.get('DM_VK_X_SKIPVS', '').strip():
        raise ValueError('Restore the shadow-map-off experiment before this comparison; nothing changed.')
    if test == 'wheel-depth':
        changes = {'DM_VK_FDZ': '0'}
    elif test == 'wheel-submit':
        changes = {'DM_VK_CB_DRAWS': '0'}
    elif test == 'pipelines':
        changes = {'DM_VK_ASYNC_PIPE': '0', 'DM_VK_NOPREWARM': '1'}
    else:
        raise ValueError('Unknown comparison.')
    rows = [row for row in rows if row.strip().split('=', 1)[0] not in changes]
    rows += [f'{key}={value}' for key, value in changes.items()]
    return ('\n'.join(rows)+'\n').encode()


def sync_settings(original):
    return comparison_settings(original, 'pipelines')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['start', 'restore'])
    ap.add_argument('--test', choices=['pipelines', 'wheel-depth', 'wheel-submit'], default='pipelines')
    ap.add_argument('--output', type=Path)
    ap.add_argument('--adb', default='adb')
    ap.add_argument('--serial')
    a = ap.parse_args()
    adb = [a.adb]+(['-s', a.serial] if a.serial else [])
    default_output = 'work/mk8-sync-pipeline-test' if a.test == 'pipelines' else f'work/mk8-{a.test}-test'
    out = (a.output or Path(default_output)).resolve()

    def run(*parts):
        return subprocess.run(adb+list(parts), check=True, capture_output=True).stdout

    if a.action == 'start':
        out.mkdir(parents=True, exist_ok=False)
        run('pull', REMOTE, str(out/'env-before.txt'))
        updated = comparison_settings((out/'env-before.txt').read_bytes(), a.test)
        (out/'env-test.txt').write_bytes(updated)
        run('shell', 'am', 'force-stop', PACKAGE)
        run('push', str(out/'env-test.txt'), REMOTE)
        if a.test == 'wheel-submit':
            print('Ordinary draw-count command-buffer splits disabled (DM_VK_CB_DRAWS=0).')
            print('Open Time Trials and observe the wheel illumination at the same stationary antigravity location.')
            print('Report whether it is steady, disappears, or still flickers; note any performance change.')
            print('This is a diagnostic comparison, not a confirmed fix. Other required submission boundaries remain.')
        elif a.test == 'wheel-depth':
            print('Fragment-depth workaround disabled for comparison (DM_VK_FDZ=0).')
            print('Open Time Trials and observe the wheel illumination at the same stationary antigravity location.')
            print('Report whether illumination is steady, disappears, or still flickers. This is not a confirmed fix.')
        else:
            print('Synchronous test enabled. Open the game and enter Time Trials normally.')
            print('Compilation stalls may increase.')
        print('Caches and saves were not removed.')
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
