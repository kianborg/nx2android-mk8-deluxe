"""Refuse unsupported diagnostic input before downloading or changing source."""
from pathlib import Path
import importlib.util
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('clip_builder', ROOT/'devtools/build_install_mk8_pr.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

class ClipExperiment(unittest.TestCase):
    def test_invalid_source_is_refused_before_asset_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp); android=repo/'nxnative/dm/android';android.mkdir(parents=True)
            (android/'gfx_vk_shader.c').write_text('unexpected source')
            with patch.object(helper.urllib.request, 'urlopen') as fetch:
                with self.assertRaisesRegex(ValueError,'source mismatch'):
                    helper.apply_clip_depth(repo)
                fetch.assert_not_called()
