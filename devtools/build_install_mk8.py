#!/usr/bin/env python3
"""Build MK8, install it, and enable the bundled Turnip driver on the phone."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
PACKAGE = 'org.nx2a.t0100152000022000'
REMOTE = f'/sdcard/Android/data/{PACKAGE}/files/env.txt'
TURNIP = {'DM_VK_DRIVER': 'turnip', 'DM_VK_BC_DECODE': '1'}


def enable_turnip(installed, previous):
    """Keep existing phone choices, add new pack defaults, replace the two switches."""
    def key(row):
        row = row.strip()
        return row.split('=', 1)[0].strip() if '=' in row and not row.startswith('#') else None
    rows = (previous if previous is not None else installed).splitlines()
    present = {key(row) for row in rows}
    for row in installed.splitlines():
        name = key(row)
        if name and name not in present:
            rows.append(row)
            present.add(name)
    rows = [row for row in rows if key(row) not in TURNIP]
    rows += [f'{name}={value}' for name, value in TURNIP.items()]
    return '\n'.join(rows) + '\n'


def build_and_install(args, adb, repo=REPO):
    folder, keys, driver = (path.expanduser().resolve() for path in (args.game_folder, args.keys, args.driver))
    if not folder.is_dir():
        raise ValueError(f'Game folder not found: {folder}')
    for path in (keys, driver):
        if not path.is_file():
            raise ValueError(f'File not found: {path}')
    if args.jobs < 1:
        raise ValueError('--jobs must be positive')
    serial = adb.pick()
    print('Building MK8 from the current source folder...', flush=True)
    subprocess.run([sys.executable, '-m', 'porter', 'port', str(folder), '-k', str(keys),
                    '--experimental', '--jobs', str(args.jobs), '--vulkan-driver', str(driver),
                    '-o', str(folder)], cwd=repo, check=True)
    data, apk = folder/'MarioKart8Deluxe-data', folder/'MarioKart8Deluxe.apk'
    manifest = json.loads((data/'nx2a-data.json').read_text(encoding='utf-8'))
    if manifest.get('package') != PACKAGE:
        raise ValueError('Built data pack has an unexpected package; installation stopped.')
    if not apk.is_file():
        raise ValueError(f'Built APK not found: {apk}')

    # The installer overwrites env.txt. Retain the phone's choices first.
    work = repo/'work'
    work.mkdir(exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='mk8-build-install-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-', dir=work))
    present = adb.shell(f'if [ -f {shlex.quote(REMOTE)} ]; then printf present; else printf absent; fi').strip()
    if present not in ('present', 'absent'):
        raise ValueError('Could not determine whether the phone has env.txt; installation stopped.')
    previous = adb.run('exec-out', 'cat', REMOTE) if present == 'present' else None
    if previous is not None:
        (backup/'env-before.txt').write_text(previous, encoding='utf-8')
    (backup/'pack-env.txt').write_bytes((data/'env.txt').read_bytes())
    print(f'Settings backup: {backup}', flush=True)
    print('Installing APK and data pack...', flush=True)
    subprocess.run([sys.executable, '-m', 'porter', 'install', str(data), '--apk', str(apk),
                    '--device', serial], cwd=repo, check=True)

    adb.shell(shlex.join(['am', 'force-stop', PACKAGE]))
    installed = adb.run('exec-out', 'cat', REMOTE)
    (backup/'env-after-install.txt').write_text(installed, encoding='utf-8')
    settings = enable_turnip(installed, previous)
    local = backup/'env-turnip.txt'
    local.write_text(settings, encoding='utf-8', newline='\n')
    temporary = REMOTE+'.'+backup.name+'.tmp'
    adb.push_file(local, temporary)
    adb.shell(shlex.join(['mv', '-f', temporary, REMOTE]))
    if adb.run('exec-out', 'cat', REMOTE).replace('\r\n', '\n') != settings:
        raise ValueError(f'Phone settings verification failed. Backup: {backup}')
    print('Installed. Turnip and CPU BC decoding are enabled. Open Mario Kart 8 Deluxe normally.')
    return backup


def main():
    home = Path.home()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-folder', type=Path, default=home/'MK8-DLUXE-NSwiTcH')
    parser.add_argument('--keys', type=Path, default=home/'Downloads/ProdKeys.NET-v22.5.0/prod.keys')
    parser.add_argument('--driver', type=Path, default=home/'Downloads/turnip_v24.3.0_R9v2.zip')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--device', help='ADB serial, otherwise use the configured or only connected device')
    args = parser.parse_args()
    sys.path.insert(0, str(REPO))
    from porter import config, toolchain
    from porter.adb import Adb, AdbError
    try:
        cfg = config.load()
        adb_path = toolchain.find_adb(cfg)
        if not adb_path:
            raise ValueError('ADB not found. Configure it with: python -m porter config adb /path/to/adb')
        adb = Adb(adb_path, args.device or cfg.get('device'))
        build_and_install(args, adb)
    except (OSError, ValueError, subprocess.CalledProcessError, AdbError) as error:
        parser.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
