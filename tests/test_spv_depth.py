"""Validate clip-depth variants with SPIR-V Tools and execute their emitted arithmetic."""
import ctypes as C
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from porter.toolchain import find_ndk

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'host C compiler required')
class ClipDepth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ndk, _ = find_ndk()
        cls.tools = next(ndk.glob('shader-tools/*/spirv-val'), None).parent if ndk else None
        if not cls.tools:
            raise unittest.SkipTest('NDK SPIR-V tools required')
        cls.temp = tempfile.TemporaryDirectory(); cls.folder = Path(cls.temp.name)
        lib = cls.folder / 'depth.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        str(ROOT / 'nxnative/dm/android/spv_depth.c'), '-o', str(lib)], check=True)
        cls.lib = C.CDLL(str(lib)); cls.lib.vk_spv_depth_remap.argtypes = [C.POINTER(C.c_uint32), C.c_uint32, C.POINTER(C.c_uint32)]
        cls.lib.vk_spv_depth_remap.restype = C.POINTER(C.c_uint32)
        cls.free = C.CDLL(None).free; cls.free.argtypes = [C.c_void_p]

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'temp'): cls.temp.cleanup()

    def transform(self, data, valid=True):
        src = (C.c_uint32 * (len(data)//4)).from_buffer_copy(data); n = C.c_uint32()
        ptr = self.lib.vk_spv_depth_remap(src, len(src), C.byref(n))
        if not valid:
            self.assertFalse(ptr); return
        self.assertTrue(ptr)
        try: result = C.string_at(ptr, n.value*4)
        finally: self.free(ptr)
        out = self.folder / 'result.spv'; out.write_bytes(result)
        check = subprocess.run([str(self.tools/'spirv-val'), '--target-env', 'vulkan1.1', str(out)], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        return result

    def assemble(self, z, w, geometry=False):
        source = f'''OpCapability Shader
{'OpCapability Geometry' if geometry else ''}
OpMemoryModel Logical GLSL450
OpEntryPoint {'Geometry' if geometry else 'Vertex'} %main "main" %position
{'OpExecutionMode %main InputPoints' if geometry else ''}
{'OpExecutionMode %main OutputPoints' if geometry else ''}
{'OpExecutionMode %main OutputVertices 2' if geometry else ''}
OpDecorate %position BuiltIn Position
%void = OpTypeVoid
%function = OpTypeFunction %void
%float = OpTypeFloat 32
%vector = OpTypeVector %float 4
%ptr = OpTypePointer Output %vector
%position = OpVariable %ptr Output
%x = OpConstant %float 0.25
%y = OpConstant %float -0.75
%z = OpConstant %float {z}
%w = OpConstant %float {w}
%value = OpConstantComposite %vector %x %y %z %w
%main = OpFunction %void None %function
%label = OpLabel
OpStore %position %value
{'OpEmitVertex' if geometry else ''}
{'OpEmitVertex' if geometry else ''}
OpReturn
OpFunctionEnd
'''
        asm = self.folder/'input.spvasm'; asm.write_text(source)
        out = self.folder/'input.spv'
        subprocess.run([str(self.tools/'spirv-as'), '--target-env', 'vulkan1.1', str(asm), '-o', str(out)], check=True)
        return out.read_bytes()

    def execute(self, data, geometry=False):
        words = struct.unpack('<'+'I'*(len(data)//4), data)
        value, memory, captured = {}, {}, []
        position = None
        i = 5
        while i < len(words):
            n, op = words[i] >> 16, words[i] & 65535; a = words[i+1:i+n]
            if op == 71 and a[1:] == (11, 0): position = a[0]
            if op == 43: value[a[1]] = struct.unpack('<f', struct.pack('<I', a[2]))[0]
            if op == 44: value[a[1]] = [value[x] for x in a[2:]]
            if op == 62: memory[a[0]] = value[a[1]]
            if op == 61: value[a[1]] = memory[a[2]]
            if op == 81: value[a[1]] = value[a[2]][a[3]]
            if op == 133: value[a[1]] = value[a[2]] * value[a[3]]
            if op == 129: value[a[1]] = value[a[2]] + value[a[3]]
            if op == 82:
                v = list(value[a[3]]); v[a[4]] = value[a[2]]; value[a[1]] = v
            if op == 218 or (op == 253 and not geometry): captured.append(list(memory[position]))
            i += n
        return captured

    def test_negative_depth_is_preserved_in_vulkan_clip_volume(self):
        for z, w in [(-1, 1), (-0.5, 1), (0, 1), (1, 1), (-2, 2), (2, 2)]:
            with self.subTest(z=z, w=w):
                result = self.transform(self.assemble(z, w))
                p = self.execute(result)[0]
                self.assertEqual(p, [0.25, -0.75, (z+w)/2, w])
                self.assertTrue(0 <= p[2] <= p[3])

    def test_outside_vertices_remain_outside(self):
        for z in (-2, 2):
            p = self.execute(self.transform(self.assemble(z, 1)))[0]
            self.assertFalse(0 <= p[2] <= p[3])

    def test_geometry_emits_do_not_accumulate_the_conversion(self):
        result = self.transform(self.assemble(-0.5, 1, geometry=True))
        self.assertEqual(self.execute(result, geometry=True), [[0.25, -0.75, 0.25, 1]]*2)

    def test_glsl_position_block_and_multiple_returns(self):
        for stage, text in [('vert', '''#version 450
layout(location=0) in vec4 p;
void main() { if(p.x<0) {gl_Position=p; return;} gl_Position=vec4(p.xy,-0.5,1); }
'''), ('geom', '''#version 450
layout(points) in;
layout(points,max_vertices=2) out;
void emit() { gl_Position=gl_in[0].gl_Position; EmitVertex(); }
void main() { emit(); emit(); EndPrimitive(); }
''')]:
            with self.subTest(stage=stage):
                src = self.folder/f'input.{stage}'; src.write_text(text)
                out = self.folder/'glsl.spv'
                subprocess.run([str(self.tools/'glslc'), '--target-env=vulkan1.1', str(src), '-o', str(out)], check=True)
                self.transform(out.read_bytes())

    def test_malformed_and_non_vertex_modules_rejected(self):
        data = self.assemble(0, 1)
        # Broken header and zero-length instructions must fail without loops or OOB reads.
        for broken in [bytes(20), data[:24], data[:20] + bytes(4) + data[24:]]:
            self.transform(broken, valid=False)
        src = self.folder/'input.frag'; src.write_text('#version 450\nlayout(location=0)out vec4 c;void main(){c=vec4(1);}')
        out = self.folder/'frag.spv'
        subprocess.run([str(self.tools/'glslc'), str(src), '-o', str(out)], check=True)
        self.transform(out.read_bytes(), valid=False)
