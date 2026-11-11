#!/usr/bin/env python3
"""Collect installed MK8 apps' logs/settings without changing the phone."""
import argparse
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

PREFIX = 'org.nx2a.t0100152000022000'


def collect(adb, output):
    def run(*args):
        result = subprocess.run([*adb, *args], capture_output=True, timeout=60)
        return result.returncode, result.stdout, result.stderr.decode(errors='replace').strip()

    code, raw, error = run('shell', 'pm', 'list', 'packages', PREFIX)
    if code:
        raise RuntimeError(error or raw.decode(errors='replace'))
    packages = sorted({line.removeprefix('package:').strip()
                       for line in raw.decode().splitlines()
                       if line.startswith('package:' + PREFIX)})
    # Android package names contain letters/digits, underscores and dots only.
    packages = [p for p in packages if all(c.isascii() and (c.isalnum() or c in '._') for c in p)]
    if not packages:
        raise RuntimeError('No MK8 package with the expected prefix was found. Run adb shell pm list packages and check the installed app identity.')
    report = {'packages': {}, 'device': {}}
    for prop in ('ro.product.model', 'ro.build.version.release', 'ro.build.version.sdk'):
        code, raw, error = run('shell', 'getprop', prop)
        report['device'][prop] = raw.decode(errors='replace').strip() if code == 0 else error
    for package in packages:
        folder = output / package
        folder.mkdir()
        root = f'/sdcard/Android/data/{package}/files'
        entry = {'files': {}, 'root': root}
        code, raw, error = run('shell', 'ls', '-la', root)
        (folder / 'directory.txt').write_bytes(raw + b'\n' + error.encode())
        for filename in ('log.txt', 'log.prev.txt', 'env.txt', 'settings.txt'):
            code, raw, error = run('exec-out', 'cat', root + '/' + filename)
            entry['files'][filename] = {'collected': code == 0, 'error': error if code else ''}
            if code == 0:
                (folder / filename).write_bytes(raw)
        code, raw, error = run('shell', 'pidof', package)
        pids = raw.decode(errors='replace').split() if code == 0 else []
        entry['running_pids'] = pids
        if pids and all(pid.isdecimal() for pid in pids):
            for pid in pids:
                code, raw, error = run('logcat', '-d', '-v', 'threadtime', '--pid=' + pid)
                if code == 0:
                    (folder / f'logcat-{pid}.txt').write_bytes(raw)
        if package.startswith(PREFIX + '.prtest'):
            code, raw, error = run('shell', 'pm', 'path', package)
            paths = [line.removeprefix('package:').strip()
                     for line in raw.decode(errors='replace').splitlines()
                     if line.startswith('package:')]
            base = next((path for path in paths if path.endswith('/base.apk')), None)
            host = {}
            if code == 0 and base:
                with tempfile.TemporaryDirectory() as temporary:
                    apk = Path(temporary) / 'base.apk'
                    code, raw, error = run('pull', base, str(apk))
                    if code == 0:
                        try:
                            with zipfile.ZipFile(apk) as z:
                                info = z.getinfo('lib/arm64-v8a/libdmhost.so')
                                if info.file_size > 128 * 1024**2:
                                    raise ValueError('Native host too large')
                                data = z.read(info)
                            host = {
                                'sha256': hashlib.sha256(data).hexdigest(),
                                'bytes': len(data),
                                'has_current_readback_switch': b'DM_VK_X_BC_GPU_READBACK' in data,
                                'has_old_readback_switch': b'DM_VK_BC_GPU_READBACK' in data,
                                'has_snapshot_completion_marker': b'BC GPU snapshot: ordered readback completed' in data,
                                'has_ordered_upload_marker': b'BC buffer readback allocation failed' in data,
                            }
                        except (OSError, KeyError, ValueError, zipfile.BadZipFile) as problem:
                            host['error'] = str(problem)
                    else:
                        host['error'] = error or raw.decode(errors='replace')
            else:
                host['error'] = error or 'Installed base APK path not found'
            entry['installed_host'] = host
            (folder / 'installed-host.json').write_text(json.dumps(host, indent=2) + '\n')
        report['packages'][package] = entry
        found = ', '.join(name for name, status in entry['files'].items() if status['collected'])
        print(f'{package}: {found or "no external log/settings files found"}')
    (output / 'collection.json').write_text(json.dumps(report, indent=2) + '\n')
    (output / 'README.txt').write_text(
        'Read-only collection of installed MK8 package logs and settings.\n'
        'log.prev.txt is the previous app startup, not necessarily the opposite test mode.\n'
        'env.txt is the current settings file; it does not prove which settings a previous run used.\n'
        'A running app PID does not prove that app was in the foreground.\n'
        'installed-host.json checks switch/diagnostic strings in the installed PR APK; strings do not prove a path executed.\n'
        'Only host metadata is retained; the inspected APK is not included.\n'
        'No settings were changed, no apps stopped or installed, and logcat was not cleared.\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb', help='ADB executable path')
    parser.add_argument('--device', help='ADB device serial, if more than one device is connected')
    args = parser.parse_args()
    adb = [args.adb] + (['-s', args.device] if args.device else [])
    try:
        folder = Path(tempfile.mkdtemp(prefix='mk8-bc-logs-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-', dir=Path.cwd()))
        collect(adb, folder)
        archive = shutil.make_archive(str(folder), 'zip', root_dir=folder)
        print(f'Upload this ZIP: {archive}')
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
