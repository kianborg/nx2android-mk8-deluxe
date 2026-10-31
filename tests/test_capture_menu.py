import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('capture_menu', Path(__file__).resolve().parents[1]/'devtools/capture_menu.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class MenuCaptureTests(unittest.TestCase):
    def test_preserves_working_driver_and_replaces_old_capture_filters(self):
        original = (b'DM_LANG=en-US\r\nDM_VK_DRIVER=turnip\r\nDM_VK_BC_DECODE=1\r\n'
                    b'DM_VK_PASSDUMP_PASS=70\r\nDM_VK_TRACE_SIZE=720x404\r\n')
        result = capture.capture_env(original, 6000)
        self.assertIn(b'DM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1', result)
        self.assertNotIn(b'DM_VK_PASSDUMP_PASS', result)
        self.assertNotIn(b'DM_VK_TRACE_SIZE', result)
        self.assertIn(b'DM_VK_SHOT=6000,6002', result)

    def test_collects_only_indices_written_in_current_log(self):
        log = ("frame trace begins at present 6000\n"
               "pass dump 00 is the submission's pass 12 (present 6001)\n"
               "pass dump 00: 1280x720 format 37 → /files/pass_00.ppm\n"
               "pass dump 02 is the submission's pass 14 (present 6001)\n"
               "pass dump 02: 1280x720 format 37 → /files/pass_02.ppm\n")
        self.assertEqual(capture.pass_files(log, 6000), ['pass_00.ppm', 'pass_02.ppm'])

    def test_rejects_incomplete_or_mistimed_capture(self):
        for log in ('', "pass dump 00 is the submission's pass 0 (present 6001)",
                    "pass dump 00 is the submission's pass 0 (present 7762)\n"
                    "pass dump 00: 1280x720 format 37 → /files/pass_00.ppm"):
            with self.subTest(log=log), self.assertRaises(ValueError):
                capture.pass_files(log, 6000)


    def test_collects_numeric_depth_only_for_completed_capture_indices(self):
        log = ("frame trace begins at present 9000\n"
               "pass dump 01 is the submission's pass 4 (present 9000)\n"
               "pass dump 01: depth 1536x1536 format 124, values 0 .. 1 → /files/pass_01.ppm\n"
               "pass dump 02 is the submission's pass 5 (present 9000)\n"
               "pass dump 02: 1280x720 format 37 → /files/pass_02.ppm\n")
        self.assertEqual(capture.pass_files(log, 9000),
                         ['pass_01.ppm', 'pass_02.ppm', 'pass_01.ppm.f32'])
