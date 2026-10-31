import sys
from pathlib import Path
import struct
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'devtools'))
from extract_device_shaders import selected_entries, ENTRY


class DeviceShaders(unittest.TestCase):
    def test_selects_only_traced_ranges_and_rejects_bad_boundaries(self):
        header = struct.pack('<4sII', b'DMSV', 1, 2)
        table = ENTRY.pack(1, 1, 100, 24, 124, 8, 0)+ENTRY.pack(2, 0, 132, 20, 152, 4, 0)
        self.assertEqual(selected_entries(header, table, 156, {2}), [(132, 20), (152, 4)])
        for size, keys in ((150, {2}), (156, {3})):
            with self.assertRaises(ValueError):
                selected_entries(header, table, size, keys)
        malformed = ENTRY.pack(1, 1, 0, 24, 124, 8, 0)+table[ENTRY.size:]
        with self.assertRaises(ValueError):
            selected_entries(header, malformed, 156, {1})

    def test_rejects_duplicate_selected_keys(self):
        header = struct.pack('<4sII', b'DMSV', 1, 2)
        row = ENTRY.pack(1, 1, 100, 24, 124, 8, 0)
        with self.assertRaises(ValueError):
            selected_entries(header, row+row, 156, {1})

    def test_adb_range_extraction_produces_only_requested_shader(self):
        import io
        import shlex
        import subprocess
        import tempfile
        import zipfile
        from unittest.mock import patch
        import extract_device_shaders as tool
        header = struct.pack('<4sII', b'DMSV', 1, 2)
        table = ENTRY.pack(1, 1, 100, 20, 120, 4, 0)+ENTRY.pack(2, 0, 124, 20, 144, 4, 0)
        blob = bytearray(148)
        blob[:12] = header
        blob[12:12+len(table)] = table
        blob[100:104] = blob[124:128] = b'\x03\x02\x23\x07'
        blob[120:124] = b'ONE!'
        blob[144:148] = b'TWO!'

        def adb(command, **kwargs):
            parts = shlex.split(command[-1])
            if parts[0] == 'stat':
                data = b'148\n'
            else:
                self.assertEqual(parts[0], 'dd')
                options = dict(p.split('=', 1) for p in parts[1:])
                start = int(options['skip'])*4096
                data = bytes(blob[start:start+int(options['count'])*4096])
            return subprocess.CompletedProcess(command, 0, stdout=data, stderr=b'')

        with tempfile.TemporaryDirectory() as folder:
            trace = Path(folder)/'log.txt'
            trace.write_text('draw: shaders 0000000000000002 0000000000000000 0000000000000000\n')
            output = Path(folder)/'shaders.zip'
            with patch.object(sys, 'argv', ['extract_device_shaders.py', '--trace', str(trace), '--output', str(output)]), \
                    patch.object(tool.subprocess, 'run', side_effect=adb), patch('sys.stdout', new_callable=io.StringIO):
                tool.main()
            with zipfile.ZipFile(output) as z:
                self.assertEqual(set(z.namelist()), {'0000000000000002.spv', '0000000000000002.reflection.bin', 'manifest.json'})
                self.assertEqual(z.read('0000000000000002.reflection.bin'), b'TWO!')
