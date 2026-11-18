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

COMMIT = '4c5a41959b7930e0e15f5603a4abd2325cfd0d8a'
PACKAGE = 'org.nx2a.t0100152000022000.prtest'
LABEL = 'MK8 PR Test'
CPU_PACKAGE = PACKAGE + '.cpubc'
CPU_LABEL = 'MK8 CPU BC Test'
UPSTREAM_PACKAGE = PACKAGE + '.cpubaseline'
UPSTREAM_LABEL = 'MK8 CPU BC Baseline'
UPSTREAM_COMMIT = 'e5a4703aec9af80a82c21669a8c01a3652ceb2bc'
DRIVER = 'libmk8_pr_turnip.so'
MARKER = b'BC buffer readback allocation failed'
BASELINE_MARKER = b'copy of a BC texture decoded on the CPU into a buffer: skipped'
# label, source commit, repository, forced CPU decoding, expected host marker
PROFILES = {
    PACKAGE: (LABEL, COMMIT, 'kianborg/nx2android-mk8-deluxe', False, MARKER),
    CPU_PACKAGE: (CPU_LABEL, COMMIT, 'kianborg/nx2android-mk8-deluxe', True, MARKER),
    UPSTREAM_PACKAGE: (UPSTREAM_LABEL, UPSTREAM_COMMIT, 'shirai91/nx2android', True, BASELINE_MARKER),
}


GAMES = {
    'mk8': ('0100152000022000', 'MK8'),
    'odyssey': ('0100000000010000', 'Odyssey'),
    '3dworld': ('010028600EBDA000', '3D World'),
}
SUCCESS_MARKER = b'BC CPU buffer upload:'


def profiles_for(game):
    title, name = GAMES[game]
    native = f'org.nx2a.t{title}.prtest'
    cpu, base = native + '.cpubc', native + '.cpubaseline'
    return native, cpu, base, {
        native: (name + ' PR Test', COMMIT, 'kianborg/nx2android-mk8-deluxe', False, MARKER),
        cpu: (name + ' CPU BC Test', COMMIT, 'kianborg/nx2android-mk8-deluxe', True, MARKER),
        base: (name + ' CPU BC Baseline', UPSTREAM_COMMIT, 'shirai91/nx2android', True, BASELINE_MARKER),
    }



CLIP_MARKER = b'GL clip depth remapped to Vulkan'
CLIP_REVISION = '5134759b5a150e9877c30c3497401ef7402c1813'
CLIP_ASSETS = {'spv_depth.c': '47954b368e05a27cf02e831672ce8bf35215e430c12010216866fb82ffbc1e74', 'spv_depth.h': '96327d43b7914b218f5f4fa67f23ba17f979ff16d0959ee23c78a193d746c567'}


def apply_clip_depth(repo):
    """Diagnostic-only: apply the same conversion to the two pinned source trees."""
    android = repo / 'nxnative/dm/android'
    def replace_once(text, old, new):
        if text.count(old) != 1:
            raise ValueError('Clip-depth experiment source mismatch: ' + old[:70])
        return text.replace(old, new, 1)
    shader = (android / 'gfx_vk_shader.c').read_text()
    shader = '#include "spv_depth.h"\n' + shader
    shader = replace_once(shader, '    int dual = fd >> 1 & 1;', '    int depth_remap = (fd & 4) && (s->stage == 0 || s->stage == 2);\n    int dual = fd >> 1 & 1;')
    shader = replace_once(shader, '(uint32_t)fd | (uint32_t)dual)', '(uint32_t)fd | (uint32_t)dual | (uint32_t)depth_remap)')
    shader = shader.replace('fd | dual << 1', 'fd | dual << 1 | depth_remap << 2')
    block = """    if (depth_remap) {
        if ((nb || xo || fd || dual) && !w) die("[vk] prerequisite depth variant failed");
        uint32_t n2 = 0, *w2 = vk_spv_depth_remap(w ? w : s->spv, nw, &n2);
        free(w); w = w2; nw = n2;
        if (!w) die("[vk] GL clip-depth remap failed");
    }
"""
    shader = replace_once(shader, '    if (w) { VkShaderModuleCreateInfo ci', block + '    if (w) { VkShaderModuleCreateInfo ci')
    shader = replace_once(shader, 'if (vkCreateShaderModule(V.dev, &ci, NULL, &m)) { m = s->mod;', 'if (vkCreateShaderModule(V.dev, &ci, NULL, &m)) { if (depth_remap) die("[vk] required clip-depth variant refused"); m = s->mod;')
    shader = replace_once(shader, '    if (s->nvar < 8) s->var[s->nvar++] = (typeof(s->var[0])){um, im, xo,', '    if (depth_remap) VKLOG("shader %016llx: GL clip depth remapped to Vulkan (z = (z + w) / 2)", (unsigned long long)s->key);\n    if (s->nvar < 8) s->var[s->nvar++] = (typeof(s->var[0])){um, im, xo,')
    executor = (android / 'gfx_vk_exec.c').read_text()
    start = executor.index('    for (int i = 0; i < 3; i++) if (stg[i] && !(i == 1 && k->raster_discard)) ss[ns++]')
    end = executor.index('\n', start)
    line = executor[start:end]
    line = line.replace(')) ss[ns++]', ')) {\n        int remap = k->clip_neg1 && !V.has_depth_clip_ctl && i == (stg[2] ? 2 : 0) && !k->raster_discard;\n        ss[ns++]')
    line = line.replace('k->alt &&', 'k->alt && !remap &&').replace('i == 1 ? (k->fdz ? 1 : 0) | (k->dual ? 2 : 0) : 0)', '(i == 1 ? (k->fdz ? 1 : 0) | (k->dual ? 2 : 0) : 0) | (remap ? 4 : 0))')
    line += '\n    }'
    executor = executor[:start] + line + executor[end:]
    # Verify all assets before writing modified source. The helper only changes a fresh downloaded work tree.
    assets = {}
    for name, digest in CLIP_ASSETS.items():
        url = f'https://raw.githubusercontent.com/kianborg/nx2android-mk8-deluxe/{CLIP_REVISION}/nxnative/dm/android/{name}'
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(1024 * 1024)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Clip-depth asset checksum mismatch: ' + name)
        assets[name] = data
    for name, data in assets.items():
        (android / name).write_bytes(data)
    (android / 'gfx_vk_shader.c').write_text(shader)
    (android / 'gfx_vk_exec.c').write_text(executor)


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
    if marker == MARKER and SUCCESS_MARKER not in data:
        raise ValueError('APK lacks the CPU-upload success diagnostic; installation/settings stopped')
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
    p.add_argument('--game', choices=GAMES, default='mk8', help='game identity for the separate test app')
    p.add_argument('--game-folder', type=Path)
    p.add_argument('--keys', type=Path, default=home / 'Downloads/ProdKeys.NET-v22.5.0/prod.keys')
    p.add_argument('--driver', type=Path, default=home / 'Downloads/turnip_v24.3.0_R9v2.zip')
    p.add_argument('--device')
    p.add_argument('--jobs', type=int, default=2)
    p.add_argument('--cpu-bc', action='store_true', help='build the separate MK8 CPU BC Test app; default builds the native-BC baseline app')
    p.add_argument('--clip-depth-test', action='store_true', help='diagnostic Lenovo build with clip-depth conversion; separate app, readback off')
    p.add_argument('--lenovo', action='store_true', help='Lenovo Idea Tab 5G: system Vulkan, no Turnip ZIP, automatic BC selection in a separate test app')
    p.add_argument('--upstream-baseline', action='store_true', help='build a separate unchanged-upstream app with CPU BC forced and GPU readback off')
    p.add_argument('--gpu-readback', action='store_true', help='opt into ordered snapshots in the CPU BC test app')
    p.add_argument('--configure-only', type=Path, help='work folder from a previous build; verify that app and change its readback setting without rebuilding')
    args = p.parse_args()
    try:
        native_package, cpu_package, upstream_package, profiles = profiles_for(args.game)
        if args.game != 'mk8' and (args.lenovo or args.clip_depth_test):
            raise ValueError('Other-game probes currently use the Nothing Phone/Turnip workflow; omit Lenovo/clip options')
        if args.game != 'mk8' and not args.configure_only and not args.game_folder:
            raise ValueError('Specify --game-folder for the selected game')
        if args.clip_depth_test:
            args.lenovo = True
            if args.configure_only or args.gpu_readback:
                raise ValueError('Clip-depth test requires a fresh build with GPU readback off')
        if args.lenovo:
            args.cpu_bc = True
        package = upstream_package if args.upstream_baseline else cpu_package if args.cpu_bc else native_package
        dependencies()
        if args.configure_only:
            work = args.configure_only.expanduser().resolve()
            receipt = json.loads((work / 'build.json').read_text())
            package = receipt.get('package', '')
            clip_receipt = package in (cpu_package + '.clipdepth', upstream_package + '.clipdepth')
            profile_package = package.removesuffix('.clipdepth') if clip_receipt else package
            if profile_package not in profiles:
                raise ValueError('This receipt is not for the separate PR test app. Run a new build with this helper.')
            if clip_receipt and (not receipt.get('clip_depth_test') or receipt.get('clip_revision') != CLIP_REVISION):
                raise ValueError('Clip-depth receipt does not match this diagnostic revision; rebuild before switching settings.')
            if args.upstream_baseline and profile_package != upstream_package:
                raise ValueError('This receipt is not for the upstream CPU baseline. Build it with --upstream-baseline first.')
            if args.cpu_bc and package == native_package:
                raise ValueError('This is a native BC app receipt. Build again with --cpu-bc to install the separate CPU BC app.')
            label, commit, repository, cpu, marker = profiles[profile_package]
            if clip_receipt:
                label = 'MK8 Clip Base' if profile_package == upstream_package else 'MK8 Clip PR'
            if receipt.get('commit') != commit:
                raise ValueError('This receipt uses an older PR runtime. Rebuild before testing the review changes.')
            repo = Path(receipt['source'])
            system_driver = args.lenovo or receipt.get('system_driver', False)
            cpu = False if args.lenovo else receipt.get('force_cpu', cpu)
        else:
            label, commit, repository, cpu, marker = profiles[package]
            system_driver = args.lenovo
            if args.lenovo:
                cpu = False
            if args.gpu_readback and package != cpu_package:
                raise ValueError('--gpu-readback requires --cpu-bc and is unavailable in the upstream baseline')
            game = (args.game_folder or home / 'MK8-DLUXE-NSwiTcH').expanduser().resolve()
            keys = args.keys.expanduser().resolve()
            driver = args.driver.expanduser().resolve()
            if not game.is_dir() or not keys.is_file() or (not system_driver and not driver.is_file()) or args.jobs < 1:
                raise ValueError('Check --game-folder, --keys, --driver and --jobs')
            work = Path(tempfile.mkdtemp(prefix='mk8-pr-test-', dir=game))
            print(f'Work folder: {work}', flush=True)
            repo = source(work, commit, repository, ordered=package != upstream_package)
            if args.clip_depth_test:
                apply_clip_depth(repo)
                package += '.clipdepth'
                label = 'MK8 Clip Base' if args.upstream_baseline else 'MK8 Clip PR'
        if args.gpu_readback and package not in (cpu_package, cpu_package + '.clipdepth'):
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
                if clip_receipt:
                    with zipfile.ZipFile(apk) as z:
                        if CLIP_MARKER not in z.read('lib/arm64-v8a/libdmhost.so'):
                            raise ValueError('Installed runtime lacks the clip-depth conversion; settings were not changed')
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
        manifest = json.loads(manifests[0].read_text(encoding='utf-8'))
        if manifest.get('title_id') != GAMES[args.game][0]:
            raise ValueError('Built title ID does not match --game; installation/settings stopped')
        data = manifests[0].parent
        apk = output / (data.name.removesuffix('-data') + '.apk')
        sha = host_hash(apk, marker)
        if args.clip_depth_test:
            with zipfile.ZipFile(apk) as z:
                if CLIP_MARKER not in z.read('lib/arm64-v8a/libdmhost.so'):
                    raise ValueError('Diagnostic APK lacks the clip-depth conversion')
        exists = adb.shell(f'if [ -f {shlex.quote(remote)} ]; then printf yes; else printf no; fi').strip()
        if exists not in ('yes', 'no'):
            raise ValueError('Could not check existing phone settings')
        previous = adb.run('exec-out', 'cat', remote) if exists == 'yes' else None
        if previous is not None:
            (work / 'env-before-install.txt').write_text(previous)
        (work / 'build.json').write_text(json.dumps({'commit': commit, 'source': str(repo),
            'title_id': manifest['title_id'], 'game_version': manifest.get('version'), 'display_version': manifest.get('display'),
            'system_driver': system_driver, 'force_cpu': cpu, 'clip_depth_test': args.clip_depth_test, 'clip_revision': CLIP_REVISION if args.clip_depth_test else None,
            'apk': str(apk), 'host_sha256': sha, 'device': serial, 'package': package}, indent=2) + '\n')
        subprocess.run([sys.executable, '-m', 'porter', 'install', str(data), '--apk', str(apk),
                        '--device', serial], cwd=repo, check=True)
        configure(adb, work, cpu, previous, args.gpu_readback, package=package, label=label, system_driver=system_driver)
        print('APK:', apk)
        print('Game:', manifest.get('name'), manifest.get('display'), 'title ID:', manifest['title_id'])
        print(f'Open {label}. It has separate saves and settings from the working app.')
        if args.clip_depth_test:
            print('Diagnostic only: compare picture and GL clip depth remapped to Vulkan log lines. GPU readback is off.')
        elif package == upstream_package:
            print(f'Unchanged upstream {commit[:7]}: BC {"forced CPU" if cpu else "automatic"}, GPU readback off.')
            print(f'Compare the same scene with {profiles[cpu_package][0]}, with readback off in both apps.')
        elif package == cpu_package:
            print('Enable GPU readback for this CPU BC app without rebuilding:')
            print(shlex.join([sys.executable, str(Path(__file__).resolve()), '--game', args.game, '--configure-only', str(work), '--gpu-readback']))
            print('Omit --gpu-readback to turn readback off; driver and BC selection stay unchanged.')
        else:
            print('Build the separate CPU BC app by running this helper again with --cpu-bc.')
        if args.game == 'mk8':
            print('The isolated branch lacks other MK8 fixes from the full fork. A failed CPU-mode launch alone does not prove a regression in this PR.')
        else:
            print('Candidate reproducer: record the game version and scene, and check for the BC CPU buffer upload success line before claiming path coverage.')
        if system_driver:
            print('Confirm the log says "BC no (decoded on the CPU)" before reporting native CPU-fallback coverage.')
    except (OSError, ValueError, KeyError, ModuleNotFoundError, zipfile.BadZipFile, subprocess.CalledProcessError, adb_error) as error:
        p.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
