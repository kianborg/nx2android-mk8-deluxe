"""BC readback must happen after ending a pass, and async draws must not skip it."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'host C compiler required')
class BCPassHooks(unittest.TestCase):
    def test_end_pass_and_readback_classification(self):
        source = (ROOT / 'nxnative/dm/android/gfx_vk_exec.c').read_text()
        def function(name):
            start = source.index(name)
            return source[start:source.index('\n}\n', start)+3]
        code = r'''
#define _GNU_SOURCE
#include <vulkan/vulkan_core.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdlib.h>
#include <assert.h>
#define VKLOG(...) ((void)0)
#define NVN_TEXTURE_FLAGS_LINEAR_RENDER_TARGET 0x40
typedef struct {struct {int flags,format;} d;} tex_t;
typedef struct {int dec;} vkfmt_t;
static vkfmt_t formats[2]={{0},{4}};
static const vkfmt_t *vk_fmt(int f) {return f>=0 && f<2?&formats[f]:NULL;}
static struct {int pass_open,rp_pass;VkPipeline bound_pipe;unsigned pass_w,pass_h;VkFormat cfmt[8];} S;
static int g_x_listpasses,P_cleared,g_x_tracepass=-1,g_sub_pass,g_lin_back,g_tf_in_pass;
static unsigned g_pass_draws,g_pass_bb[4],ended,flushed,committed;
static VkCommandBuffer vk_cmd(void) {return (VkCommandBuffer)1;}
void vkCmdEndRenderPass(VkCommandBuffer c) {(void)c;ended++;}
void vkCmdEndRendering(VkCommandBuffer c) {(void)c;ended++;}
static int pass_commit(void) {committed++;S.pass_open=1;return 1;}
static void pass_dump(void) {}
void vk_pass_ts(int e,uint32_t w,uint32_t h,uint32_t f,uint32_t d) {(void)e;(void)w;(void)h;(void)f;(void)d;}
static void lin_back(void) {abort();}
static void crumb_mark(int d) {(void)d;}
void vk_bc_flush_targets(void) {
 assert(!S.pass_open && !S.bound_pipe && !g_tf_in_pass);flushed++;
}
''' + function('void vk_end_pass(void) {') + function('static int pipeline_target_needs_readback(') + r'''
int main(void) {
 S.pass_open=1;S.bound_pipe=(VkPipeline)2;g_tf_in_pass=1;vk_end_pass();
 assert(ended==1 && flushed==1);
 S.pass_open=2;P_cleared=1;S.rp_pass=1;vk_end_pass();
 assert(committed==1 && ended==2 && flushed==2);
 tex_t t={.d={0,0}};assert(!pipeline_target_needs_readback(&t));
 t.d.format=1;assert(pipeline_target_needs_readback(&t));
 t.d.format=0;t.d.flags=NVN_TEXTURE_FLAGS_LINEAR_RENDER_TARGET;assert(pipeline_target_needs_readback(&t));
 t.d.format=99;t.d.flags=0;assert(!pipeline_target_needs_readback(&t));
}
'''
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / 'hooks.c'
            exe = Path(folder) / 'hooks'
            src.write_text(code)
            subprocess.run(['cc', '-std=gnu11', '-I', str(ROOT / 'nxnative/dm/third_party/vulkan-headers/include'),
                            str(src), '-ldl', '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
