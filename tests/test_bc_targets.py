"""GPU BC target shadows: execute real attach/flush code with Vulkan transfers stubbed."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
DM=ROOT/'nxnative/dm'


@unittest.skipUnless(shutil.which('cc'),'host C compiler required')
class BCTargets(unittest.TestCase):
    def test_generated_blocks_mips_layers_and_load_preservation(self):
        src=(DM/'android/gfx_vk_tex.c').read_text()
        start=src.index('typedef struct {\n    vkimg_t *shadow, *base;')
        helper=src[start:src.index('static VkComponentSwizzle swz_comp',start)]
        header=(DM/'android/gfx_vk.h').read_text()
        types=header[header.index('typedef struct { VkFormat vk;'):header.index('vkfmt_t;')+len('vkfmt_t;')]
        image=header[header.index('typedef struct vkimg vkimg_t;'):header.index('\nvkimg_t *vk_tex(')]
        code=r'''
#include <vulkan/vulkan_core.h>
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "nvn_bc.h"
#include "nvn_deswizzle.h"
#define NVN_TEXTURE_FLAGS_LINEAR 0x10
#define NVN_TEXTURE_FLAGS_LINEAR_RENDER_TARGET 0x40
#define VKLOG(...) ((void)0)
#define VKCHK(x) assert((x)==VK_SUCCESS)
static void die(const char *s,...) {va_list a;va_start(a,s);vfprintf(stderr,s,a);va_end(a);abort();}
''' + types + image + r'''
typedef struct {uint64_t serial;nvn_texdesc d;nvn_texlayout L;const uint8_t *mem;} tex_t;
typedef struct {int set_format,format,set_levels,base_level,set_layers,min_layer,nlayers;} view_t;
static struct {VkDevice dev;} V;
static vkfmt_t bc={.vk=VK_FORMAT_R8G8B8A8_UNORM,.kind=1,.bc_decode=1,.bw=4,.bh=4,.bpb=16};
static vkfmt_t raw={.vk=VK_FORMAT_R32G32B32A32_UINT,.kind=1,.is_int=1,.bw=1,.bh=1,.bpb=16};
static const vkfmt_t *vk_fmt(int f) {return f==0x44?&bc:f==0x2f?&raw:NULL;}
static vkimg_t base;
static vkimg_t *vk_tex(const tex_t *t) {(void)t;return &base;}
static unsigned layers_of(const nvn_texdesc *d) {return d->target==4?d->depth:1;}
static unsigned g_img_n,freed_views,created,snapshots,uploads,release_count;
static uint64_t g_img_bytes;
static VkFormat vk_view_fmt;static uint32_t vk_view_layers;
static void *allocations[256];static unsigned nalloc;
static uint8_t last_upload[8192];static VkBufferImageCopy last_region;static size_t last_bytes;
static vkimg_t *img_new(const tex_t *t,const vkfmt_t *f) {
    vkimg_t *im=calloc(1,sizeof *im);im->w=t->d.width;im->h=t->d.height;im->fmt=f->vk;
    im->allocation_size=im->w*im->h*16;im->usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
    im->img=(VkImage)(uintptr_t)calloc(1,im->allocation_size);created++;return im;
}
static void img_drop(vkimg_t *im) {g_img_n--;g_img_bytes-=im->allocation_size;free((void *)(uintptr_t)im->img);free(im);}
static void vk_defer_free_view(VkImageView v) {(void)v;freed_views++;}
VkResult vkCreateImageView(VkDevice d,const VkImageViewCreateInfo *c,const VkAllocationCallbacks *a,VkImageView *v) {
    (void)d;(void)a;assert(c->viewType==VK_IMAGE_VIEW_TYPE_2D && c->format==raw.vk);*v=(VkImageView)c->image;return VK_SUCCESS;
}
static void *vk_scratch(size_t n,size_t align,VkBuffer *b,VkDeviceSize *o) {
    (void)align;assert(nalloc<256);void *p=malloc(n);allocations[nalloc++]=p;*b=(VkBuffer)(uintptr_t)p;*o=0;return p;
}
static VkCommandBuffer vk_cmd(void) {return (VkCommandBuffer)1;}
static void vk_tex_prepare(VkCommandBuffer cb,vkimg_t *im) {(void)cb;im->layout=VK_IMAGE_LAYOUT_GENERAL;}
static void vk_img_barrier_all(VkCommandBuffer cb) {(void)cb;}
void vkCmdCopyBufferToImage(VkCommandBuffer cb,VkBuffer b,VkImage im,VkImageLayout l,uint32_t n,const VkBufferImageCopy *r) {
    (void)cb;(void)l;assert(n==1);
    if(im==base.img) {last_region=*r;last_bytes=r->imageExtent.width*r->imageExtent.height*4;assert(last_bytes<=sizeof last_upload);memcpy(last_upload,(void *)((uintptr_t)b+r->bufferOffset),last_bytes);uploads++;}
    else memcpy((void *)(uintptr_t)im,(void *)((uintptr_t)b+r->bufferOffset),r->imageExtent.width*r->imageExtent.height*16);
}
void vkCmdCopyImageToBuffer(VkCommandBuffer cb,VkImage im,VkImageLayout l,VkBuffer b,uint32_t n,const VkBufferImageCopy *r) {
    (void)cb;(void)l;assert(n==1);memcpy((void *)((uintptr_t)b+r->bufferOffset),(void *)(uintptr_t)im,r->imageExtent.width*r->imageExtent.height*16);
}
static void vk_buffer_snapshot(VkBuffer b,VkDeviceSize off,size_t n,void *p) {memcpy(p,(void *)((uintptr_t)b+off),n);snapshots++;}
static void nvn_dirty_release(const void *p,size_t n) {(void)p;(void)n;release_count++;}
static void nvn_dirty_protect(const void *p,size_t n) {(void)p;(void)n;}
static uint64_t nvn_dirty_now(void) {return 123;}
''' + helper + r'''
static const uint8_t red[16]={255,0,0,0,0,0,0,0,0,248,224,7,0,0,0,0};
static const uint8_t blue[16]={255,0,0,0,0,0,0,0,31,0,224,7,0,0,0,0};
int main(void) {
    tex_t t={.serial=44,.d={4,0x44,0,0,19,13,3,5,0,0}};nvn_tex_layout(&t.d,&t.L);
    uint8_t *storage=calloc(1,t.L.size);t.mem=storage;
    base=(vkimg_t){.w=19,.h=13,.d=1,.layers=3,.levels=5,.img=(VkImage)999,.packaged=1};
    for(unsigned ly=0;ly<3;ly++)for(unsigned lv=0;lv<5;lv++) {
        unsigned w=19>>lv,h=13>>lv;if(!w)w=1;if(!h)h=1;size_t row=((w+3)/4)*16,n=row*((h+3)/4);
        uint8_t *blocks=malloc(n);for(size_t i=0;i<n;i+=16)memcpy(blocks+i,red,16);
        assert(!nvn_swizzle(&t.d,lv,ly,blocks,row,storage));free(blocks);
    }
    unsigned levels[]={0,2,4},layers[]={1,2,0};
    for(unsigned pass=0;pass<3;pass++) {
        view_t v={.set_format=1,.format=0x2f,.set_levels=1,.base_level=levels[pass],.set_layers=1,.min_layer=layers[pass],.nlayers=1};
        vkimg_t *shadow=NULL;assert(vk_bc_target(0,&t,&v,&shadow));
        unsigned w=19>>levels[pass],h=13>>levels[pass];if(!w)w=1;if(!h)h=1;
        assert(shadow->w==(w+3)/4 && shadow->h==(h+3)/4 && vk_view_layers==1 && vk_view_fmt==raw.vk);
        uint8_t *gpu=(uint8_t *)(uintptr_t)shadow->img;assert(!memcmp(gpu,red,16));
        memcpy(gpu,blue,16); // simulated shader overwrites one block; LOAD must preserve the rest
        vk_bc_flush_targets();
        assert(last_region.imageSubresource.mipLevel==levels[pass] && last_region.imageSubresource.baseArrayLayer==layers[pass]);
        assert(last_region.imageExtent.width==w && last_region.imageExtent.height==h && last_bytes==w*h*4);
        for(unsigned y=0;y<h;y++)for(unsigned x=0;x<w;x++) {
            uint8_t *p=last_upload+(y*w+x)*4;
            assert(p[3]==255 && p[1]==0);assert(x<4 && y<4 ? p[0]==0 && p[2]==255 : p[0]==255 && p[2]==0);
        }
        size_t row=shadow->w*16,n=row*shadow->h;uint8_t *check=malloc(n);
        assert(!nvn_deswizzle(&t.d,levels[pass],layers[pass],storage,check,row));assert(!memcmp(check,blue,16));
        for(size_t i=16;i<n;i+=16)assert(!memcmp(check+i,red,16));free(check);
        assert(base.gpu_w && base.pkg_stamp==123 && !base.pkg_released);
    }
    // Same shadow shape is cached, but its source bytes are loaded again.
    view_t v={.set_format=1,.format=0x2f,.set_levels=1,.base_level=4,.set_layers=1,.min_layer=0,.nlayers=1};vkimg_t *shadow;
    assert(vk_bc_target(0,&t,&v,&shadow));assert(created==2);assert(!memcmp((void *)(uintptr_t)shadow->img,blue,16));vk_bc_flush_targets();
    assert(snapshots==4 && uploads==4 && release_count==4 && freed_views==1);
    vk_bc_flush_targets();assert(snapshots==4);
    tex_t unsupported=t;unsupported.d.target=2;assert(!vk_bc_target(0,&unsupported,&v,&shadow));
    bc.bc_decode=0;assert(!vk_bc_target(0,&t,&v,&shadow));bc.bc_decode=1;
    for(unsigned i=0;i<nalloc;i++)free(allocations[i]);
    img_drop(g_bc_target[0].shadow);free(storage);
    assert(g_img_n==0 && g_img_bytes==0);
    puts("generated BC targets, partial writes, mips, layers and cache reuse passed");
}
'''
        with tempfile.TemporaryDirectory() as folder:
            src=Path(folder)/'targets.c';src.write_text(code);exe=Path(folder)/'targets'
            subprocess.run(['cc','-std=c11','-O1','-fno-strict-aliasing','-I',str(DM/'third_party/vulkan-headers/include'),
                            '-I',str(DM/'gfx/tex'),str(src),str(DM/'gfx/tex/nvn_bc.c'),str(DM/'gfx/tex/nvn_deswizzle.c'),
                            str(DM/'gfx/nvn/nvn_tex.c'),'-o',str(exe)],check=True)
            result=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('partial writes, mips, layers and cache reuse passed',result.stdout)
