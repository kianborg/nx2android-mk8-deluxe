#!/usr/bin/env python3
"""Schedule a bounded release-APK graphics capture, collect it, and restore env.txt."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import zipfile

PACKAGE = 'org.nx2a.t0100152000022000'
PREFIXES = ('DM_VK_PASSDUMP', 'DM_VK_TRACE_', 'DM_VK_SHOT', 'DM_VK_TEXDUMP', 'DM_VK_DRAW_PACKET')


def capture_env(original, frame, shadow_test='baseline'):
    text = original.decode('utf-8')
    rows = [row for row in text.splitlines()
            if not row.strip().split('=', 1)[0].startswith(PREFIXES)]
    if shadow_test == 'map-off':
        rows = [row for row in rows if row.strip().split('=', 1)[0] != 'DM_VK_X_SKIPVS']
        rows.append('DM_VK_X_SKIPVS=b2cfa260c7494f18')
    if shadow_test == 'uniforms':
        if any(row.strip().startswith('DM_VK_X_SKIPVS=') and row.split('=',1)[1].strip() for row in rows):
            raise ValueError('Restore the map-off experiment before capturing normal shadow inputs.')
        rows += ['DM_VK_DRAW_PACKET=b2cfa260c7494f18', f'DM_VK_DRAW_PACKET_AT={frame}',
                 'DM_VK_PASSDUMP_RGBA=1', 'DM_VK_TEXDUMP_SHADER=6aa6c36ed6065b7d', 'DM_VK_TEXDUMP_BINDING=2']
    frames = 16 if shadow_test in ('wheel-light', 'wheel-motion', 'wheel-inputs') else 1
    if shadow_test in ('wheel-light', 'wheel-motion', 'wheel-inputs'):
        if any(row.strip().startswith('DM_VK_X_SKIPVS=') and row.split('=',1)[1].strip() for row in rows):
            raise ValueError('Restore draw-skip experiments before the wheel capture.')
        if shadow_test in ('wheel-motion', 'wheel-inputs'):
            rows += ['DM_VK_PASSDUMP_VS=35696712904ac390', 'DM_VK_PASSDUMP_TARGET=all',
                     'DM_VK_PASSDUMP_UNIFORMS=1', 'DM_VK_PASSDUMP_RAW=1']
        else:
            rows += ['DM_VK_PASSDUMP_SIZE=480x270,640x360', 'DM_VK_PASSDUMP_FMT=122/122',
                     'DM_VK_PASSDUMP_DEPTH=0']
    if shadow_test == 'wheel-inputs':
        rows += ['DM_VK_PASSDUMP_INPUTS=6', 'DM_VK_DRAW_PACKET=35696712904ac390', f'DM_VK_DRAW_PACKET_AT={frame}']
    shots = list(range(frame, frame+frames+(2 if shadow_test in ('wheel-motion','wheel-inputs') else 0))) if frames>1 else [frame,frame+2]
    rows += [f'DM_VK_TRACE_AT={frame}', 'DM_VK_TRACE_FRAME=*',
             f'DM_VK_PASSDUMP={frame}', f'DM_VK_PASSDUMP_FRAMES={frames}',
             'DM_VK_SHOT='+','.join(map(str,shots))]
    return ('\n'.join(rows)+'\n').encode()


def pass_files(log, frame, frames=1):
    records = re.findall(r'pass dump (\d+) is the submission\'s pass (-?\d+) \(present (\d+)\)', log)
    if not records or not any(int(present) >= frame for _, _, present in records):
        raise ValueError('Capture has not reached the scheduled frame; keep the affected scene visible and retry collect.')
    if any(not frame <= int(present) <= frame+frames+7 for _, _, present in records):
        raise ValueError('Dump presents do not match this capture; keep log.txt for inspection.')
    if frames>1 and len({int(present) for _,_,present in records})<min(frames,8):
        raise ValueError('Not enough temporal pass frames have finished writing; keep the view open and retry collect.')
    completed = {int(i) for i in re.findall(r'pass dump (\d+): .* → ', log)}
    indices = {int(i) for i, _, _ in records}
    if not indices <= completed:
        raise ValueError('Pass files are still being written; retry collect shortly.')
    if 'frame trace begins at present ' not in log:
        raise ValueError('No frame trace found; keep the log for inspection.')
    files = [f'pass_{i:02d}.ppm' for i in sorted(indices)]
    depths = {int(i) for i in re.findall(r'pass dump (\d+): (?:depth |[^\n]*\bRG(?:16|32)F,)', log)}
    files += [f'pass_{i:02d}.ppm.f32' for i in sorted(indices & depths)]
    raw = {int(i) for i in re.findall(r'pass dump (\d+) raw RGBA8 → ', log)}
    files += [f'pass_{i:02d}.ppm.rgba8' for i in sorted(indices & raw)]
    packed = {int(i) for i in re.findall(r'pass dump (\d+) raw R11G11B10 → ', log)}
    files += [f'pass_{i:02d}.ppm.u32' for i in sorted(indices & packed)]
    inputs = {int(i) for i in re.findall(r'pass dump (\d+) raw format \d+ → ', log)}
    files += [f'pass_{i:02d}.ppm.raw' for i in sorted(indices & inputs)]
    return files


def motion_files(log, frame, frames):
    if 'shader-filter capture enabled: vertex 35696712904ac390' not in log:
        raise ValueError('The installed APK lacks the shader-filter capture. Rebuild with the new runtime; preserve this log.')
    files = pass_files(log, frame, frames)
    targets = {}
    packed = {int(i) for i in re.findall(r'pass dump (\d+) raw R11G11B10 → ', log)}
    for present, subpass, index, target in re.findall(
            r'pass capture: present (\d+) pass (\d+) dump (\d+) target (\d+) layer \d+', log):
        if int(index) in packed:
            targets.setdefault((int(present), int(subpass)), set()).add(int(target))
    depths = {int(i) for i in re.findall(r'pass dump (\d+): depth ', log)}
    complete = {int(present) for index, subpass, present in re.findall(
        r"pass dump (\d+) is the submission's pass (-?\d+) \(present (\d+)\)", log)
        if int(index) in depths and targets.get((int(present), int(subpass)), set()) >= {0, 1}}
    if len(complete) < min(frames, 8) or 'pass capture draw:' not in log or 'pass capture uniform:' not in log:
        raise ValueError('Incomplete motion capture: need both lighting targets, depth and light uniforms across frames. Preserve the log and retry collect.')
    return files


def input_files(log, frame, frames):
    files = motion_files(log, frame, frames)
    raw = {int(i) for i in re.findall(r'pass dump (\d+) raw format \d+ → ', log)}
    found = {}
    for present, index, binding, fmt in re.findall(
            r'pass capture input: present (\d+) pass \d+ dump (\d+) binding (\d+) format (\d+)', log):
        if int(index) in raw and ((int(binding), int(fmt)) in ((1,64),(2,76))):
            found.setdefault(int(present),set()).add(int(binding))
    if len([v for v in found.values() if v >= {1,2}]) < min(frames,8):
        raise ValueError('Missing normal/linear-depth inputs. Rebuild the updated APK and preserve this log.')
    return files


def packet_files(manifest, frame, wheel=False):
    if (not manifest.get('complete') or not frame <= manifest.get('present', -1) <= frame+8
            or manifest.get('vertex_shader') != ('35696712904ac390' if wheel else 'b2cfa260c7494f18')
            or manifest.get('fragment_shader') not in (('0722cc0403877a4e','30b45cd2223d3964') if wheel else ('6aa6c36ed6065b7d',))):
        raise ValueError('Shadow packet is incomplete, mistimed or targets the wrong shaders; keep the log for inspection.')
    rows = manifest.get('streams', [])+manifest.get('uniforms', [])
    if len(rows)>64 or not any(row.get('stage')==1 and row.get('binding')==4 for row in manifest.get('uniforms', [])):
        raise ValueError('Missing fragment uniforms: rebuild the APK with the extended packet capture.')
    files = ['draw_packet.json', 'draw_packet_indices.bin']
    for row in rows:
        name=row.get('file','')
        if not row.get('saved') or not 0<row.get('size',0)<=1024*1024 or not re.fullmatch(r'draw_packet_[a-z_0-9]+\.bin',name):
            raise ValueError('Invalid or missing packet blob.')
        files.append(name)
    return list(dict.fromkeys(files))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['start', 'collect', 'restore'])
    ap.add_argument('--scene', choices=['menu', 'shadows'], default='menu')
    ap.add_argument('--shadow-test', choices=['baseline', 'map-off', 'uniforms', 'wheel-light', 'wheel-motion', 'wheel-inputs'], default='baseline',
                    help='uniforms captures normal shadow inputs (updated APK); map-off is the earlier inconclusive skip experiment')
    ap.add_argument('--output', type=Path)
    ap.add_argument('--frame', type=int, help='capture present (default: menu 6000, shadows 9000)')
    ap.add_argument('--adb', default='adb')
    ap.add_argument('--serial')
    args = ap.parse_args()
    if args.shadow_test != 'baseline' and args.scene != 'shadows':
        ap.error('--shadow-test requires --scene shadows')
    if args.frame is None:
        args.frame = 9000 if args.scene == 'shadows' else 6000
    if args.output is None:
        suffix = '' if args.shadow_test == 'baseline' else '-'+args.shadow_test
        args.output = Path(f'work/mk8-{args.scene}{suffix}-capture')
    if args.frame < 300:
        ap.error('--frame must be at least 300')
    adb = [args.adb] + (['-s', args.serial] if args.serial else [])
    root = f'/sdcard/Android/data/{PACKAGE}/files'
    out = args.output.resolve()

    def run(*parts):
        return subprocess.run(adb+list(parts), check=True, stdout=subprocess.PIPE).stdout

    def shell(*parts):
        return run('shell', shlex.join(parts))

    def restore():
        current = shell('cat', root+'/env.txt')
        # Android shell transports may normalize CRLF; compare normalized lines.
        if current.replace(b'\r\n', b'\n') != (out/'capture-env.txt').read_bytes().replace(b'\r\n', b'\n'):
            raise ValueError('env.txt changed after start; refusing to overwrite newer settings. Original is in env-before.txt.')
        shell('am', 'force-stop', PACKAGE)
        run('push', str(out/'env-before.txt'), root+'/env.txt')
        print('Original working settings restored. You can reopen the game.')

    if args.action == 'start':
        out.mkdir(parents=True, exist_ok=False)
        run('pull', root+'/env.txt', str(out/'env-before.txt'))
        original = (out/'env-before.txt').read_bytes()
        if b'DM_VK_DRIVER=turnip' not in original or b'DM_VK_BC_DECODE=1' not in original:
            raise ValueError('Expected working Turnip and CPU BC settings; nothing on the phone was changed.')
        settings = capture_env(original, args.frame, args.shadow_test)
        (out/'capture-env.txt').write_bytes(settings)
        before = shell('cat', root+'/log.txt')
        (out/'capture.json').write_text(json.dumps({'frame': args.frame,
            'scene': args.scene, 'shadow_test': args.shadow_test, 'capture_frames': 16 if args.shadow_test in ('wheel-light','wheel-motion','wheel-inputs') else 1, 'previous_log_sha256': hashlib.sha256(before).hexdigest()}, indent=2)+'\n')
        shell('am', 'force-stop', PACKAGE)
        run('push', str(out/'capture-env.txt'), root+'/env.txt')
        print(f'Capture armed for present {args.frame}. Open the game manually now.')
        if args.scene == 'shadows':
            if args.shadow_test == 'map-off':
                print('DIAGNOSTIC: the shadow-map resolve draw is disabled. This is not a permanent fix.')
            if args.shadow_test == 'uniforms':
                print('Capturing normal shadow inputs, including vertex/fragment uniforms and mask RGBA. Requires updated APK.')
            if args.shadow_test == 'wheel-light':
                print('Capturing 16 consecutive lighting/output frames; keep the kart and camera still.')
            print('Choose Time Trials, Mario Kart Stadium. Drive onto the banked antigravity section.')
            if args.shadow_test in ('wheel-motion', 'wheel-inputs'):
                print('Requires the updated APK. Near capture time, repeatedly accelerate briefly and release/brake in antigravity.')
                print('Keep doing this through the capture window; keep the race view open without pausing.')
            else:
                print('Stop where the affected illumination is visible; keep the race view open without pausing.')
            print('The default delay is 5 minutes at 30 FPS, 3.75 minutes at 40 FPS.')
            print('After about six minutes run collect with the same --scene/--shadow-test options; retry if not ready.')
        else:
            print('Go directly to cup selection, select Mushroom Cup and leave that screen open.')
            print('At 40 FPS the default delay is about 2.5 minutes; at 30 FPS about 3.3 minutes.')
            print('After about four minutes run collect. If it is not ready, collect will say so.')
    elif args.action == 'restore':
        restore()
    else:
        meta = json.loads((out/'capture.json').read_text())
        log = shell('cat', root+'/log.txt')
        (out/'log.txt').write_bytes(log)
        if hashlib.sha256(log).hexdigest() == meta['previous_log_sha256']:
            raise ValueError('The game has not produced a new log since start.')
        count = meta.get('capture_frames', 1)
        mode = meta.get('shadow_test')
        reader = input_files if mode=='wheel-inputs' else motion_files if mode=='wheel-motion' else pass_files
        files = reader(log.decode('utf-8', errors='replace'), meta['frame'], count)
        for name in files:
            run('pull', root+'/'+name, str(out/name))
        extra_shots = 2 if meta.get('shadow_test') in ('wheel-motion','wheel-inputs') else 0
        shots = range(meta['frame'], meta['frame']+count+extra_shots) if count>1 else (meta['frame'], meta['frame']+2)
        for frame in shots:
            name = f'frame_{frame:06d}.ppm'
            run('pull', root+'/'+name, str(out/name))
            files.append(name)
        if meta.get('shadow_test') in ('uniforms','wheel-inputs'):
            run('pull', root+'/draw_packet.json', str(out/'draw_packet.json'))
            extra = packet_files(json.loads((out/'draw_packet.json').read_text()), meta['frame'], wheel=mode=='wheel-inputs')
            for name in extra:
                if name != 'draw_packet.json':
                    run('pull', root+'/'+name, str(out/name))
            files += extra
            # The full pass archive can exceed upload limits. Once the pass
            # files have already been sent, this small ZIP supplies just the
            # missing CPU packet, plus trace metadata tying it to the capture.
            inputs = out/('mk8-wheel-mesh.zip' if mode=='wheel-inputs' else 'mk8-shadow-inputs.zip')
            with zipfile.ZipFile(inputs, 'x', zipfile.ZIP_DEFLATED) as z:
                for name in extra+['log.txt', 'capture.json']:
                    z.write(out/name, name)
            print(f'Small shadow-input archive: {inputs}')
        (out/'screen.png').write_bytes(run('exec-out', 'screencap', '-p'))
        variant = '' if meta.get('shadow_test', 'baseline') == 'baseline' else '-'+meta['shadow_test']
        archive_path = out/f"mk8-{meta.get('scene', 'menu')}{variant}-diagnostics.zip"
        with zipfile.ZipFile(archive_path, 'x', zipfile.ZIP_DEFLATED) as z:
            for name in files+['log.txt', 'screen.png', 'capture.json', 'capture-env.txt']:
                z.write(out/name, name)
        print(f'Capture saved: {archive_path}')
        restore()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        raise SystemExit(f'Error: {e}\nIf settings were armed, use the restore action with the same --output directory.')
