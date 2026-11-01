"""Exercise the runtime's pass selector with changing sizes and unrelated passes."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class PassCapture(unittest.TestCase):
    def test_actual_pass_selector_handles_dynamic_resolution_and_both_targets(self):
        cc = shutil.which('cc')
        if not cc:
            self.skipTest('C compiler required')
        source = (Path(__file__).resolve().parents[1]/'nxnative/dm/android/gfx_vk_exec.c').read_text()
        function = 'static void pass_dump(void) {' + source.split('static void pass_dump(void) {', 1)[1].split('\nstatic void texdump_flush(void) {', 1)[0]
        harness = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
typedef struct {int bc_decode;} vkfmt_t;
static const vkfmt_t *vk_fmt(int f) {(void)f;return NULL;}
static struct {int rt_has_col[8],rt_has_cview[8]; struct {int set_format,format;} rt_cview[8];
 struct {struct {int format;} d;} rt_col[8];int cfmt[8],ncol;unsigned pass_w,pass_h;} S;
static uint64_t g_pd_shader;
static int g_pd_match,g_pd_state=1,g_pd_skip,g_sub_pass=19;
static char g_pd_size[128],g_pd_from[32];
static int targets,depths;
static void texdump_flush(void) {}
static void pass_dump_depth(void) {depths++;}
static void pass_dump_colour(int ci) {if(ci<S.ncol)targets|=1<<ci;}
''' + function + r'''
int main(void) {
 S.ncol=2;S.rt_has_col[0]=S.rt_has_col[1]=1;
 setenv("DM_VK_PASSDUMP_TARGET","all",1);
 g_pd_shader=0x35696712904ac390ull;
 // An unrelated pass at the same formats/sizes must not count as the light pass.
 pass_dump();assert(!targets && !depths);
 g_pd_match=1;S.pass_w=482;S.pass_h=271;
 pass_dump();assert(targets==3 && depths==1);
 targets=depths=0;S.pass_w=551;S.pass_h=309;g_sub_pass=24;
 pass_dump();assert(targets==3 && depths==1);
 targets=depths=0;g_pd_match=0;
 pass_dump();assert(!targets && !depths);
 // Legacy, unfiltered capture still supports one selected target.
 g_pd_shader=0;setenv("DM_VK_PASSDUMP_TARGET","1",1);
 pass_dump();assert(targets==2 && depths==1);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            c, exe = Path(tmp)/'capture.c', Path(tmp)/'capture'
            c.write_text(harness)
            built = subprocess.run([cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            subprocess.run([str(exe)], check=True)
