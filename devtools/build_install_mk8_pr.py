#!/usr/bin/env python3
"""Build/install the isolated BC-upload PR, then switch between baseline and CPU BC."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

COMMIT = '7fc39e262279f5f023239a6febc11d36a04457f9'
PACKAGE = 'org.nx2a.t0100152000022000.prtest'
LABEL = 'MK8 PR Test'
REMOTE = f'/sdcard/Android/data/{PACKAGE}/files/env.txt'
DRIVER = 'libmk8_pr_turnip.so'
MARKER = b'BC buffer readback allocation failed'


def dependencies():
    missing = []
    for module, package in [('lz4.block', 'lz4'), ('capstone', 'capstone'),
                            ('PIL', 'pillow'), ('fontTools', 'fonttools'),
                            ('yaml', 'pyyaml'), ('Crypto', 'pycryptodome')]:
        try:
            importlib.import_module(module)
        except ModuleNotFoundError:
            missing.append(package)
    if sys.version_info < (3, 14):
        try:
            importlib.import_module('backports.zstd')
        except ModuleNotFoundError:
            missing.append('backports.zstd')
    if missing:
        raise ValueError('Missing Python dependencies. Run: ' +
                         shlex.join([sys.executable, '-m', 'pip', 'install', *missing]))


def source(work):
    archive = work / 'source.zip'
    url = f'https://github.com/kianborg/nx2android-mk8-deluxe/archive/{COMMIT}.zip'
    print(f'Downloading isolated PR source {COMMIT[:7]}...', flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, archive.open('wb') as out:
        shutil.copyfileobj(response, out)
    root = work / 'source'
    root.mkdir()
    with zipfile.ZipFile(archive) as z:
        if sum(e.file_size for e in z.infolist()) > 4 * 1024**3:
            raise ValueError('Source archive exceeds extraction limit')
        for entry in z.infolist():
            if ('\\' in entry.filename or stat.S_ISLNK(entry.external_attr >> 16) or
                    not (root / entry.filename).resolve().is_relative_to(root.resolve())):
                raise ValueError('Unsafe source archive entry')
        z.extractall(root)
        for entry in z.infolist():
            if not entry.is_dir() and entry.external_attr >> 16 & 0o111:
                p = root / entry.filename
                p.chmod(p.stat().st_mode | (entry.external_attr >> 16 & 0o111))
    roots = [p for p in root.iterdir() if (p / 'porter/cli.py').is_file()]
    if len(roots) != 1:
        raise ValueError('Unexpected PR source layout')
    code = (roots[0] / 'nxnative/dm/android/gfx_vk_exec.c').read_text()
    if 'vk_buffer_snapshot(src, src_off, size, blocks)' not in code:
        raise ValueError('Downloaded source lacks the ordered BC upload')
    return roots[0]


def driver_library(path, work):
    """The upstream CLI bundles one .so, unlike the working fork's ZIP option."""
    if path.suffix.lower() == '.so':
        data = path.read_bytes()
    else:
        with zipfile.ZipFile(path) as z:
            if sum(e.file_size for e in z.infolist()) > 256 * 1024**2:
                raise ValueError('Driver archive exceeds extraction limit')
            libraries = [e for e in z.infolist() if e.filename.endswith('.so')]
            if len(libraries) != 1:
                raise ValueError('This isolated-PR workflow requires a driver ZIP containing one .so (such as R9v2)')
            data = z.read(libraries[0])
    if (len(data) < 64 or len(data) > 128 * 1024**2 or data[:6] != b'\x7fELF\x02\x01' or
            struct.unpack_from('<HH', data, 16) != (3, 183)):
        raise ValueError('Driver must be an ARM64 ELF shared library')
    out = work / DRIVER
    out.write_bytes(data)
    return out


def host_hash(apk):
    with zipfile.ZipFile(apk) as z:
        entry = z.getinfo('lib/arm64-v8a/libdmhost.so')
        if entry.file_size > 128 * 1024**2:
            raise ValueError('Native host is too large')
        data = z.read(entry)
    if MARKER not in data:
        raise ValueError('APK lacks the ordered BC upload code; installation/settings stopped')
    return hashlib.sha256(data).hexdigest()


def settings(installed, previous, cpu, gpu_readback=False):
    forced = {'DM_VK_DRIVER': DRIVER, 'DM_VK_X_BC_CPU': str(int(cpu)),
              'DM_VK_BC_GPU_READBACK': str(int(gpu_readback)), 'DM_VK_BC_DECODE': '0', 'DM_VK_NOPCACHE': '1'}
    def key(row):
        row = row.strip()
        return row.split('=', 1)[0].strip() if '=' in row and not row.startswith('#') else None
    rows = (previous if previous is not None else installed).splitlines()
    present = {key(row) for row in rows}
    for row in installed.splitlines():
        if key(row) and key(row) not in present:
            rows.append(row)
            present.add(key(row))
    rows = [row for row in rows if key(row) not in forced]
    return '\n'.join(rows + [f'{k}={v}' for k, v in forced.items()]) + '\n'


def configure(adb, work, cpu, previous=None, gpu_readback=False):
    adb.shell(shlex.join(['am', 'force-stop', PACKAGE]))
    installed = adb.run('exec-out', 'cat', REMOTE)
    backup = Path(tempfile.mkdtemp(prefix='settings-', dir=work))
    (backup / 'env-before.txt').write_text(installed)
    result = settings(installed, previous, cpu, gpu_readback)
    local = backup / 'env-test.txt'
    local.write_text(result, encoding='utf-8', newline='\n')
    temporary = REMOTE + '.pr-test.tmp'
    adb.push_file(local, temporary)
    adb.shell(shlex.join(['mv', '-f', temporary, REMOTE]))
    if adb.run('exec-out', 'cat', REMOTE).replace('\r\n', '\n') != result:
        raise ValueError(f'Settings verification failed. Backup: {backup}')
    print(f'Configured {LABEL}, mode: {"CPU BC test" if cpu else "native BC baseline"}.')
    print(f'GPU snapshots: {"on" if gpu_readback else "off"}')
    print(f'Settings backup: {backup}')


def main():
    adb_error = type('UnavailableAdbError', (Exception,), {})
    home = Path.home()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game-folder', type=Path, default=home / 'MK8-DLUXE-NSwiTcH')
    p.add_argument('--keys', type=Path, default=home / 'Downloads/ProdKeys.NET-v22.5.0/prod.keys')
    p.add_argument('--driver', type=Path, default=home / 'Downloads/turnip_v24.3.0_R9v2.zip')
    p.add_argument('--device')
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--cpu-bc', action='store_true', help='force the CPU fallback to exercise the PR; default is a native-BC baseline')
    p.add_argument('--gpu-readback', action='store_true', help='opt into ordered snapshots; requires --cpu-bc')
    p.add_argument('--configure-only', type=Path, help='work folder printed by a previous build; verify the installed host and switch mode without rebuilding')
    args = p.parse_args()
    try:
        if args.gpu_readback and not args.cpu_bc:
            raise ValueError('--gpu-readback requires --cpu-bc for this test workflow')
        dependencies()
        if args.configure_only:
            work = args.configure_only.expanduser().resolve()
            receipt = json.loads((work / 'build.json').read_text())
            if receipt.get('package') != PACKAGE:
                raise ValueError('This receipt is not for the separate PR test app. Run a new build with this helper.')
            if receipt.get('commit') != COMMIT:
                raise ValueError('This receipt uses an older PR runtime. Rebuild before testing the review changes.')
            repo = Path(receipt['source'])
        else:
            game = args.game_folder.expanduser().resolve()
            keys = args.keys.expanduser().resolve()
            driver = args.driver.expanduser().resolve()
            if not game.is_dir() or not keys.is_file() or not driver.is_file() or args.jobs < 1:
                raise ValueError('Check --game-folder, --keys, --driver and --jobs')
            work = Path(tempfile.mkdtemp(prefix='mk8-pr-test-', dir=game))
            print(f'Work folder: {work}', flush=True)
            repo = source(work)
        sys.path.insert(0, str(repo))
        from porter import config, toolchain
        from porter.adb import Adb, AdbError
        adb_error = AdbError
        cfg = config.load()
        adb = Adb(toolchain.find_adb(cfg), args.device or cfg.get('device'))
        serial = adb.pick()
        if args.configure_only:
            if serial != receipt['device']:
                raise ValueError('Select the same phone used for this build with --device')
            paths = adb.shell(shlex.join(['pm', 'path', PACKAGE])).splitlines()
            base = next((s[len('package:'):] for s in paths if s.startswith('package:') and s.endswith('/base.apk')), None)
            if not base:
                raise ValueError('Installed base APK not found')
            with tempfile.TemporaryDirectory() as tmp:
                apk = Path(tmp) / 'base.apk'
                adb.run('pull', base, str(apk), timeout=120)
                if host_hash(apk) != receipt['host_sha256']:
                    raise ValueError('Installed runtime differs from this PR build; settings were not changed')
            configure(adb, work, args.cpu_bc, gpu_readback=args.gpu_readback)
            return
        library = driver_library(driver, work)
        output = work / 'port'
        command = [sys.executable, '-m', 'porter', 'port', str(game), '-k', str(keys),
                   '--experimental', '--package', PACKAGE, '--app-name', LABEL,
                   '--jobs', str(args.jobs), '--vulkan-driver', str(library), '-o', str(output)]
        subprocess.run(command, cwd=repo, check=True)
        manifests = list(output.glob('*-data/nx2a-data.json'))
        if len(manifests) != 1 or json.loads(manifests[0].read_text()).get('package') != PACKAGE:
            raise ValueError('Unexpected built data pack')
        data = manifests[0].parent
        apk = output / (data.name.removesuffix('-data') + '.apk')
        sha = host_hash(apk)
        exists = adb.shell(f'if [ -f {shlex.quote(REMOTE)} ]; then printf yes; else printf no; fi').strip()
        if exists not in ('yes', 'no'):
            raise ValueError('Could not check existing phone settings')
        previous = adb.run('exec-out', 'cat', REMOTE) if exists == 'yes' else None
        if previous is not None:
            (work / 'env-before-install.txt').write_text(previous)
        (work / 'build.json').write_text(json.dumps({'commit': COMMIT, 'source': str(repo),
            'apk': str(apk), 'host_sha256': sha, 'device': serial, 'package': PACKAGE}, indent=2) + '\n')
        subprocess.run([sys.executable, '-m', 'porter', 'install', str(data), '--apk', str(apk),
                        '--device', serial], cwd=repo, check=True)
        configure(adb, work, args.cpu_bc, previous, args.gpu_readback)
        print('APK:', apk)
        print(f'Open {LABEL}. It has separate saves and settings from the working app.')
        print('Switch to CPU BC without rebuilding:')
        print(shlex.join([sys.executable, str(Path(__file__).resolve()), '--configure-only', str(work), '--cpu-bc', '--gpu-readback']))
        print('The isolated branch lacks other MK8 fixes from the full fork. A failed CPU-mode launch alone does not prove a regression in this PR.')
    except (OSError, ValueError, KeyError, ModuleNotFoundError, zipfile.BadZipFile, subprocess.CalledProcessError, adb_error) as error:
        p.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
