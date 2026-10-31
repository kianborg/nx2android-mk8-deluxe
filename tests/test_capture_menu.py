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


    def test_shadow_map_comparison_changes_only_skip_setting_and_capture_keys(self):
        original = (b'DM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\n'
                    b'DM_VK_X_SKIPVS=old\nDM_LANG=en-US\n')
        result = capture.capture_env(original, 9000, 'map-off')
        self.assertIn(b'DM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\n', result)
        self.assertIn(b'DM_LANG=en-US\n', result)
        self.assertEqual(result.count(b'DM_VK_X_SKIPVS='), 1)
        self.assertIn(b'DM_VK_X_SKIPVS=b2cfa260c7494f18\n', result)
        self.assertIn(b'DM_VK_PASSDUMP=9000\n', result)
        self.assertIn(b'DM_VK_X_SKIPVS=old\n', capture.capture_env(original, 9000))

    def test_uniform_capture_includes_sampled_float_texture_and_rgba_sidecars(self):
        log = ("frame trace begins at present 9000\n"
               "pass dump 01 is the submission's pass -100 (present 9000)\n"
               "pass dump 01: 2048x2048 RG32F, values 0 .. 1, nonzero texels 1 → /files/pass_01.ppm\n"
               "pass dump 02 is the submission's pass 16 (present 9000)\n"
               "pass dump 02 raw RGBA8 → /files/pass_02.ppm.rgba8\n"
               "pass dump 02: 960x540 format 37 → /files/pass_02.ppm\n")
        self.assertEqual(capture.pass_files(log, 9000),
                         ['pass_01.ppm', 'pass_02.ppm', 'pass_01.ppm.f32', 'pass_02.ppm.rgba8'])
        env = capture.capture_env(b'DM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\n', 9000, 'uniforms')
        self.assertIn(b'DM_VK_DRAW_PACKET_AT=9000\n', env)
        self.assertNotIn(b'DM_VK_X_SKIPVS', env)

    def test_packet_collection_requires_fragment_inputs_and_safe_filenames(self):
        packet = {'complete': True, 'present': 9000, 'vertex_shader': 'b2cfa260c7494f18',
                  'fragment_shader': '6aa6c36ed6065b7d', 'streams': [],
                  'uniforms': [{'stage': 1, 'binding': 4, 'register': 0, 'saved': True, 'size': 608,
                                'file': 'draw_packet_fragment_uniform_00.bin'}]}
        self.assertIn('draw_packet_fragment_uniform_00.bin', capture.packet_files(packet, 9000))
        packet['uniforms'][0]['file'] = '../outside.bin'
        with self.assertRaises(ValueError):
            capture.packet_files(packet, 9000)
        packet['uniforms'] = []
        with self.assertRaises(ValueError):
            capture.packet_files(packet, 9000)


    def test_actual_resolve_packet_uses_fragment_binding_four_register_zero(self):
        packet = {'complete': True, 'present': 9000, 'vertex_shader': 'b2cfa260c7494f18',
                  'fragment_shader': '6aa6c36ed6065b7d', 'streams': [
                      {'saved': True, 'size': 128, 'file': 'draw_packet_stream_00.bin'}],
                  'uniforms': [
                      {'stage': 0, 'binding': 1, 'register': 0, 'size': 608, 'saved': True, 'file': 'draw_packet_uniform_00.bin'},
                      {'stage': 1, 'binding': 4, 'register': 0, 'size': 608, 'saved': True, 'file': 'draw_packet_fragment_uniform_00.bin'}]}
        self.assertEqual(capture.packet_files(packet, 9000), ['draw_packet.json', 'draw_packet_indices.bin',
                         'draw_packet_stream_00.bin', 'draw_packet_uniform_00.bin', 'draw_packet_fragment_uniform_00.bin'])
        packet['uniforms'][1]['binding'] = 3
        with self.assertRaises(ValueError):
            capture.packet_files(packet, 9000)


    def test_wheel_capture_keeps_consecutive_frames_and_does_not_change_depth_workaround(self):
        env=capture.capture_env(b'DM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\nDM_VK_FDZ=1\n',9000,'wheel-light')
        self.assertIn(b'DM_VK_FDZ=1\n',env)
        self.assertIn(b'DM_VK_PASSDUMP_FRAMES=16\n',env)
        self.assertIn(b'DM_VK_PASSDUMP_SIZE=480x270,640x360\n',env)
        shots=next(line for line in env.decode().splitlines() if line.startswith('DM_VK_SHOT='))
        self.assertEqual(shots.split('=',1)[1].split(','),list(map(str,range(9000,9016))))
        log='frame trace begins at present 9000\n'+''.join(
            f"pass dump {i:02d} is the submission's pass 17 (present {9000+i})\n"
            f"pass dump {i:02d}: 480x270 format 122 → /files/pass_{i:02d}.ppm\n" for i in range(16))
        self.assertEqual(len(capture.pass_files(log,9000,16)),16)
        with self.assertRaises(ValueError):capture.pass_files(log,9000)
        with self.assertRaises(ValueError):capture.pass_files(log.split('pass dump 07')[0],9000,16)
