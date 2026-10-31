"""Check diagnostic pipeline isolation and the embedded solid fragment module."""
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from porter.toolchain import find_ndk

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'nxnative/dm/android/gfx_vk_exec.c'

class DrawProbe(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'),'host C compiler required')
    def test_modes_preserve_unrelated_pipeline_state(self):
        source=SOURCE.read_text()
        start=source.index('typedef struct {\n    uint64_t key[3]')
        types=source[start:source.index('} pkey;',start)+len('} pkey;')]
        start=source.index('static void probe_pipeline(')
        helper=source[start:source.index('static nvn_hmap g_pipes',start)]
        program='#include <stdint.h>\n#include <string.h>\n#include <assert.h>\n'+types+helper+r'''
int main(void) {
    pkey base={.key={123,456,789},.dt=1,.dw=1,.df=3,.cull=2,.st=1,.blend_en=7,.dual=1,.uint_outputs=1,.a2c=1,.logic_en=1,.vin=64,.clip_neg1=1};
    base.wmask[0]=3;base.wmask[1]=7;
    pkey k=base;probe_pipeline(&k,0);assert(!memcmp(&k,&base,sizeof k));
    k=base;probe_pipeline(&k,1);assert(k.probe==1 && !k.dt && !k.dw && k.df==3 && k.cull==2 && k.st==1 && k.wmask[0]==3 && k.blend_en==7);
    k=base;probe_pipeline(&k,2);assert(!k.dt && !k.dw && !k.cull && !k.st && k.wmask[1]==7 && k.blend_en==7);
    k=base;probe_pipeline(&k,3);assert(!k.dt && !k.dw && !k.cull && !k.st && !k.blend_en && !k.a2c && !k.dual && !k.uint_outputs && !k.logic_en && k.wmask[0]==15 && !k.wmask[1]);
    assert(k.key[0]==123 && k.key[1]==456 && k.vin==64 && k.clip_neg1==1);
}
'''
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'probe.c').write_text(program)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'probe.c'),'-o',str(p/'probe')],check=True)
            subprocess.run([str(p/'probe')],check=True)

    def test_solid_fragment_is_valid_spirv(self):
        ndk,_=find_ndk()
        validator=next(ndk.glob('shader-tools/*/spirv-val'),None) if ndk else None
        if not validator:self.skipTest('NDK SPIR-V tools required')
        source=SOURCE.read_text();start=source.index('static VkShaderModule probe_fragment(')
        body=source[start:source.index('static VkPipeline build_pipeline(',start)]
        words=[int(x,16) for x in re.findall(r'0x([0-9a-f]{8})u',body)]
        self.assertGreater(len(words),5)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'solid.spv';p.write_bytes(struct.pack('<'+'I'*len(words),*words))
            result=subprocess.run([str(validator),'--target-env','vulkan1.1',str(p)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
