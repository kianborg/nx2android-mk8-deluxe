import importlib.util
from pathlib import Path
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('shader_jobs', ROOT / 'nxnative/dm/android/tools/shader_jobs.py')
shader_jobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shader_jobs)


class ShaderJobsTests(unittest.TestCase):
    def run_translator(self, source, jobs, **kwargs):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'translator.py'
            script.write_text('import json, sys, time\njobs = json.load(open(sys.argv[1]))\n' + source,
                              encoding='utf-8')
            messages = []
            outputs = shader_jobs.translate(jobs, [sys.executable, script], folder, workers=2,
                                             report=messages.append, **kwargs)
            return outputs, messages

    def test_multiple_batches_and_progress(self):
        outputs, messages = self.run_translator(
            'print(f"translated: {len(jobs)} ok, 0 failed")\n',
            {str(i): {'key': str(i)} for i in range(5)}, batch_size=2)
        self.assertEqual(len(outputs), 3)
        self.assertIn('5/5 processed, 5 translated', messages[-1])

    def test_shader_errors_are_reported_without_mistaking_them_for_crashes(self):
        outputs, messages = self.run_translator(
            'print("[RED] deadbeef: unsupported instruction")\n'
            'print("translated: 0 ok, 1 failed")\nsys.exit(1)\n', {'deadbeef': {}})
        self.assertIn('unsupported instruction', outputs[0])
        self.assertIn('1/1 processed, 0 translated', messages[-1])

    def test_crash_preserves_diagnostic(self):
        with self.assertRaisesRegex(RuntimeError, 'exited 7.*complete result') as error:
            self.run_translator('print("runtime failed")\nsys.exit(7)\n', {'badshader': {}})
        self.assertIn('badshader', str(error.exception))
        self.assertIn('runtime failed', str(error.exception))

    def test_truncated_batch_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'without a complete result'):
            self.run_translator('print("translated: 1 ok, 0 failed")\n', {'a': {}, 'b': {}})

    def test_timeout_stops_other_active_batches(self):
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, 'timed out.*') as error:
            self.run_translator('time.sleep(30)\n', {'slow-a': {}, 'slow-b': {}},
                                timeout=0.3, batch_size=1)
        self.assertLess(time.monotonic() - started, 5)
        self.assertIn('NX2A_SHADER_TIMEOUT', str(error.exception))

    def test_empty_selection_and_invalid_workers(self):
        with self.assertRaisesRegex(RuntimeError, 'no shaders selected'):
            self.run_translator('', {})
        with self.assertRaises(ValueError):
            shader_jobs.translate({'a': {}}, [], '.', workers=0)
