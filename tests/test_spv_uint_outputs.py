"""Validate raw integer target shader variants with the NDK SPIR-V validator."""
import ctypes as C
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from porter.toolchain import find_ndk

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('cc'), 'host C compiler required')
class UintOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ndk, _ = find_ndk()
        validator = next(ndk.glob('shader-tools/*/spirv-val'), None) if ndk else None
        if not validator:
            raise unittest.SkipTest('NDK SPIR-V tools required')
        cls.tools = validator.parent
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        source = (ROOT/'nxnative/dm/android/gfx_vk_shader.c').read_text()
        source = source[source.index('typedef struct { const uint32_t *w;'):source.index('// A variant of a fragment shader that writes gl_FragDepth')]
        wrapper = cls.folder/'variant.c'
        wrapper.write_text('#include <stdint.h>\n#include <stdlib.h>\n#include <string.h>\n'+source+'\nuint32_t *transform(const uint32_t *w,uint32_t n,uint32_t *o){return spv_uint_outputs(w,n,o);}\nuint32_t *transform_inputs(const uint32_t *w,uint32_t n,uint32_t *o,uint32_t vin){return spv_vertex_inputs(w,n,o,vin);}\n')
        lib = cls.folder/'variant.so'
        subprocess.run(['cc','-shared','-fPIC',str(wrapper),'-o',str(lib)],check=True)
        cls.lib = C.CDLL(str(lib))
        cls.lib.transform.argtypes = [C.POINTER(C.c_uint32),C.c_uint32,C.POINTER(C.c_uint32)]
        cls.lib.transform.restype = C.POINTER(C.c_uint32)
        cls.lib.transform_inputs.argtypes = cls.lib.transform.argtypes+[C.c_uint32]
        cls.lib.transform_inputs.restype = cls.lib.transform.restype
        cls.free = C.CDLL(None).free
        cls.free.argtypes = [C.c_void_p]

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,'temp'): cls.temp.cleanup()

    def check_shader(self, declarations, body):
        src = self.folder/'input.frag'
        src.write_text('#version 450\n'+declarations+'\nvoid main(){'+body+'}\n')
        binary = self.folder/'input.spv'
        subprocess.run([str(self.tools/'glslc'),'-O0',str(src),'-o',str(binary)],check=True)
        data = binary.read_bytes()
        words = (C.c_uint32*(len(data)//4)).from_buffer_copy(data)
        count = C.c_uint32()
        result = self.lib.transform(words,len(words),C.byref(count))
        self.assertTrue(result)
        try: transformed = C.string_at(result,count.value*4)
        finally: self.free(result)
        output = self.folder/'output.spv'
        output.write_bytes(transformed)
        validated = subprocess.run([str(self.tools/'spirv-val'),'--target-env','vulkan1.0',str(output)],capture_output=True,text=True)
        self.assertEqual(validated.returncode,0,validated.stderr)
        dis = subprocess.check_output([str(self.tools/'spirv-dis'),str(output)],text=True)
        self.assertNotIn('OpConvertFToU',dis)
        return dis

    def test_vector_stores_preserve_raw_words(self):
        dis = self.check_shader('layout(location=0) out vec4 c;', 'c=uintBitsToFloat(uvec4(0xffffffffu,0x80000000u,0x12345678u,0u));')
        self.assertIn('OpTypePointer Output %v4uint',dis)
        self.assertIn('OpBitcast %v4uint',dis)

    def test_component_loads_stores_and_multiple_outputs(self):
        dis = self.check_shader('layout(location=0) out vec4 c; layout(location=1) out vec4 d;', 'c=vec4(0);c.x=uintBitsToFloat(0x7fc01234u);d=c;d.y=c.x;')
        self.assertIn('OpTypePointer Output %uint',dis)
        self.assertIn('OpBitcast %float',dis)

    def test_existing_uint_and_signed_outputs(self):
        self.check_shader('layout(location=0) out uvec4 c;', 'c=uvec4(0xffffffffu);')
        self.check_shader('layout(location=0) out ivec4 c;', 'c=ivec4(-1);')

    def test_vertex_integer_fetch_loads_preserve_register_bits(self):
        for component in (False, True):
            source = self.folder/'input.vert'
            source.write_text('#version 450\nlayout(location=0) in vec4 p; layout(location=1) in vec4 bones; layout(location=2) in vec4 signedBits; void main(){gl_Position=p+vec4(floatBitsToUint(bones'+('.x' if component else '')+'))+vec4(floatBitsToInt(signedBits));}')
            binary = self.folder/'vertex.spv'
            subprocess.run([str(self.tools/'glslc'),str(source),'-o',str(binary)],check=True)
            data=binary.read_bytes(); words=(C.c_uint32*(len(data)//4)).from_buffer_copy(data); n=C.c_uint32()
            ptr=self.lib.transform_inputs(words,len(words),C.byref(n),(1<<1)|(1<<18))
            self.assertTrue(ptr)
            try: result=C.string_at(ptr,n.value*4)
            finally: self.free(ptr)
            binary.write_bytes(result)
            check=subprocess.run([str(self.tools/'spirv-val'),'--target-env','vulkan1.0',str(binary)],capture_output=True,text=True)
            self.assertEqual(check.returncode,0,check.stderr)
            dis=subprocess.check_output([str(self.tools/'spirv-dis'),str(binary)],text=True)
            self.assertIn('OpTypePointer Input %v4uint',dis)
            self.assertIn('OpTypePointer Input %v4int',dis)
            self.assertIn('OpBitcast %v4float',dis)
            if component: self.assertIn('OpBitcast %float',dis)
