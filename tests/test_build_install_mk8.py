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
