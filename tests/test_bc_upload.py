"""Exercise the actual format selector and packaged-upload code with Vulkan calls stubbed."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DM = ROOT / 'nxnative/dm'


@unittest.skipUnless(shutil.which('cc'), 'a host C compiler is required')
class BCUpload(unittest.TestCase):
    def test_formats_and_uploads(self):
        source = (DM / 'android/gfx_vk_tex.c').read_text()
        header = (DM / 'android/gfx_vk.h').read_text()
        fmt = header[header.index('typedef struct { VkFormat vk;'):header.index('vkfmt_t;') + len('vkfmt_t;')]
        image = header[header.index('typedef struct vkimg vkimg_t;'):header.index('\nvkimg_t *vk_tex(')]
        formats = source[source.index('enum { K_NONE'):source.index('static VkImageAspectFlags aspect_of')]
        start = source.index('static void pkg_upload_(vkimg_t *im, const tex_t *t, const vkfmt_t *f) {')
        upload = source[start:source.index('\nstatic int packaged_tex', start)]
        executor = (DM / 'android/gfx_vk_exec.c').read_text()
        start = executor.index('static int pipeline_target_needs_readback(')
        readback = executor[start:executor.index('static int async_pipe(', start)]
        code = r'''
#define _GNU_SOURCE
#include <vulkan/vulkan_core.h>
#include <assert.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "nvn_bc.h"
#include "nvn_deswizzle.h"
#define NVN_TEXTURE_FLAGS_LINEAR 0x10
#define NVN_TEXTURE_FLAGS_LINEAR_RENDER_TARGET 0x40
#define VKLOG(...) ((void)0)
#define VKRED_ONCE(id, ...) abort()
static void die(const char *f, ...) { va_list a; va_start(a, f); vfprintf(stderr, f, a); va_end(a); abort(); }
static struct { int has_bc, has_astc; VkPhysicalDevice pd; } V;
typedef struct { uint64_t serial; nvn_texdesc d; nvn_texlayout L; const uint8_t *mem; } tex_t;
''' + fmt + image + formats + readback + r'''
void vkGetPhysicalDeviceFormatProperties(VkPhysicalDevice p, VkFormat f, VkFormatProperties *o) { (void)p; (void)f; memset(o, 0, sizeof *o); }
static unsigned calls, layer, level, test_linear, uploads; static uint8_t expected[32][8];
static void *scratch; static size_t scratch_size;
static VkCommandBuffer vk_upload_cmd(void) { return (VkCommandBuffer)1; }
static void vk_tex_prepare(VkCommandBuffer cb, vkimg_t *im) { (void)cb; im->layout = VK_IMAGE_LAYOUT_GENERAL; }
static void nvn_dirty_protect(const void *p, size_t n) { (void)p; (void)n; }
static uint64_t nvn_dirty_now(void) { return 77; }
static const void *nvn_dirty_span(const void *p, size_t n) { (void)n; return p; }
static void *vk_scratch(size_t n, size_t align, VkBuffer *b, VkDeviceSize *o) {
    (void)align; free(scratch); scratch = malloc(n); scratch_size = n;
    *b = (VkBuffer)(uintptr_t)scratch; *o = 0; return scratch;
}
void vkCmdCopyBufferToImage(VkCommandBuffer cb, VkBuffer b, VkImage im, VkImageLayout layout, uint32_t count, const VkBufferImageCopy *r) {
    (void)cb; (void)im; (void)layout; assert(count == 1 && r->bufferOffset == 0);
    assert(r->bufferRowLength == 0 && r->bufferImageHeight == 0);
    unsigned z = r->imageExtent.depth, w = r->imageExtent.width, h = r->imageExtent.height;
    assert(scratch_size == (size_t)w*h*z);
    for (unsigned s = 0; s < z; s++) for (unsigned i = 0; i < w*h; i++)
        assert(((uint8_t *)(uintptr_t)b)[s*w*h + i] == expected[r->imageSubresource.baseArrayLayer][r->imageSubresource.mipLevel] + s);
    calls++;
}
''' + upload + r'''
static void reset(void) { memset(g_fmt, 0, sizeof g_fmt); memset(g_fmt_done, 0, sizeof g_fmt_done); }
// Decode the selected Vulkan packed format by Vulkan's bit layout, not its
// spelling in NVN. NVN RGB565 stores R in bits 0..4; Vulkan R5G6B5 stores R
// in bits 11..15. This reproduces yellow cup icons turning cyan.
static unsigned sample565(int nvn, unsigned word) {
    const vkfmt_t *f = vk_fmt(nvn); assert(f && f->bpb == 2);
    unsigned low = word & 31, high = word >> 11, green = (word >> 5) & 63;
    unsigned red, blue;
    if (f->vk == VK_FORMAT_B5G6R5_UNORM_PACK16) { red = low; blue = high; }
    else { assert(f->vk == VK_FORMAT_R5G6B5_UNORM_PACK16); red = high; blue = low; }
    assert(f->swz.r == VK_COMPONENT_SWIZZLE_IDENTITY && f->swz.b == VK_COMPONENT_SWIZZLE_IDENTITY);
    return ((red * 255 / 31) << 16) | ((green * 255 / 63) << 8) | (blue * 255 / 31);
}
int main(void) {
    V.has_bc = 1; V.has_astc = 1;
    tex_t readback_target = {.d={.format=0x25}};
    assert(!pipeline_target_needs_readback(&readback_target));
    readback_target.d.flags = NVN_TEXTURE_FLAGS_LINEAR_RENDER_TARGET;
    assert(pipeline_target_needs_readback(&readback_target));
    readback_target.d.flags = 0; readback_target.d.format = 0x44;
    assert(!pipeline_target_needs_readback(&readback_target)); // native BC needs no CPU decode
    assert(sample565(0x3c, 0x001f) == 0xff0000); // red
    assert(sample565(0x3c, 0x07ff) == 0xffff00); // yellow, not cyan
    assert(sample565(0x3c, 0xf800) == 0x0000ff); // blue
    assert(sample565(0x3c, 0x07e0) == 0x00ff00); // green
    assert(sample565(0x95, 0xf800) == 0xff0000); // BGR565 has the opposite layout
    assert(sample565(0x95, 0xffe0) == 0xffff00);
    assert(sample565(0x95, 0x001f) == 0x0000ff);
    for (int f = 0x41; f <= 0x50; f++) { const vkfmt_t *v = vk_fmt(f); assert(v && !v->bc_decode && v->compressed && v->bw == 4 && v->bh == 4); }
    reset(); V.has_bc = 0;
    assert(pipeline_target_needs_readback(&readback_target)); // generated BC must not be skipped
    for (int f = 0x41; f <= 0x50; f++) { const vkfmt_t *v = vk_fmt(f); assert(v && v->bc_decode && !v->compressed && v->bw == 4 && v->bh == 4); assert(v->bpb == nvn_bc_block_size(f)); }
    assert(vk_fmt(0x49)->vk == VK_FORMAT_R8_UNORM && vk_fmt(0x4a)->vk == VK_FORMAT_R8_SNORM);
    assert(vk_fmt(0x4b)->vk == VK_FORMAT_R8G8_UNORM && vk_fmt(0x4c)->vk == VK_FORMAT_R8G8_SNORM);
    assert(vk_fmt(0x45)->vk == VK_FORMAT_R8G8B8A8_SRGB && vk_fmt(0x4e)->vk == VK_FORMAT_R8G8B8A8_SRGB);
    assert(vk_fmt(0x4f)->vk == VK_FORMAT_R16G16B16A16_SFLOAT && vk_fmt(0x50)->vk == VK_FORMAT_R16G16B16A16_SFLOAT);
    reset(); V.has_bc = 1; setenv("DM_VK_BC_DECODE", "1", 1); assert(vk_fmt(0x49)->bc_decode); unsetenv("DM_VK_BC_DECODE");
    reset(); V.has_bc = 0;
    int targets[] = {1, 2, 4, 8, 9};
    for (unsigned k = 0; k < 5; k++) {
        int target = targets[k]; tex_t t = {.serial=1, .d={target, 0x49, 0, 0, 19, 13, target == 8 ? 1 : target == 9 ? 12 : 3, 5, 0, 0}};
        nvn_tex_layout(&t.d, &t.L); uint8_t *mem = calloc(1, t.L.size); t.mem = mem;
        vkimg_t im = {.w=19, .h=13, .d=target == 2 ? 3 : 1, .levels=5, .layers=t.L.layers, .aspect=VK_IMAGE_ASPECT_COLOR_BIT};
        // Re-upload the same image with changed CPU contents, as dirty tracking does.
        for (unsigned pass = 0; pass < 2; pass++) {
            for (unsigned ly = 0; ly < im.layers; ly++) for (unsigned lv = 0; lv < im.levels; lv++) {
                unsigned w = im.w >> lv, h = im.h >> lv, z = im.d >> lv;
                if (!w) w=1; if (!h) h=1; if (!z) z=1;
                size_t pitch=((w+3)/4)*8, rows=(h+3)/4, n=pitch*rows*z;
                uint8_t *blocks = calloc(1,n); expected[ly][lv] = 20+7*ly+lv+pass;
                for (unsigned s=0;s<z;s++) for(size_t b=0;b<pitch*rows;b+=8) blocks[s*pitch*rows+b]=expected[ly][lv]+s;
                assert(!nvn_swizzle(&t.d, lv, ly, blocks, pitch, mem)); free(blocks);
            }
            pkg_upload_(&im, &t, vk_fmt(0x49)); assert(im.pkg_mem == mem && im.pkg_stamp == 77); uploads++;
        }
        free(mem);
    }
    // Linear BC4 with padded block rows.
    tex_t t = {.serial=2, .d={1,0x49,0x10,0,5,5,1,1,32,0}};
    uint8_t linear[64]={0}; linear[0]=linear[8]=linear[32]=linear[40]=99; t.mem=linear; t.L.size=64; expected[0][0]=99;
    vkimg_t im={.w=5,.h=5,.d=1,.layers=1,.levels=1,.aspect=VK_IMAGE_ASPECT_COLOR_BIT};
    pkg_upload_(&im, &t, vk_fmt(0x49));
    assert(calls == 231 && uploads == 10); free(scratch);
    puts("BC format selection and 231 packaged mip/layer uploads passed");
}
'''
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / 'test.c'; src.write_text(code)
            exe = Path(folder) / 'test'
            subprocess.run(['cc', '-std=c11', '-O1', '-fno-strict-aliasing', '-pthread',
                            '-I', str(DM / 'third_party/vulkan-headers/include'), '-I', str(DM / 'gfx/tex'),
                            str(src), str(DM / 'gfx/tex/nvn_bc.c'), str(DM / 'gfx/tex/nvn_deswizzle.c'),
                            str(DM / 'gfx/nvn/nvn_tex.c'), '-o', str(exe)], check=True)
            result = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
            self.assertIn('231 packaged mip/layer uploads passed', result.stdout)
