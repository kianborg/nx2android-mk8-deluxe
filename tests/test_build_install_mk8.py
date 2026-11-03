"""Check command ordering and phone settings handling without building or using ADB."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('mk8_builder',Path(__file__).resolve().parents[1]/'devtools/build_install_mk8.py')
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)


class FakeAdb:
    def __init__(self, events, previous):
        self.events=events;self.env=previous;self.staged=None
    def pick(self):
        self.events.append('pick');return 'phone-serial'
    def shell(self, command):
        if command.startswith('if [ -f '):return 'present' if self.env is not None else 'absent'
        self.events.append(command)
        if command.startswith('mv -f '):self.env=self.staged
        return ''
    def run(self, *parts):
        assert parts==('exec-out','cat',tool.REMOTE)
        return self.env
    def push_file(self, local, remote):
        self.events.append('push');self.staged=local.read_text()


class BuildInstallMk8(unittest.TestCase):
    def test_settings_preserve_existing_choices_and_replace_switches_once(self):
        previous='# phone\r\nDM_LANG=fr\r\nDM_VK_DRIVER=system\r\nDM_VK_BC_DECODE=0\r\nDM_VK_DRIVER=old\r\n'
        result=tool.enable_turnip('DM_LANG=en-US\nNEW_SETTING=1\n',previous)
        self.assertEqual(result,'# phone\nDM_LANG=fr\nNEW_SETTING=1\nDM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\n')
        self.assertEqual(tool.enable_turnip('DM_LANG=en-US\n',None),'DM_LANG=en-US\nDM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\n')

    def workflow(self, failure=None, previous='DM_LANG=fr\nDM_VK_DRIVER=system\n'):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'Game Folder';folder.mkdir()
            keys=root/'prod.keys';keys.touch();driver=root/'turnip driver.zip';driver.touch()
            data=folder/'MarioKart8Deluxe-data';data.mkdir()
            (data/'nx2a-data.json').write_text(json.dumps({'package':tool.PACKAGE}))
            pack='DM_LANG=en-US\nNEW_SETTING=1\n'
            (data/'env.txt').write_text(pack);(folder/'MarioKart8Deluxe.apk').touch()
            args=argparse.Namespace(game_folder=folder,keys=keys,driver=driver,jobs=2)
            events=[];adb=FakeAdb(events,previous);commands=[]
            def run(command, **options):
                self.assertTrue(options['check']);self.assertEqual(options['cwd'],root)
                self.assertEqual(command[:3],[sys.executable,'-m','porter'])
                commands.append(command);action=command[3];events.append(action)
                if action==failure:raise subprocess.CalledProcessError(1,command)
                if action=='install':adb.env=pack
            with patch.object(tool.subprocess,'run',side_effect=run):
                if failure:
                    with self.assertRaises(subprocess.CalledProcessError):tool.build_and_install(args,adb,repo=root)
                    self.assertNotIn('push',events)
                    self.assertEqual(adb.env,previous)
                    if failure=='port':self.assertEqual(len(commands),1)
                    return
                backup=tool.build_and_install(args,adb,repo=root)
            self.assertEqual(commands[0][commands[0].index('--jobs')+1],'2')
            self.assertIn(str(driver),commands[0]);self.assertIn('--experimental',commands[0])
            self.assertEqual(commands[1][-2:],['--device','phone-serial'])
            self.assertEqual([x for x in events if x in ('port','install','push')],['port','install','push'])
            self.assertIn('DM_VK_DRIVER=turnip\n',adb.env)
            self.assertIn('DM_VK_BC_DECODE=1\n',adb.env)
            self.assertIn('NEW_SETTING=1\n',adb.env)
            self.assertEqual((backup/'env-turnip.txt').read_text(),adb.env)
            if previous is not None:
                self.assertEqual((backup/'env-before.txt').read_text(),previous)
                self.assertIn('DM_LANG=fr\n',adb.env)
            else:self.assertIn('DM_LANG=en-US\n',adb.env)

    def test_build_install_enable_and_backup(self):self.workflow()
    def test_first_install_uses_pack_defaults(self):self.workflow(previous=None)
    def test_build_failure_stops_before_install_or_settings_changes(self):self.workflow(failure='port')
    def test_install_failure_stops_before_settings_changes(self):self.workflow(failure='install')

    def test_runtime_verification_reads_installed_apk_without_phone_mutations(self):
        import zipfile
        for has_fix in (False,True):
            with self.subTest(has_fix=has_fix), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);calls=[];pulled=[]
                class ReadOnlyAdb:
                    def pick(self):return 'phone-serial'
                    def shell(self, command):
                        calls.append(command)
                        if command!=f'pm path {tool.PACKAGE}':raise AssertionError('Unexpected phone command')
                        return 'package:/data/app/example/base.apk\n'
                    def run(self, *parts, **kw):
                        calls.append(parts)
                        if parts[:2]==('exec-out','cat'):
                            if parts[2]==tool.REMOTE:return 'DM_VK_DRIVER=turnip\n'
                            if parts[2]==tool.REMOTE.replace('/env.txt','/log.txt'):return 'current log\n'
                        if parts[:2]==('pull','/data/app/example/base.apk'):
                            path=Path(parts[2]);pulled.append(path)
                            with zipfile.ZipFile(path,'w') as z:
                                z.writestr('lib/arm64-v8a/libdmhost.so',b'host inactive colour attachment alias: slot' if has_fix else b'older host')
                                z.writestr('assets/private.bin',b'not to be included')
                            return ''
                        raise AssertionError('Unexpected phone command')
                with patch.object(tool.subprocess,'run',side_effect=AssertionError('No build/install allowed')):
                    archive=tool.verify_install(ReadOnlyAdb(),repo=root)
                with zipfile.ZipFile(archive) as z:
                    self.assertEqual(set(z.namelist()),{'log.txt','env.txt','runtime-check.json'})
                    report=json.loads(z.read('runtime-check.json'))
                self.assertEqual(report['installed_host']['alias_fix_marker_present'],has_fix)
                self.assertFalse(report['phone_changes'])
                self.assertFalse(report['alias_event_in_log'])
                self.assertIsNone(report['local_source_has_alias_helper'])
                self.assertEqual(len(report['installed_host']['sha256']),64)
                self.assertTrue(all(not path.exists() for path in pulled))
