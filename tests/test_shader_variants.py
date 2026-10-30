"""Exercise merged shader-variant routing/cache with Vulkan and transforms stubbed."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DM = ROOT/'nxnative/dm'


@unittest.skipUnless(shutil.which('cc'), 'host C compiler required')
class ShaderVariants(unittest.TestCase):
    def test_independent_variant_bits_and_cache_entries(self):
        source = (DM/'android/gfx_vk_shader.c').read_text()
        start = source.index('VkShaderModule vk_shader_module(')
        function = source[start:source.index('\n// static buffers:', start)]
        code = r'''
#include <vulkan/vulkan_core.h>
#include <pthread.h>
#include <stdint.h>
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "shader_variant.h"
#define VKLOG(...) ((void)0)
#define die(...) abort()
static struct {VkDevice dev;} V;
static pthread_mutex_t g_sh_mu=PTHREAD_MUTEX_INITIALIZER;
typedef struct {
    int stage,depth_repl,nbind; uint64_t key; uint32_t *spv,nspv; VkShaderModule mod;
    struct {uint16_t binding;} b[64];
    struct {uint64_t um,im; uint32_t xo; int fd; VkShaderModule mod;} var[8]; int nvar;
} vkshader_t;
static unsigned created;
static uint32_t *change(const uint32_t *w,uint32_t n,uint32_t *nn,unsigned bit) {
    uint32_t *o=malloc(n*4);memcpy(o,w,n*4);o[0]|=bit;*nn=n;return o;
}
static uint32_t *spv_int_images(const uint32_t*w,uint32_t n,const uint16_t*b,const uint8_t*k,int nb,uint32_t*nn) {
    (void)b;(void)k;assert(nb==1);return change(w,n,nn,32);
}
static uint32_t *spv_add_outputs(const uint32_t*w,uint32_t n,uint32_t mask,uint32_t*nn) {assert(mask==1);return change(w,n,nn,4);}
static uint32_t *spv_vs_init(const uint32_t*w,uint32_t n,uint32_t*nn) {return change(w,n,nn,16);}
static uint32_t *spv_frag_depth(const uint32_t*w,uint32_t n,uint32_t*nn) {return change(w,n,nn,1);}
static uint32_t *spv_dual(const uint32_t*w,uint32_t n,uint32_t*nn) {return change(w,n,nn,2);}
static uint32_t *vk_spv_depth_remap(const uint32_t*w,uint32_t n,uint32_t*nn) {return change(w,n,nn,8);}
static VkShaderModule alt_module(vkshader_t*s) {(void)s;return (VkShaderModule)200;}
VkResult vkCreateShaderModule(VkDevice d,const VkShaderModuleCreateInfo*c,const VkAllocationCallbacks*a,VkShaderModule*m) {
    (void)d;(void)a;assert(c->codeSize==4);*m=(VkShaderModule)(uintptr_t)(100+c->pCode[0]);created++;return VK_SUCCESS;
}
''' + function + r'''
int main(void) {
    uint32_t word=0;
    vkshader_t vs={.stage=0,.spv=&word,.nspv=1,.mod=(VkShaderModule)99};
    vkshader_t fs=vs;fs.stage=1;
    vkshader_t gs=vs;gs.stage=2;
    assert(VK_SHADER_DUAL_SOURCE!=VK_SHADER_CLIP_DEPTH);
    assert(vk_shader_module(&vs,0,0,0,VK_SHADER_CLIP_DEPTH)==(VkShaderModule)108);
    unsigned count=created;
    assert(vk_shader_module(&vs,0,0,0,VK_SHADER_CLIP_DEPTH)==(VkShaderModule)108 && created==count);
    assert(vk_shader_module(&vs,0,0,0,VK_SHADER_DUAL_SOURCE)==vs.mod);
    assert(vk_shader_module(&vs,0,0,1,VK_SHADER_CLIP_DEPTH)==(VkShaderModule)128); // outputs, init, depth
    assert(vk_shader_module(&vs,0,0,1,0)==(VkShaderModule)120); // distinct cache entry
    vs.nbind=1;vs.b[0].binding=7;
    assert(vk_shader_module(&vs,1,0,0,VK_SHADER_CLIP_DEPTH)==(VkShaderModule)140); // integer variant + depth
    assert(vk_shader_module(&fs,0,0,0,VK_SHADER_DUAL_SOURCE)==(VkShaderModule)102);
    assert(vk_shader_module(&fs,0,0,0,VK_SHADER_FRAG_DEPTH)==(VkShaderModule)101);
    assert(vk_shader_module(&fs,0,0,0,VK_SHADER_DUAL_SOURCE|VK_SHADER_FRAG_DEPTH)==(VkShaderModule)103);
    count=created;
    assert(vk_shader_module(&fs,0,0,0,VK_SHADER_DUAL_SOURCE)==(VkShaderModule)102 && created==count);
    assert(vk_shader_module(&fs,0,0,0,VK_SHADER_CLIP_DEPTH)==fs.mod);
    fs.depth_repl=1;
    assert(vk_shader_module(&fs,0,0,0,VK_SHADER_DUAL_SOURCE|VK_SHADER_FRAG_DEPTH)==(VkShaderModule)102);
    assert(vk_shader_module(&gs,0,0,0,VK_SHADER_CLIP_DEPTH)==(VkShaderModule)108);
    assert(vk_shader_variant_flags(5,0,7)==0);
}
'''
        with tempfile.TemporaryDirectory() as folder:
            src=Path(folder)/'variants.c';src.write_text(code)
            exe=Path(folder)/'variants'
            subprocess.run(['cc','-std=gnu11','-pthread','-I',str(DM/'third_party/vulkan-headers/include'),
                            '-I',str(DM/'android'),str(src),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
