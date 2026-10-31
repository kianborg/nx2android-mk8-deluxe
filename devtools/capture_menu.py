#!/usr/bin/env python3
"""Schedule a bounded release-APK menu capture, collect it, and restore env.txt."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import zipfile

PACKAGE = 'org.nx2a.t0100152000022000'
PREFIXES = ('DM_VK_PASSDUMP', 'DM_VK_TRACE_', 'DM_VK_SHOT', 'DM_VK_TEXDUMP')


def capture_env(original, frame):
    text = original.decode('utf-8')
    rows = [row for row in text.splitlines()
            if not row.strip().split('=', 1)[0].startswith(PREFIXES)]
    rows += [f'DM_VK_TRACE_AT={frame}', 'DM_VK_TRACE_FRAME=*',
             f'DM_VK_PASSDUMP={frame}', 'DM_VK_PASSDUMP_FRAMES=1',
             f'DM_VK_SHOT={frame},{frame+2}']
    return ('\n'.join(rows)+'\n').encode()


def pass_files(log, frame):
    records = re.findall(r'pass dump (\d+) is the submission\'s pass (\d+) \(present (\d+)\)', log)
    if not records or not any(int(present) >= frame for _, _, present in records):
        raise ValueError('Capture has not reached the scheduled frame; leave the menu open and retry collect.')
    if any(not frame <= int(present) <= frame+8 for _, _, present in records):
        raise ValueError('Dump presents do not match this capture; keep log.txt for inspection.')
    completed = {int(i) for i in re.findall(r'pass dump (\d+): .* → ', log)}
    indices = {int(i) for i, _, _ in records}
    if not indices <= completed:
        raise ValueError('Pass files are still being written; retry collect shortly.')
    if 'frame trace begins at present ' not in log:
        raise ValueError('No frame trace found; keep the log for inspection.')
    return [f'pass_{i:02d}.ppm' for i in sorted(indices)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['start', 'collect', 'restore'])
    ap.add_argument('--output', type=Path, default=Path('work/mk8-menu-capture'))
    ap.add_argument('--frame', type=int, default=6000)
    ap.add_argument('--adb', default='adb')
    ap.add_argument('--serial')
    args = ap.parse_args()
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
        settings = capture_env(original, args.frame)
        (out/'capture-env.txt').write_bytes(settings)
        before = shell('cat', root+'/log.txt')
        (out/'capture.json').write_text(json.dumps({'frame': args.frame,
            'previous_log_sha256': hashlib.sha256(before).hexdigest()}, indent=2)+'\n')
        shell('am', 'force-stop', PACKAGE)
        run('push', str(out/'capture-env.txt'), root+'/env.txt')
        print(f'Capture armed for present {args.frame}. Open the game manually now.')
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
        files = pass_files(log.decode('utf-8', errors='replace'), meta['frame'])
        for name in files:
            run('pull', root+'/'+name, str(out/name))
        for frame in (meta['frame'], meta['frame']+2):
            name = f'frame_{frame:06d}.ppm'
            run('pull', root+'/'+name, str(out/name))
            files.append(name)
        (out/'screen.png').write_bytes(run('exec-out', 'screencap', '-p'))
        archive_path = out/'mk8-menu-diagnostics.zip'
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
