"""Check collection selects each game without changing device state."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bc_collector', ROOT/'devtools/collect_mk8_bc_logs.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

class GameCollector(unittest.TestCase):
    def test_trace_counts_use_latest_summary_and_maximum_sample(self):
        log = '''BC transfer trace v1: summary recorded=0 recorded_bc=0 replayed=0 replayed_bc=0 cpu_uploads=0 native_uploads=0 skips=0
BC transfer trace v1: replay b2t format=0x49 outcome=entry count=1
BC transfer trace v1: replay b2t format=0x49 outcome=entry count=2
BC transfer trace v1: replay b2t format=0x49 outcome=entry count=4
BC transfer trace v1: replay b2t format=0x49 outcome=invalid-region count=1
BC transfer trace v1: summary recorded=2 recorded_bc=2 replayed=4 replayed_bc=4 cpu_uploads=3 native_uploads=0 skips=1
'''
        result = collector.transfer_trace(log)
        self.assertEqual(result['summary_samples'], 2)
        self.assertEqual(result['latest_summary']['replayed'], 4)
        self.assertEqual(result['sampled_replay_outcome_counts']['0x49/entry'], 4)
        self.assertEqual(result['sampled_replay_outcome_counts']['0x49/invalid-region'], 1)

    def test_missing_trace_is_not_reported_as_zero_requests(self):
        result = collector.transfer_trace('BC CPU buffer upload: NVN format 0x49\n')
        self.assertIsNone(result['latest_summary'])
        self.assertEqual(result['summary_samples'], 0)

    def test_active_zero_trace_is_reported(self):
        result = collector.transfer_trace('BC transfer trace v1: summary recorded=0 recorded_bc=0 replayed=0 replayed_bc=0 cpu_uploads=0 native_uploads=0 skips=0\n')
        self.assertEqual(result['latest_summary']['recorded_bc'], 0)

    def test_other_game_prefixes_and_version_metadata(self):
        for game in ('odyssey', '3dworld'):
            with self.subTest(game=game), tempfile.TemporaryDirectory() as tmp:
                prefix=collector.GAME_PREFIXES[game]; package=prefix+'.prtest.cpubc'; calls=[]
                def run(command, **kwargs):
                    a=command[1:];calls.append(a);code=0;out=b'';err=b''
                    if a[:4]==['shell','pm','list','packages']:
                        self.assertEqual(a[4],prefix);out=('package:'+package+'\n').encode()
                    elif a[:2]==['shell','getprop']:out=b'test\n'
                    elif a[:3]==['shell','ls','-la']:self.assertIn(package,a[3]);out=b'log.txt env.txt nx2a-data.json'
                    elif a[:2]==['exec-out','cat']:
                        self.assertTrue(a[2].startswith('/sdcard/Android/data/'+package+'/files/'))
                        if a[2].endswith('/nx2a-data.json'):out=json.dumps({'title_id':prefix.removeprefix('org.nx2a.t').upper(),'display':'1.4.1' if game=='odyssey' else '1.2.2'}).encode()
                        elif a[2].endswith('/log.txt'):out=b'BC CPU buffer upload: NVN format 0x49, 4x4x1, GPU readback no\n'
                        else:code=1;err=b'No such file'
                    elif a[:2]==['shell','pidof'] or a[:3]==['shell','pm','path']:code=1
                    else:raise AssertionError(a)
                    return SimpleNamespace(returncode=code,stdout=out,stderr=err)
                with patch.object(collector.subprocess,'run',side_effect=run):
                    collector.collect(['adb'],Path(tmp),prefix)
                metadata=json.loads((Path(tmp)/package/'nx2a-data.json').read_text())
                self.assertEqual(metadata['title_id'],prefix.removeprefix('org.nx2a.t').upper())
                self.assertIn('BC CPU buffer upload:',(Path(tmp)/package/'log.txt').read_text())
                self.assertFalse(any('push' in c or 'install' in c or 'force-stop' in c for c in calls))
