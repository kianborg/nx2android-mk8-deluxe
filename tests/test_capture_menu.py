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

    def test_motion_capture_uses_shader_instead_of_resolution_and_preserves_test_settings(self):
        original = b'DM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\nTU_DEBUG=nolrz\nDM_VK_CB_DRAWS=0\n'
        env = capture.capture_env(original, 9000, 'wheel-motion')
        self.assertTrue(env.startswith(original))
        self.assertNotIn(b'DM_VK_PASSDUMP_SIZE=', env)
        for row in (b'DM_VK_PASSDUMP_VS=35696712904ac390\n', b'DM_VK_PASSDUMP_TARGET=all\n',
                    b'DM_VK_PASSDUMP_UNIFORMS=1\n', b'DM_VK_PASSDUMP_RAW=1\n'):
            self.assertIn(row, env)
        shots = next(line for line in env.decode().splitlines() if line.startswith('DM_VK_SHOT='))
        self.assertEqual(shots.split('=', 1)[1].split(','), list(map(str, range(9000, 9018))))

    def test_motion_collection_requires_two_targets_depth_uniforms_and_updated_runtime(self):
        log = ('shader-filter capture enabled: vertex 35696712904ac390\n'
               'frame trace begins at present 9000\npass capture draw: present 9001\npass capture uniform: present 9001\n')
        for frame in range(8):
            for target in range(3):
                i = frame*3+target
                size = '482x271' if frame%2 else '640x360'
                log += f"pass dump {i:02d} is the submission's pass 18 (present {9001+frame})\n"
                if target == 0:
                    log += f'pass dump {i:02d}: depth {size} format 126, values 0 .. 1 → /files/pass_{i:02d}.ppm\n'
                else:
                    log += (f'pass capture: present {9001+frame} pass 18 dump {i:02d} target {target-1} layer {target-1}\n'
                            f'pass dump {i:02d}: {size} format 122 → /files/pass_{i:02d}.ppm\n'
                            f'pass dump {i:02d} raw R11G11B10 → /files/pass_{i:02d}.ppm.u32\n')
        files = capture.motion_files(log, 9000, 16)
        self.assertEqual(len(files), 48)  # 24 previews, 8 depth, 16 packed colour
        self.assertIn('pass_01.ppm.u32', files)
        self.assertIn('pass_00.ppm.f32', files)
        for damaged in (log.replace('shader-filter capture enabled:', 'old runtime:'),
                        log.replace('target 1 layer 1', 'target 0 layer 1'),
                        log.replace('pass capture draw:', 'no draws:'),
                        log.replace('pass capture uniform:', 'no uniforms:'),
                        log.replace('raw R11G11B10', 'missing packed sidecar')):
            with self.assertRaises(ValueError):
                capture.motion_files(damaged, 9000, 16)

    def test_input_capture_adds_only_diagnostics_and_requires_sampled_images(self):
        original = b'DM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\nTU_DEBUG=nolrz\nDM_VK_CB_DRAWS=0\n'
        env = capture.capture_env(original,9000,'wheel-inputs')
        self.assertTrue(env.startswith(original))
        self.assertIn(b'DM_VK_PASSDUMP_INPUTS=6\n',env)
        self.assertIn(b'DM_VK_DRAW_PACKET=35696712904ac390\n',env)
        self.assertNotIn(b'DM_VK_PASSDUMP_SIZE=',env)
        log=('shader-filter capture enabled: vertex 35696712904ac390\nframe trace begins at present 9000\n'
             'pass capture draw: present 9001\npass capture uniform: present 9001\n')
        for frame in range(8):
            for part in range(5):
                i=frame*5+part;present=9001+frame
                log+=f"pass dump {i:02d} is the submission's pass 16 (present {present})\n"
                if part==0:
                    log+=f'pass dump {i:02d}: depth 579x326 format 126 → file\n'
                else:
                    log+=f'pass dump {i:02d}: 579x326 format 122 → file\n'
                    if part<3:
                        log+=(f'pass capture: present {present} pass 16 dump {i:02d} target {part-1} layer {part-1}\n'
                              f'pass dump {i:02d} raw R11G11B10 → file\n')
                    else:
                        log+=(f'pass capture input: present {present} pass 16 dump {i:02d} binding {part-2} format {64 if part==3 else 76} size 579x326\n'
                              f'pass dump {i:02d} raw format {64 if part==3 else 76} → file\n')
        files=capture.input_files(log,9000,16)
        self.assertEqual(len(files),80)
        self.assertIn('pass_03.ppm.raw',files)
        for invalid in (log.replace('binding 1 format 64','binding 1 format 76'),log.replace('raw format','no raw')):
            with self.assertRaises(ValueError):capture.input_files(invalid,9000,16)

    def test_wheel_mesh_packet_accepts_shared_volume_shader_but_not_resolve(self):
        packet={'complete':True,'present':9000,'vertex_shader':'35696712904ac390',
                'fragment_shader':'0722cc0403877a4e','streams':[],
                'uniforms':[{'stage':1,'binding':4,'size':224,'saved':True,'file':'draw_packet_fragment_uniform_00.bin'}]}
        self.assertIn('draw_packet_indices.bin',capture.packet_files(packet,9000,wheel=True))
        with self.assertRaises(ValueError):capture.packet_files(packet,9000)
