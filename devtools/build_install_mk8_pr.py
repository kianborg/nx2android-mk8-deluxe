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

COMMIT = '6eb7bcb4896d41a4baf93a89bdf3ec746e4c2c00'
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
    'hollow-knight': ('0100633007D48000', 'Hollow Knight'),
}
SUCCESS_MARKER = b'BC CPU buffer upload:'
TRACE_MARKER = b'BC transfer trace v1:'

# Diagnostic-only instrumentation, applied to a fresh download, never to the PR.
TRACE_RECORD = r'''
// BC transfer trace v1: recording counters (diagnostic test build only).
static uint64_t bc_probe_requests, bc_probe_bc_requests, bc_probe_formats[158];
static int bc_probe_on(void) {
    static int on = -1;
    int value = __atomic_load_n(&on, __ATOMIC_ACQUIRE);
    if (value < 0) { const char *e = getenv("DM_VK_X_BC_TRANSFER_TRACE"); value = e && atoi(e); __atomic_store_n(&on, value, __ATOMIC_RELEASE); }
    return value;
}
void vk_bc_probe_summary(uint64_t requests, uint64_t bc_requests);
static void bc_probe_record(const p_copy_b2t *c) {
    if (!bc_probe_on()) return;
    int f = c->tex && c->tex->magic == MAGIC('T','E','X',0) ? c->tex->d.format : -1;
    __atomic_fetch_add(&bc_probe_requests, 1, __ATOMIC_RELAXED);
    if (f >= 0x41 && f <= 0x50) __atomic_fetch_add(&bc_probe_bc_requests, 1, __ATOMIC_RELAXED);
    unsigned key = f >= 0 && f < 157 ? (unsigned)f : 157;
    uint64_t n = __atomic_add_fetch(&bc_probe_formats[key], 1, __ATOMIC_RELAXED);
    if (n <= 3 || !(n & (n - 1))) LOG("[nvn] BC transfer trace v1: record b2t format=%#x count=%llu request=%dx%dx%d offset=%d,%d,%d level=%u view_format=%#x",
        f, (unsigned long long)n, c->r.width, c->r.height, c->r.depth, c->r.xoffset, c->r.yoffset, c->r.zoffset,
        c->has_view && c->view.set_levels ? c->view.base_level : 0, c->has_view && c->view.set_format ? c->view.format : 0);
}
// End BC recording trace.
'''

TRACE_REPLAY = r'''
// BC transfer trace v1: replay outcomes (diagnostic test build only).
enum { BC_PROBE_ENTRY, BC_PROBE_LOOKUP, BC_PROBE_REGION, BC_PROBE_EXTENT,
    BC_PROBE_ROW, BC_PROBE_SLICE, BC_PROBE_SOURCE, BC_PROBE_SIZE, BC_PROBE_REFUSED,
    BC_PROBE_DECODE, BC_PROBE_CPU, BC_PROBE_GPU, BC_PROBE_NATIVE_SOURCE, BC_PROBE_NATIVE, BC_PROBE_COUNT };
static uint64_t bc_probe_replayed, bc_probe_bc_replayed, bc_probe_cpu, bc_probe_native, bc_probe_skips;
static uint64_t bc_probe_outcomes[BC_PROBE_COUNT][158];
static int bc_probe_on(void) {
    static int on = -1;
    int value = __atomic_load_n(&on, __ATOMIC_ACQUIRE);
    if (value < 0) { const char *e = getenv("DM_VK_X_BC_TRANSFER_TRACE"); value = e && atoi(e); __atomic_store_n(&on, value, __ATOMIC_RELEASE); }
    return value;
}
static void bc_probe_result(const p_copy_b2t *c, int to_texture, unsigned event) {
    if (!to_texture || !bc_probe_on()) return;
    static const char *names[] = {"entry", "image-or-format-unavailable", "invalid-region", "invalid-extent",
        "invalid-row-stride", "invalid-slice-stride", "source-outside-pools", "decoded-size-overflow", "readback-refused",
        "decode-failed", "cpu-upload", "gpu-snapshot-upload", "native-source-unavailable", "native-upload"};
    int f = c->tex && c->tex->magic == MAGIC('T','E','X',0) ? c->tex->d.format : -1;
    if (event == BC_PROBE_ENTRY) {
        __atomic_fetch_add(&bc_probe_replayed, 1, __ATOMIC_RELAXED);
        if (f >= 0x41 && f <= 0x50) __atomic_fetch_add(&bc_probe_bc_replayed, 1, __ATOMIC_RELAXED);
    } else if (event == BC_PROBE_CPU || event == BC_PROBE_GPU) __atomic_fetch_add(&bc_probe_cpu, 1, __ATOMIC_RELAXED);
    else if (event == BC_PROBE_NATIVE) __atomic_fetch_add(&bc_probe_native, 1, __ATOMIC_RELAXED);
    else __atomic_fetch_add(&bc_probe_skips, 1, __ATOMIC_RELAXED);
    unsigned key = f >= 0 && f < 157 ? (unsigned)f : 157;
    uint64_t n = __atomic_add_fetch(&bc_probe_outcomes[event][key], 1, __ATOMIC_RELAXED);
    if (n <= 3 || !(n & (n - 1))) VKLOG("BC transfer trace v1: replay b2t format=%#x outcome=%s count=%llu request=%dx%dx%d offset=%d,%d,%d level=%u view_format=%#x",
        f, names[event], (unsigned long long)n, c->r.width, c->r.height, c->r.depth, c->r.xoffset, c->r.yoffset, c->r.zoffset,
        c->has_view && c->view.set_levels ? c->view.base_level : 0, c->has_view && c->view.set_format ? c->view.format : 0);
}
void vk_bc_probe_summary(uint64_t requests, uint64_t bc_requests) {
    if (!bc_probe_on()) return;
    VKLOG("BC transfer trace v1: summary recorded=%llu recorded_bc=%llu replayed=%llu replayed_bc=%llu cpu_uploads=%llu native_uploads=%llu skips=%llu",
        (unsigned long long)requests, (unsigned long long)bc_requests,
        (unsigned long long)__atomic_load_n(&bc_probe_replayed, __ATOMIC_RELAXED),
        (unsigned long long)__atomic_load_n(&bc_probe_bc_replayed, __ATOMIC_RELAXED),
        (unsigned long long)__atomic_load_n(&bc_probe_cpu, __ATOMIC_RELAXED),
        (unsigned long long)__atomic_load_n(&bc_probe_native, __ATOMIC_RELAXED),
        (unsigned long long)__atomic_load_n(&bc_probe_skips, __ATOMIC_RELAXED));
}
// End BC replay trace.
'''


def apply_transfer_trace(repo):
    """Patch only the downloaded test tree; fail closed if its source changed."""
    recording = repo / 'nxnative/dm/gfx/nvn/hle_nvn.c'
    replay = repo / 'nxnative/dm/android/gfx_vk_exec.c'
    nvn, code = recording.read_text(encoding='utf-8'), replay.read_text(encoding='utf-8')
    if TRACE_MARKER.decode() in nvn or TRACE_MARKER.decode() in code:
        raise ValueError('Transfer trace is already applied; use a fresh source tree')
    def replace(text, old, new):
        if text.count(old) != 1:
            raise ValueError('Transfer trace source mismatch: ' + old[:70])
        return text.replace(old, new, 1)
    anchor = 'NVN(nvnCommandBufferCopyBufferToTexture,'
    nvn = replace(nvn, anchor, TRACE_RECORD + '\n' + anchor)
    lines = [s for s in nvn.splitlines() if 'p_copy_b2t *o = REC_SNAP(c, OP_COPY_B2T,' in s]
    if len(lines) != 1:
        raise ValueError('Transfer trace recording source mismatch')
    line = lines[0]
    nvn = replace(nvn, line, line + '\n    bc_probe_record(o);')
    nvn = replace(nvn, '    g_frame++; cs_dump();', '''    if (bc_probe_on() && g_frame % 300 == 0) vk_bc_probe_summary(
        __atomic_load_n(&bc_probe_requests, __ATOMIC_RELAXED), __atomic_load_n(&bc_probe_bc_requests, __ATOMIC_RELAXED));
    g_frame++; cs_dump();''')
    start = code.index('static void copy_b2t(')
    end = code.index('// Scaled copies of depth and stencil:', start)
    block = code[start:end]
    block = replace(block, '    vk_end_pass_land();', '    bc_probe_result(c, to_texture, BC_PROBE_ENTRY);\n    vk_end_pass_land();')
    block = replace(block, '    if (!im || !f) return;', '    if (!im || !f) { bc_probe_result(c, to_texture, BC_PROBE_LOOKUP); return; }')
    reasons = {
        'invalid BC buffer upload region; copy skipped': ['BC_PROBE_REGION', 'BC_PROBE_EXTENT'],
        'invalid BC upload row stride; copy skipped': ['BC_PROBE_ROW'],
        'invalid BC upload slice stride; copy skipped': ['BC_PROBE_SLICE'],
        'BC upload source outside memory pools; copy skipped': ['BC_PROBE_SOURCE'],
        'BC upload is too large; copy skipped': ['BC_PROBE_SIZE'],
        'BC buffer upload decode failed; copy skipped': ['BC_PROBE_DECODE'],
    }
    for message, events in reasons.items():
        needle = f'VKRED_ONCE(71, "{message}"); return;'
        if block.count(needle) != len(events):
            raise ValueError('Transfer trace outcome mismatch: ' + message)
        for event in events:
            block = block.replace(needle, f'VKRED_ONCE(71, "{message}"); bc_probe_result(c, to_texture, {event}); return;', 1)
    block = replace(block, 'if (!vk_buffer_snapshot(src, src_off, size, blocks)) { free(blocks); return; }',
                    'if (!vk_buffer_snapshot(src, src_off, size, blocks)) { free(blocks); bc_probe_result(c, to_texture, BC_PROBE_REFUSED); return; }')
    block = replace(block, '        im->gpu_w = 1; vk_img_barrier_all(cb);',
                    '        im->gpu_w = 1; vk_img_barrier_all(cb);\n        bc_probe_result(c, to_texture, used_readback ? BC_PROBE_GPU : BC_PROBE_CPU);')
    block = replace(block, 'VKRED_ONCE(70, "buffer of a buffer ↔ texture copy outside the memory pools"); return;',
                    'VKRED_ONCE(70, "buffer of a buffer ↔ texture copy outside the memory pools"); bc_probe_result(c, to_texture, BC_PROBE_NATIVE_SOURCE); return;')
    block = replace(block, 'im->gpu_w = 1; }', 'im->gpu_w = 1; bc_probe_result(c, to_texture, BC_PROBE_NATIVE); }')
    code = code[:start] + TRACE_REPLAY + '\n' + block + code[end:]
    recording.write_text(nvn, encoding='utf-8')
    replay.write_text(code, encoding='utf-8')


def profiles_for(game):
    title, name = GAMES[game]
    native = f'org.nx2a.t{title.lower()}.prtest'
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


def host_hash(apk, marker=MARKER, transfer_trace=False):
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
    if transfer_trace and (TRACE_MARKER not in data or b'DM_VK_X_BC_TRANSFER_TRACE' not in data):
        raise ValueError('APK lacks transfer tracing; installation/settings stopped')
    return hashlib.sha256(data).hexdigest()


def settings(installed, previous, cpu, gpu_readback=False, system_driver=False, transfer_trace=False):
    forced = {'DM_VK_DRIVER': None if system_driver else DRIVER, 'DM_VK_X_BC_CPU': str(int(cpu)),
              'DM_VK_X_BC_GPU_READBACK': str(int(gpu_readback)), 'DM_VK_BC_DECODE': '0', 'DM_VK_NOPCACHE': '1',
              'DM_VK_X_BC_TRANSFER_TRACE': str(int(transfer_trace))}
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


def configure(adb, work, cpu, previous=None, gpu_readback=False, *, package=PACKAGE, label=LABEL, system_driver=False, transfer_trace=False):
    remote = f'/sdcard/Android/data/{package}/files/env.txt'
    adb.shell(shlex.join(['am', 'force-stop', package]))
    installed = adb.run('exec-out', 'cat', remote)
    backup = Path(tempfile.mkdtemp(prefix='settings-', dir=work))
    (backup / 'env-before.txt').write_text(installed)
    result = settings(installed, previous, cpu, gpu_readback, system_driver, transfer_trace)
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
    print(f'Transfer trace: {"on (diagnostic build)" if transfer_trace else "off"}')
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
    p.add_argument('--cpu-bc', action='store_true', help='build the selected game\'s separate CPU BC Test app; default builds the native-BC baseline app')
    p.add_argument('--clip-depth-test', action='store_true', help='diagnostic Lenovo build with clip-depth conversion; separate app, readback off')
    p.add_argument('--lenovo', action='store_true', help='Lenovo Idea Tab 5G: system Vulkan, no Turnip ZIP, automatic BC selection in a separate test app')
    p.add_argument('--upstream-baseline', action='store_true', help='build a separate unchanged-upstream app with CPU BC forced and GPU readback off')
    p.add_argument('--gpu-readback', action='store_true', help='opt into ordered snapshots in the CPU BC test app')
    p.add_argument('--trace-transfers', action='store_true', help='diagnostic PR test build: trace buffer-to-texture formats, replay outcomes and periodic totals')
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
        if args.trace_transfers and (args.upstream_baseline or args.clip_depth_test or (not args.cpu_bc and not args.configure_only)):
            raise ValueError('--trace-transfers requires the CPU BC PR test app; omit upstream/clip options')
        transfer_trace = args.trace_transfers
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
            if args.trace_transfers and receipt.get('transfer_trace') != 'v1':
                raise ValueError('This app lacks transfer tracing; rebuild with --cpu-bc --trace-transfers first')
            transfer_trace = receipt.get('transfer_trace') == 'v1'
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
            if args.game == 'hollow-knight':
                print('Original Hollow Knight: the pinned source has no game profile; porter will attempt an experimental port. Startup is unverified.', flush=True)
            work = Path(tempfile.mkdtemp(prefix='mk8-pr-test-', dir=game))
            print(f'Work folder: {work}', flush=True)
            repo = source(work, commit, repository, ordered=package != upstream_package)
            if transfer_trace:
                apply_transfer_trace(repo)
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
                if host_hash(apk, marker, transfer_trace) != receipt['host_sha256']:
                    raise ValueError('Installed runtime differs from this PR build; settings were not changed')
                if clip_receipt:
                    with zipfile.ZipFile(apk) as z:
                        if CLIP_MARKER not in z.read('lib/arm64-v8a/libdmhost.so'):
                            raise ValueError('Installed runtime lacks the clip-depth conversion; settings were not changed')
            configure(adb, work, cpu, gpu_readback=args.gpu_readback, package=package, label=label, system_driver=system_driver, transfer_trace=transfer_trace)
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
        sha = host_hash(apk, marker, transfer_trace)
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
            'transfer_trace': 'v1' if transfer_trace else None,
            'apk': str(apk), 'host_sha256': sha, 'device': serial, 'package': package}, indent=2) + '\n')
        subprocess.run([sys.executable, '-m', 'porter', 'install', str(data), '--apk', str(apk),
                        '--device', serial], cwd=repo, check=True)
        configure(adb, work, cpu, previous, args.gpu_readback, package=package, label=label, system_driver=system_driver, transfer_trace=transfer_trace)
        print('APK:', apk)
        print('Game:', manifest.get('name'), manifest.get('display'), 'title ID:', manifest['title_id'])
        print(f'Open {label}. It has separate saves and settings from the working app.')
        if transfer_trace:
            print('Transfer trace v1: source is patched only for this diagnostic build; these traces are not in PR #140.')
            print('Play the previously tested scene for at least 300 rendered frames, then collect logs with the same --game.')
            print('Look for BC transfer trace v1: summary and per-format record/replay outcomes. Counts can differ when command lists are reused or replay is asynchronous.')
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
