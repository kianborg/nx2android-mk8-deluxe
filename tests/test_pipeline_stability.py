import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('pipeline_stability', Path(__file__).resolve().parents[1]/'devtools/pipeline_stability.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class PipelineStability(unittest.TestCase):
    def test_preserves_driver_and_other_settings_without_duplicate_switches(self):
        original = (b'# settings\r\nDM_VK_DRIVER=turnip\r\nDM_VK_BC_DECODE=1\r\nDM_LANG=en-US\r\n'
                    b'DM_VK_ASYNC_PIPE=1\r\nDM_VK_NOPREWARM=0\r\n')
        updated = tool.sync_settings(original)
        self.assertEqual(updated.count(b'DM_VK_ASYNC_PIPE='), 1)
        self.assertEqual(updated.count(b'DM_VK_NOPREWARM='), 1)
        for line in (b'# settings\n', b'DM_VK_DRIVER=turnip\n', b'DM_VK_BC_DECODE=1\n', b'DM_LANG=en-US\n',
                     b'DM_VK_ASYNC_PIPE=0\n', b'DM_VK_NOPREWARM=1\n'):
            self.assertIn(line, updated)

    def test_refuses_wrong_driver_and_active_shadow_experiment(self):
        for original in (b'DM_VK_DRIVER=system\n',
                         b'DM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\nDM_VK_X_SKIPVS=b2cfa260c7494f18\n'):
            with self.assertRaises(ValueError):
                tool.sync_settings(original)


    def test_wheel_depth_comparison_changes_only_the_depth_workaround(self):
        original = (b'DM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\nDM_LANG=en-US\n'
                    b'DM_VK_ASYNC_PIPE=0\nDM_VK_NOPREWARM=1\nDM_VK_FDZ=1\n')
        updated = tool.comparison_settings(original, 'wheel-depth')
        self.assertEqual(updated, original.replace(b'DM_VK_FDZ=1', b'DM_VK_FDZ=0'))
        self.assertEqual(updated.count(b'DM_VK_FDZ='), 1)
        self.assertNotIn(b'DM_VK_X_SKIPVS', updated)

    def test_unknown_comparison_is_rejected(self):
        with self.assertRaises(ValueError):
            tool.comparison_settings(b'DM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\n', 'unknown')

    def test_wheel_submission_comparison_preserves_depth_and_pipeline_settings(self):
        original = (b'DM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\nDM_VK_FDZ=1\n'
                    b'DM_VK_ASYNC_PIPE=1\nDM_VK_NOPREWARM=0\nDM_VK_CB_DRAWS=128\n')
        updated = tool.comparison_settings(original, 'wheel-submit')
        self.assertEqual(updated, original.replace(b'DM_VK_CB_DRAWS=128', b'DM_VK_CB_DRAWS=0'))
        self.assertEqual(updated.count(b'DM_VK_CB_DRAWS='), 1)
