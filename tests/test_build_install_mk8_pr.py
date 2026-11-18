"""Verify the isolated-PR install and settings workflow without a phone."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pr_builder', ROOT / 'devtools/build_install_mk8_pr.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def apk(path, host=tool.MARKER):
    if tool.MARKER in host and tool.SUCCESS_MARKER not in host:
        host += tool.SUCCESS_MARKER
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('lib/arm64-v8a/libdmhost.so', host)


class Phone:
    def __init__(self):
        self.env = 'DM_LANG=en-US\nDM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\n'
        self.calls = []
        self.host = tool.MARKER

    def pick(self):
        return 'phone'

    def shell(self, command):
        self.calls.append(command)
        if command.startswith('if '):
            return 'yes'
        if command.startswith('pm path '):
            return 'package:/data/app/base.apk\n'
        if command.startswith('mv '):
            self.env = self.pending
        return ''

    def run(self, *args, **kwargs):
        self.calls.append(args)
        if args[:2] == ('exec-out', 'cat'):
            return self.env
        if args[0] == 'pull':
            apk(Path(args[2]), self.host)
            return ''
        raise AssertionError(args)

    def push_file(self, local, remote):
        self.calls.append(('push', str(local), remote))
        self.pending = local.read_text()


class PRBuilder(unittest.TestCase):
    def test_native_app_install_and_identity(self):
        self.exercise_app(False)

    def test_cpu_app_install_and_identity(self):
        self.exercise_app(True)

    def test_upstream_cpu_baseline_install_and_identity(self):
        self.exercise_app(True, baseline=True)

    def test_lenovo_system_driver_and_automatic_bc(self):
        self.exercise_app(True, lenovo=True)

    def test_lenovo_upstream_baseline(self):
        self.exercise_app(True, baseline=True, lenovo=True)

    def test_clip_pr_identity_and_readback_off(self):
        self.exercise_app(True, lenovo=True, clip=True)

    def test_clip_baseline_identity_and_readback_off(self):
        self.exercise_app(True, baseline=True, lenovo=True, clip=True)

    def test_odyssey_pr_app(self):
        self.exercise_app(True, game='odyssey')

    def test_odyssey_baseline_app(self):
        self.exercise_app(True, baseline=True, game='odyssey')

    def test_3dworld_pr_app(self):
        self.exercise_app(True, game='3dworld')

    def test_3dworld_baseline_app(self):
        self.exercise_app(True, baseline=True, game='3dworld')

    def test_wrong_game_folder_stops_before_install(self):
        self.exercise_app(True, game='odyssey', wrong_title=True)

    def exercise_app(self, cpu, baseline=False, lenovo=False, clip=False, game='mk8', wrong_title=False):
        force_cpu = cpu and not lenovo
        native_package, cpu_package, upstream_package, profiles = tool.profiles_for(game)
        package = upstream_package if baseline else cpu_package if cpu else native_package
        label, commit, repository, _, marker = profiles[package]
        if clip:
            package += '.clipdepth'
            label = 'MK8 Clip Base' if baseline else 'MK8 Clip PR'
            marker += tool.CLIP_MARKER
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game_folder = root / 'game'
            game_folder.mkdir()
            keys = root / 'keys'
            keys.write_text('not real keys')
            driver = root / 'driver.so'
            elf = bytearray(64)
            elf[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<HH', elf, 16, 3, 183)
            if not lenovo:
                driver.write_bytes(elf)
            working = game_folder / 'MarioKart8Deluxe.apk'
            working.write_bytes(b'working APK must remain')
            repo = root / 'isolated-source'
            repo.mkdir()
            phone = Phone()
            phone.host = marker
            commands = []

            def run(command, cwd, check):
                self.assertEqual(cwd, repo)
                self.assertEqual(command[:3], [sys.executable, '-m', 'porter'])
                self.assertNotIn('--replace-signer', command)
                commands.append(command)
                if command[3] == 'port':
                    self.assertEqual(command[command.index('--package') + 1], package)
                    self.assertEqual(command[command.index('--app-name') + 1], label)
                    if lenovo:
                        self.assertNotIn('--vulkan-driver', command)
                    else:
                        library = Path(command[command.index('--vulkan-driver') + 1])
                        self.assertEqual(library.name, tool.DRIVER)
                    out = Path(command[command.index('-o') + 1])
                    data = out / 'MarioKart8Deluxe-data'
                    data.mkdir(parents=True)
                    (data / 'nx2a-data.json').write_text(json.dumps({'package': package, 'title_id': tool.GAMES['mk8' if wrong_title else game][0]}))
                    apk(out / 'MarioKart8Deluxe.apk', marker)
                else:
                    self.assertEqual(command[3], 'install')
                    phone.env = 'DM_VK_DRIVER=libmk8_pr_turnip.so\nNEW_DEFAULT=1\n'

            arguments = ['helper', '--game', game, '--game-folder', str(game_folder), '--keys', str(keys), '--driver', str(driver)]
            if cpu:
                arguments.append('--cpu-bc')
            if clip:
                arguments.append('--clip-depth-test')
            if lenovo:
                arguments.append('--lenovo')
            if baseline:
                arguments.append('--upstream-baseline')
            old_path = list(sys.path)
            try:
                with patch.object(tool, 'source', return_value=repo) as source, \
                     patch.object(tool, 'dependencies'), \
                     patch.object(tool, 'apply_clip_depth') as clip_patch, \
                     patch.object(tool.subprocess, 'run', side_effect=run), \
                     patch('porter.adb.Adb', return_value=phone), \
                     patch('porter.config.load', return_value={}), \
                     patch('porter.toolchain.find_adb', return_value='adb'):
                    with patch.object(sys, 'argv', arguments):
                        if wrong_title:
                            before = phone.env
                            with self.assertRaises(SystemExit):
                                tool.main()
                            self.assertEqual(len(commands), 1)
                            self.assertEqual(phone.env, before)
                            self.assertFalse(phone.calls)
                            return
                        tool.main()
                    work = next(game_folder.glob('mk8-pr-test-*'))
                    source.assert_called_once_with(work, commit, repository, ordered=not baseline)
                    self.assertIn(f'DM_VK_X_BC_CPU={int(force_cpu)}', phone.env)
                    self.assertIn('DM_VK_X_BC_GPU_READBACK=0', phone.env)
                    self.assertIn('DM_LANG=en-US', phone.env)
                    self.assertIn('NEW_DEFAULT=1', phone.env)
                    self.assertNotIn('DM_VK_DRIVER=turnip', phone.env)
                    self.assertEqual((work / 'env-before-install.txt').read_text().splitlines()[-1], 'DM_VK_BC_DECODE=1')
                    self.assertEqual(working.read_bytes(), b'working APK must remain')
                    if clip:
                        clip_patch.assert_called_once_with(repo)
                        receipt = json.loads((work / 'build.json').read_text())
                        self.assertEqual(receipt['package'], package)
                        self.assertTrue(receipt['clip_depth_test'])
                        self.assertFalse(receipt['force_cpu'])
                        self.assertTrue(receipt['system_driver'])
                        self.assertNotIn('DM_VK_DRIVER=', phone.env)
                        if baseline:
                            before = phone.env
                            with patch.object(sys, 'argv', ['helper', '--game', game, '--configure-only', str(work), '--gpu-readback']):
                                with self.assertRaises(SystemExit):
                                    tool.main()
                            self.assertEqual(phone.env, before)
                        else:
                            with patch.object(sys, 'argv', ['helper', '--game', game, '--configure-only', str(work), '--gpu-readback']):
                                tool.main()
                            self.assertIn('DM_VK_X_BC_GPU_READBACK=1', phone.env)
                            self.assertIn('DM_VK_X_BC_CPU=0', phone.env)
                            self.assertNotIn('DM_VK_DRIVER=', phone.env)
                            with patch.object(sys, 'argv', ['helper', '--game', game, '--configure-only', str(work)]):
                                tool.main()
                            self.assertIn('DM_VK_X_BC_GPU_READBACK=0', phone.env)
                            phone.host = marker + b'changed runtime'
                            before = phone.env
                            with patch.object(sys, 'argv', ['helper', '--game', game, '--configure-only', str(work), '--gpu-readback']):
                                with self.assertRaises(SystemExit):
                                    tool.main()
                            self.assertEqual(phone.env, before)
                        self.assertEqual(len(commands), 2)
                        return
                    if not cpu:
                        with patch.object(sys, 'argv', ['helper', '--game', game, '--configure-only', str(work), '--cpu-bc']):
                            with self.assertRaises(SystemExit):
                                tool.main()
                    if baseline:
                        with patch.object(sys, 'argv', ['helper', '--game', game, '--configure-only', str(work), '--gpu-readback']):
                            with self.assertRaises(SystemExit):
                                tool.main()
                    readback = cpu and not baseline
                    options = ['--gpu-readback'] if readback else []
                    with patch.object(sys, 'argv', ['helper', '--game', game, '--configure-only', str(work), *options]):
                        tool.main()
                    self.assertIn(f'DM_VK_X_BC_CPU={int(force_cpu)}', phone.env)
                    self.assertIn(f'DM_VK_X_BC_GPU_READBACK={int(readback)}', phone.env)
                    if cpu:
                        with patch.object(sys, 'argv', ['helper', '--game', game, '--configure-only', str(work)]):
                            tool.main()
                        self.assertIn(f'DM_VK_X_BC_CPU={int(force_cpu)}', phone.env)
                        self.assertIn('DM_VK_X_BC_GPU_READBACK=0', phone.env)
                    receipt = json.loads((work / 'build.json').read_text())
                    self.assertEqual(receipt['package'], package)
                    self.assertEqual(receipt['commit'], commit)
                    self.assertEqual(receipt['force_cpu'], force_cpu)
                    self.assertEqual(receipt['system_driver'], lenovo)
                    if lenovo:
                        self.assertNotIn('DM_VK_DRIVER=', phone.env)
                    else:
                        self.assertIn('DM_VK_DRIVER=' + tool.DRIVER, phone.env)
                    self.assertEqual(len(commands), 2)  # no rebuild/reinstall for mode switch
                    working_package = native_package.removesuffix('.prtest')
                    for call in phone.calls:
                        text = call if isinstance(call, str) else ' '.join(map(str, call))
                        self.assertNotIn(working_package + '/files', text)
                        for other_package in set(profiles) - {package}:
                            self.assertNotIn(other_package + '/files', text)
                            self.assertNotIn('force-stop ' + other_package + '\n', text + '\n')
                            self.assertNotIn('pm path ' + other_package + '\n', text + '\n')
                        if isinstance(call, tuple) and call[:2] == ('exec-out', 'cat'):
                            self.assertEqual(call[2], f'/sdcard/Android/data/{package}/files/env.txt')
                        self.assertNotIn('force-stop ' + working_package + '\n', text + '\n')
                        self.assertNotIn('pm path ' + working_package + '\n', text + '\n')
                    phone.host = marker + b'different host'
                    before = phone.env
                    with patch.object(sys, 'argv', ['helper', '--game', game, '--configure-only', str(work)]):
                        with self.assertRaises(SystemExit):
                            tool.main()
                    self.assertEqual(phone.env, before)
            finally:
                sys.path[:] = old_path

    def test_driver_archive_and_stale_apk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'driver.zip'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('driver.so', b'not ELF')
            with self.assertRaisesRegex(ValueError, 'ARM64'):
                tool.driver_library(path, root)
            with zipfile.ZipFile(path, 'a') as z:
                z.writestr('another.so', b'not ELF')
            with self.assertRaisesRegex(ValueError, 'one .so'):
                tool.driver_library(path, root)
            apk(root / 'old.apk', b'old host')
            with self.assertRaisesRegex(ValueError, 'lacks'):
                tool.host_hash(root / 'old.apk')

    def test_old_receipt_is_refused_before_phone_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / 'build.json').write_text(json.dumps({'source': '/old/source',
                'package': 'org.nx2a.t0100152000022000'}))
            with patch.object(tool, 'dependencies'), patch('porter.adb.Adb') as adb, \
                 patch.object(sys, 'argv', ['helper', '--configure-only', str(work)]):
                with self.assertRaises(SystemExit):
                    tool.main()
                adb.assert_not_called()

    def test_missing_lz4_gives_same_interpreter_fix(self):
        real = tool.importlib.import_module

        def load(name):
            if name == 'lz4.block':
                raise ModuleNotFoundError('lz4')
            return real(name)

        with patch.object(tool.importlib, 'import_module', side_effect=load):
            with self.assertRaises(ValueError) as caught:
                tool.dependencies()
        self.assertIn(sys.executable, str(caught.exception))
        self.assertIn('-m pip install lz4', str(caught.exception))
