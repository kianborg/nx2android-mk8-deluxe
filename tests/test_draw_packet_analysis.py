"""Known skinning result with nonzero base vertex and strided input streams."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('packet_analysis',ROOT/'devtools/analyze_draw_packet.py')
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)

class PacketAnalysis(unittest.TestCase):
    def test_reference_skinning_and_input_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            (p/'pos.bin').write_bytes(bytes(16)+bytes(4)+struct.pack('<3f',1,2,3))
            (p/'weights.bin').write_bytes(bytes(8)+bytes(2)+bytes([128,127,0,0])+bytes(2))
            (p/'bones.bin').write_bytes(bytes(8)+bytes(1)+bytes([0,1,0,0])+bytes(3))
            identity=[1,0,0,0,0,1,0,0,0,0,1,0]
            shifted=[1,0,0,10,0,1,0,0,0,0,1,0]
            (p/'palette.bin').write_bytes(struct.pack('<24f',*(identity+shifted)))
            (p/'draw_packet_indices.bin').write_bytes(bytes(6))
            manifest={'version':1,'complete':True,'vertex_shader':'45539f60801ff5e3','present':1,'base_vertex':1,'index_type':1,'count':3,
                'attributes':[{'location':0,'format':34,'stream':0,'offset':4},{'location':4,'format':37,'stream':3,'offset':2},{'location':6,'format':39,'stream':4,'offset':1}],
                'streams':[{'stream':i,'stride':stride,'size':size,'divisor':0,'saved':True,'file':name} for i,stride,size,name in [(0,16,32,'pos.bin'),(3,8,16,'weights.bin'),(4,8,16,'bones.bin')]],
                'uniforms':[{'binding':1,'saved':True,'size':96,'file':'palette.bin'}]}
            file=p/'draw_packet.json';file.write_text(json.dumps(manifest))
            report,points,order=analysis.reconstruct(p)
            self.assertAlmostEqual(points[0][0],1+10*127/255)
            self.assertEqual(points[0][1:],[2,3])
            self.assertEqual(report['invalid_weighted_bone_references'],0)
            self.assertEqual(report['weight_sum_histogram'],{255:1})
            self.assertEqual(order,(0,0,0))
            manifest['base_vertex']=10;file.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'outside'):analysis.reconstruct(p)
            manifest['base_vertex']=1;manifest['streams'][0]['file']='../outside.bin';file.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'escapes'):analysis.reconstruct(p)
