#!/usr/bin/env python3
"""Build/install separate native and CPU BC test apps for the isolated upload PR."""
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

COMMIT = '308a672078e0ec5850acb23945f8ad05a4f4929c'
PACKAGE = 'org.nx2a.t0100152000022000.prtest'
LABEL = 'MK8 PR Test'
CPU_PACKAGE = PACKAGE + '.cpubc'
CPU_LABEL = 'MK8 CPU BC Test'
UPSTREAM_PACKAGE = PACKAGE + '.cpubaseline'
UPSTREAM_LABEL = 'MK8 CPU BC Baseline'
UPSTREAM_COMMIT = '5e4ea3b5953944163987ecc2752258e551c3ba06'
DRIVER = 'libmk8_pr_turnip.so'
MARKER = b'BC buffer readback allocation failed'
BASELINE_MARKER = b'copy of a BC texture decoded on the CPU into a buffer: skipped'
# label, source commit, repository, forced CPU decoding, expected host marker
PROFILES = {
    PACKAGE: (LABEL, COMMIT, 'kianborg/nx2android-mk8-deluxe', False, MARKER),
    CPU_PACKAGE: (CPU_LABEL, COMMIT, 'kianborg/nx2android-mk8-deluxe', True, MARKER),
    UPSTREAM_PACKAGE: (UPSTREAM_LABEL, UPSTREAM_COMMIT, 'shirai91/nx2android', True, BASELINE_MARKER),
}


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


def source(work, commit=COMMIT, repository='kianborg/nx2android-mk8-deluxe', ordered=True):
    archive = work / 'source.zip'
    url = f'https://github.com/{repository}/archive/{commit}.zip'
    print(f'Downloading {repository} at {commit[:7]}...', flush=True)
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
    has_ordered = 'vk_buffer_snapshot(src, src_off, size, blocks)' in code
    if has_ordered != ordered or BASELINE_MARKER.decode() not in code:
        raise ValueError('Downloaded source does not match the selected BC upload profile')
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


def host_hash(apk, marker=MARKER):
    with zipfile.ZipFile(apk) as z:
        entry = z.getinfo('lib/arm64-v8a/libdmhost.so')
        if entry.file_size > 128 * 1024**2:
            raise ValueError('Native host is too large')
        data = z.read(entry)
    if marker not in data:
        raise ValueError('APK lacks the selected BC upload code; installation/settings stopped')
    if marker == BASELINE_MARKER and MARKER in data:
        raise ValueError('Baseline APK contains the PR upload code; installation/settings stopped')
    return hashlib.sha256(data).hexdigest()


def settings(installed, previous, cpu, gpu_readback=False, system_driver=False):
    forced = {'DM_VK_DRIVER': None if system_driver else DRIVER, 'DM_VK_X_BC_CPU': str(int(cpu)),
              'DM_VK_X_BC_GPU_READBACK': str(int(gpu_readback)), 'DM_VK_BC_DECODE': '0', 'DM_VK_NOPCACHE': '1'}
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
    return '\n'.join(rows + [f'{k}={v}' for k, v in forced.items() if v is not None]) + '\n'


def configure(adb, work, cpu, previous=None, gpu_readback=False, *, package=PACKAGE, label=LABEL, system_driver=False):
    remote = f'/sdcard/Android/data/{package}/files/env.txt'
    adb.shell(shlex.join(['am', 'force-stop', package]))
    installed = adb.run('exec-out', 'cat', remote)
    backup = Path(tempfile.mkdtemp(prefix='settings-', dir=work))
    (backup / 'env-before.txt').write_text(installed)
    result = settings(installed, previous, cpu, gpu_readback, system_driver)
    local = backup / 'env-test.txt'
    local.write_text(result, encoding='utf-8', newline='\n')
    temporary = remote + '.pr-test.tmp'
    adb.push_file(local, temporary)
    adb.shell(shlex.join(['mv', '-f', temporary, remote]))
    if adb.run('exec-out', 'cat', remote).replace('\r\n', '\n') != result:
        raise ValueError(f'Settings verification failed. Backup: {backup}')
    print(f'Configured {label}, BC selection: {"forced CPU" if cpu else "automatic (check the runtime log)"}.')
    print(f'Vulkan driver: {"system" if system_driver else "bundled Turnip"}')
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
    p.add_argument('--cpu-bc', action='store_true', help='build the separate MK8 CPU BC Test app; default builds the native-BC baseline app')
    p.add_argument('--lenovo', action='store_true', help='Lenovo Idea Tab 5G: system Vulkan, no Turnip ZIP, automatic BC selection in a separate test app')
    p.add_argument('--upstream-baseline', action='store_true', help='build a separate unchanged-upstream app with CPU BC forced and GPU readback off')
    p.add_argument('--gpu-readback', action='store_true', help='opt into ordered snapshots in the CPU BC test app')
    p.add_argument('--configure-only', type=Path, help='work folder from a previous build; verify that app and change its readback setting without rebuilding')
    args = p.parse_args()
    try:
        if args.lenovo:
            args.cpu_bc = True
        package = UPSTREAM_PACKAGE if args.upstream_baseline else CPU_PACKAGE if args.cpu_bc else PACKAGE
        dependencies()
        if args.configure_only:
            work = args.configure_only.expanduser().resolve()
            receipt = json.loads((work / 'build.json').read_text())
            if receipt.get('package') not in PROFILES:
                raise ValueError('This receipt is not for the separate PR test app. Run a new build with this helper.')
            package = receipt['package']
            if args.upstream_baseline and package != UPSTREAM_PACKAGE:
                raise ValueError('This receipt is not for the upstream CPU baseline. Build it with --upstream-baseline first.')
            if args.cpu_bc and package == PACKAGE:
                raise ValueError('This is a native BC app receipt. Build again with --cpu-bc to install the separate CPU BC app.')
            label, commit, repository, cpu, marker = PROFILES[package]
            if receipt.get('commit') != commit:
                raise ValueError('This receipt uses an older PR runtime. Rebuild before testing the review changes.')
            repo = Path(receipt['source'])
            system_driver = args.lenovo or receipt.get('system_driver', False)
            cpu = False if args.lenovo else receipt.get('force_cpu', cpu)
        else:
            label, commit, repository, cpu, marker = PROFILES[package]
            system_driver = args.lenovo
            if args.lenovo:
                cpu = False
            if args.gpu_readback and package != CPU_PACKAGE:
                raise ValueError('--gpu-readback requires --cpu-bc and is unavailable in the upstream baseline')
            game = args.game_folder.expanduser().resolve()
            keys = args.keys.expanduser().resolve()
            driver = args.driver.expanduser().resolve()
            if not game.is_dir() or not keys.is_file() or (not system_driver and not driver.is_file()) or args.jobs < 1:
                raise ValueError('Check --game-folder, --keys, --driver and --jobs')
            work = Path(tempfile.mkdtemp(prefix='mk8-pr-test-', dir=game))
            print(f'Work folder: {work}', flush=True)
            repo = source(work, commit, repository, ordered=package != UPSTREAM_PACKAGE)
        if args.gpu_readback and package != CPU_PACKAGE:
            raise ValueError('--gpu-readback requires the CPU BC PR test app')
        remote = f'/sdcard/Android/data/{package}/files/env.txt'
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
            paths = adb.shell(shlex.join(['pm', 'path', package])).splitlines()
            base = next((s[len('package:'):] for s in paths if s.startswith('package:') and s.endswith('/base.apk')), None)
            if not base:
                raise ValueError('Installed base APK not found')
            with tempfile.TemporaryDirectory() as tmp:
                apk = Path(tmp) / 'base.apk'
                adb.run('pull', base, str(apk), timeout=120)
                if host_hash(apk, marker) != receipt['host_sha256']:
                    raise ValueError('Installed runtime differs from this PR build; settings were not changed')
            configure(adb, work, cpu, gpu_readback=args.gpu_readback, package=package, label=label, system_driver=system_driver)
            return
        library = None if system_driver else driver_library(driver, work)
        output = work / 'port'
        command = [sys.executable, '-m', 'porter', 'port', str(game), '-k', str(keys),
                   '--experimental', '--package', package, '--app-name', label,
                   '--jobs', str(args.jobs), '-o', str(output)]
        if library:
            command += ['--vulkan-driver', str(library)]
        subprocess.run(command, cwd=repo, check=True)
        manifests = list(output.glob('*-data/nx2a-data.json'))
        if len(manifests) != 1 or json.loads(manifests[0].read_text()).get('package') != package:
            raise ValueError('Unexpected built data pack')
        data = manifests[0].parent
        apk = output / (data.name.removesuffix('-data') + '.apk')
        sha = host_hash(apk, marker)
        exists = adb.shell(f'if [ -f {shlex.quote(remote)} ]; then printf yes; else printf no; fi').strip()
        if exists not in ('yes', 'no'):
            raise ValueError('Could not check existing phone settings')
        previous = adb.run('exec-out', 'cat', remote) if exists == 'yes' else None
        if previous is not None:
            (work / 'env-before-install.txt').write_text(previous)
        (work / 'build.json').write_text(json.dumps({'commit': commit, 'source': str(repo),
            'system_driver': system_driver, 'force_cpu': cpu,
            'apk': str(apk), 'host_sha256': sha, 'device': serial, 'package': package}, indent=2) + '\n')
        subprocess.run([sys.executable, '-m', 'porter', 'install', str(data), '--apk', str(apk),
                        '--device', serial], cwd=repo, check=True)
        configure(adb, work, cpu, previous, args.gpu_readback, package=package, label=label, system_driver=system_driver)
        print('APK:', apk)
        print(f'Open {label}. It has separate saves and settings from the working app.')
        if package == UPSTREAM_PACKAGE:
            print(f'Unchanged upstream {commit[:7]}: BC {"forced CPU" if cpu else "automatic"}, GPU readback off.')
            print('Compare the same scene with MK8 CPU BC Test, with readback off in both apps.')
        elif package == CPU_PACKAGE:
            print('Enable GPU readback for this CPU BC app without rebuilding:')
            print(shlex.join([sys.executable, str(Path(__file__).resolve()), '--configure-only', str(work), '--gpu-readback']))
            print('Omit --gpu-readback to turn readback off; driver and BC selection stay unchanged.')
        else:
            print('Build the separate CPU BC app by running this helper again with --cpu-bc.')
        print('The isolated branch lacks other MK8 fixes from the full fork. A failed CPU-mode launch alone does not prove a regression in this PR.')
        if system_driver:
            print('Confirm the log says "BC no (decoded on the CPU)" before reporting native CPU-fallback coverage.')
    except (OSError, ValueError, KeyError, ModuleNotFoundError, zipfile.BadZipFile, subprocess.CalledProcessError, adb_error) as error:
        p.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
