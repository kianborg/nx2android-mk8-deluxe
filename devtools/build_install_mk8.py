#!/usr/bin/env python3
"""Build MK8, install it, and enable the bundled Turnip driver on the phone."""
import argparse
from datetime import datetime
import json
import hashlib
import zipfile
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import urllib.request
import shutil
import stat

REPO = Path(__file__).resolve().parents[1]
PACKAGE = 'org.nx2a.t0100152000022000'
REMOTE = f'/sdcard/Android/data/{PACKAGE}/files/env.txt'
TURNIP = {'DM_VK_DRIVER': 'turnip', 'DM_VK_BC_DECODE': '1'}
SOURCE_URL = 'https://github.com/kianborg/nx2android-mk8-deluxe/archive/refs/heads/main.zip'


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


def native_host_info(apk):
    with zipfile.ZipFile(apk) as archive:
        info = archive.getinfo('lib/arm64-v8a/libdmhost.so')
        if info.file_size > 128*1024*1024:
            raise ValueError('Native host exceeds the inspection limit')
        host = archive.read(info)
    return {'sha256': hashlib.sha256(host).hexdigest(),
            'alias_fix_marker_present': b'inactive colour attachment alias:' in host}


def verify_install(adb, repo=REPO):
    """Read the installed host and current log; change nothing on the phone."""
    serial = adb.pick()
    work = repo/'work'
    work.mkdir(exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='mk8-runtime-check-', dir=work))
    log = adb.run('exec-out', 'cat', REMOTE.replace('/env.txt', '/log.txt'))
    env = adb.run('exec-out', 'cat', REMOTE)
    (out/'log.txt').write_text(log, encoding='utf-8')
    (out/'env.txt').write_text(env, encoding='utf-8')
    paths = [line.removeprefix('package:').strip() for line in
             adb.shell(shlex.join(['pm', 'path', PACKAGE])).splitlines() if line.startswith('package:')]
    if not paths:
        raise ValueError(f'Installed APK path not found. Available log: {out}')
    base = next((path for path in paths if path.endswith('/base.apk')), paths[0])
    with tempfile.TemporaryDirectory(prefix='mk8-apk-check-') as tmp:
        local = Path(tmp)/'base.apk'
        adb.run('pull', base, str(local), timeout=120)
        info = native_host_info(local)
    source = repo/'nxnative/dm/android/gfx_vk_exec.c'
    report = {'package': PACKAGE, 'device': serial, 'installed_host': info,
              'alias_event_in_log': 'inactive colour attachment alias:' in log,
              'local_source_has_alias_helper': 'static void color_alias_map(' in source.read_text() if source.is_file() else None,
              'phone_changes': False}
    (out/'runtime-check.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    archive = out/'mk8-runtime-check.zip'
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as z:
        for name in ('log.txt', 'env.txt', 'runtime-check.json'):
            z.write(out/name, name)
    print(f'Alias-fix code marker in installed APK: {info["alias_fix_marker_present"]}')
    print(f'Alias-removal event in current log: {report["alias_event_in_log"]}')
    print(f'Alias helper in local source: {report["local_source_has_alias_helper"]}')
    print(f'Report: {archive}')
    print('Phone settings and app state were not changed. APK contents are not included in the report.')
    return archive


def has_alias_source(repo):
    source = repo/'nxnative/dm/android/gfx_vk_exec.c'
    return source.is_file() and 'static void color_alias_map(' in source.read_text()


def extract_source(archive_path, destination):
    destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if sum(entry.file_size for entry in entries)>4*1024**3:
            raise ValueError('Source archive exceeds extraction limit')
        root = destination.resolve()
        for entry in entries:
            name = entry.filename
            if stat.S_ISLNK(entry.external_attr>>16):
                raise ValueError('Source archive contains an unsupported symbolic link')
            if '\\' in name or not (root/name).resolve().is_relative_to(root):
                raise ValueError('Source archive contains an unsafe path')
        archive.extractall(root)
        # zipfile drops Unix executable bits; the source contains build tools.
        for entry in entries:
            if not entry.is_dir() and (entry.external_attr>>16)&0o111:
                path=root/entry.filename
                path.chmod(path.stat().st_mode | ((entry.external_attr>>16)&0o111))
    candidates = [path for path in root.iterdir() if path.is_dir() and
                  (path/'devtools/build_install_mk8.py').is_file() and has_alias_source(path)]
    if len(candidates)!=1:
        raise ValueError('Downloaded source does not contain the expected MK8 fix and build helper')
    return candidates[0]


def update_source_and_run(args, repo=REPO):
    work = repo/'work'
    work.mkdir(exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix='mk8-updated-source-', dir=work))
    archive = destination/'source.zip'
    print(f'Downloading updated fork source into {destination} ...', flush=True)
    with urllib.request.urlopen(SOURCE_URL,timeout=120) as response, archive.open('wb') as output:
        shutil.copyfileobj(response,output)
    fresh = extract_source(archive,destination/'extracted')
    print(f'Building from updated source: {fresh}',flush=True)
    command = [sys.executable,str(fresh/'devtools/build_install_mk8.py'),
               '--game-folder',str(args.game_folder.expanduser().resolve()),
               '--keys',str(args.keys.expanduser().resolve()),
               '--driver',str(args.driver.expanduser().resolve()),'--jobs',str(args.jobs)]
    if args.device:
        command += ['--device',args.device]
    # Preserve the Python environment, toolchain configuration and signing key.
    # Re-execution ensures porter imports/build paths refer to the fresh source.
    subprocess.run(command,cwd=fresh,check=True)
    return fresh


def build_and_install(args, adb, repo=REPO):
    folder, keys, driver = (path.expanduser().resolve() for path in (args.game_folder, args.keys, args.driver))
    if not folder.is_dir():
        raise ValueError(f'Game folder not found: {folder}')
    for path in (keys, driver):
        if not path.is_file():
            raise ValueError(f'File not found: {path}')
    if args.jobs < 1:
        raise ValueError('--jobs must be positive')
    if not has_alias_source(repo):
        raise ValueError('This source folder lacks the MK8 alias change. Run this helper with --update-source to build from a fresh fork download.')
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

    host = native_host_info(apk)
    if not host['alias_fix_marker_present']:
        raise ValueError('Built APK lacks the expected alias-change code; installation stopped. Retry with --update-source.')
    print('Built APK verified: alias-change code is present.',flush=True)

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
    (backup/'built-host.json').write_text(json.dumps(host,indent=2)+'\n',encoding='utf-8')
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
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--verify-only', action='store_true', help='inspect the installed runtime and log without building, installing or changing phone settings')
    actions.add_argument('--update-source', action='store_true', help='download the latest fork into a separate folder and build/install from there')
    args = parser.parse_args()
    if args.update_source:
        try:
            update_source_and_run(args)
        except (OSError,ValueError,zipfile.BadZipFile,subprocess.CalledProcessError) as error:
            parser.exit(1,f'Error: {error}\n')
        return
    sys.path.insert(0, str(REPO))
    from porter import config, toolchain
    from porter.adb import Adb, AdbError
    try:
        cfg = config.load()
        adb_path = toolchain.find_adb(cfg)
        if not adb_path:
            raise ValueError('ADB not found. Configure it with: python -m porter config adb /path/to/adb')
        adb = Adb(adb_path, args.device or cfg.get('device'))
        if args.verify_only:
            verify_install(adb)
        else:
            build_and_install(args, adb)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.CalledProcessError, AdbError) as error:
        parser.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
