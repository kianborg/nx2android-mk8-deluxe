"""Analytic checks for the optional offline light reference (NumPy required)."""
import importlib.util
from pathlib import Path
import unittest


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'optional NumPy analysis dependency')
class WheelReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.np=np
        spec=importlib.util.spec_from_file_location('wheel_reference',Path(__file__).resolve().parents[1]/'devtools/analyze_wheel_inputs.py')
        cls.ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.ref)

    def test_one_unit_front_facing_lambert_and_squared_attenuation(self):
        np=self.np;camera=np.zeros((14,4));camera[10,0]=1;camera[11,:2]=1
        light=np.zeros((6,4));light[1]=[2,4,6,.25];light[3,3]=2
        normals=np.array([[[.5,.5,1.]]]);depth=np.zeros((1,1))
        np.testing.assert_allclose(self.ref.diffuse(normals,depth,camera,light),[[[1.125,2.25,3.375]]])
        normals[:,:,2]=0
        np.testing.assert_array_equal(self.ref.diffuse(normals,depth,camera,light),0)
        normals[:,:,2]=1;light[1,3]=2
        np.testing.assert_array_equal(self.ref.diffuse(normals,depth,camera,light),0)

    def test_packed_colour_decoders(self):
        np=self.np
        packed=np.array([960|(960<<11)|(480<<22)],dtype=np.uint32)
        np.testing.assert_array_equal(self.ref.decode_lights(packed),[[1,1,1]])
        np.testing.assert_array_equal(self.ref.decode_normals(np.array([0xffffffff],dtype=np.uint32)),[[1,1,1]])
        np.testing.assert_array_equal(self.ref.decode_normals(np.array([1023],dtype=np.uint32)),[[1,0,0]])

    def test_complete_capture_with_reversed_sampler_bindings(self):
        import tempfile
        np=self.np
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);camera=np.zeros((14,4),dtype='<f4');camera[10,0]=1;camera[11,:2]=1
            light=np.zeros((6,4),dtype='<f4');light[1]=[2,4,6,.25];light[3,3]=2
            log=('pass capture input: present 9000 pass 16 dump 03 binding 1 format 76 size 1x1\n'
                 'pass capture input: present 9000 pass 16 dump 04 binding 2 format 64 size 1x1\n'
                 'pass capture: present 9000 pass 16 dump 01 target 0 layer 0\n'
                 'pass capture draw: present 9000 pass 16 draw 14 VS 35696712904ac390 FS 30b45cd2223d3964\n')
            for reg,values in enumerate((camera,light)):
                words=' '.join(f'{int(x):08x}' for x in values.ravel().view('<u4'))
                log+=f'pass capture uniform: present 9000 pass 16 draw 14 stage 1 binding {3+reg} c{reg} address 1000 size {values.nbytes} bytes {values.nbytes} hex {words}\n'
            (folder/'log.txt').write_text(log)
            for i in (1,3,4):(folder/f'pass_{i:02d}.ppm').write_bytes(b'P6\n1 1\n255\n\0\0\0')
            np.array([0],dtype='<f2').tofile(folder/'pass_03.ppm.raw')
            np.array([512|(512<<10)|(1023<<20)],dtype='<u4').tofile(folder/'pass_04.ppm.raw')
            np.array([0],dtype='<u4').tofile(folder/'pass_01.ppm.u32')
            report=self.ref.analyze(folder)['passes'][0]
            self.assertEqual(report['underlit_candidates'],1)
            self.assertEqual(report['final_frame'],9001)
            self.assertAlmostEqual(report['predicted_green_sum'],2.25)
