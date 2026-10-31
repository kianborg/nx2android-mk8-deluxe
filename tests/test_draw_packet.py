"""Exercise one-shot draw packet output, pending uniform reads and capture bounds."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('cc'),'host C compiler required')
class DrawPacket(unittest.TestCase):
    def test_packet_contains_selected_draw_and_bounded_inputs(self):
        program=r'''
#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define VKLOG(...) do {if(0)printf(__VA_ARGS__);}while(0)
static unsigned char arena[4096];
static int vk_pool_of(uint64_t a,uint64_t n) {uint64_t lo=(uintptr_t)arena,hi=lo+sizeof arena;return a>=lo && a<=hi && n<=hi-a;}
static void vk_ubd_read(uint64_t a,uint64_t n,uint8_t *out) {memcpy(out,(void *)(uintptr_t)a,n);out[0]=0x7b;}
typedef struct {uint32_t fmt:8,offset:19,stream:5;} va_st;
typedef struct {int kind,reg;unsigned binding;} dmsv_bind;
enum {RK_CBUF=1};
typedef struct {uint64_t key;uint32_t local[3];int nbind;const dmsv_bind *b;} vkshader_t;
typedef struct {int prim,itype,count,base_vertex,instances;uint64_t ibuf,ind;} p_draw_idx;
static struct {
 vkshader_t *sh[3];int rast_discard,rt_has_col[8];uint32_t vattr[16];
 struct {uint64_t address,size;} vbuf[16];
 struct {unsigned stride,divisor;} vstream[16];
 struct {uint64_t addr,size;} ubo[3][16];
} S;
static uint64_t g_tex_frame=42;
#include "draw_packet.h"
int main(int argc,char **argv) {
 if(argc!=3)return 2;
 setenv("DM_ROOT",argv[1],1);setenv("DM_VK_DRAW_PACKET","123",1);
 for(unsigned i=0;i<sizeof arena;i++)arena[i]=(unsigned char)i;
 dmsv_bind binding={1,4,1};vkshader_t vs={.key=0x999,.local={17,0,0},.nbind=1,.b=&binding},fs={.key=0x456};S.sh[0]=&vs;S.sh[1]=&fs;S.rt_has_col[0]=1;
 va_st attr={.fmt=34,.offset=0,.stream=0};memcpy(&S.vattr[0],&attr,4);
 attr=(va_st){.fmt=37,.offset=4,.stream=3};memcpy(&S.vattr[4],&attr,4);
 S.vbuf[0].address=(uintptr_t)arena+128;S.vbuf[0].size=48;S.vstream[0].stride=12;
 S.vbuf[3].address=(uintptr_t)arena+256;S.vbuf[3].size=16;S.vstream[3].stride=4;
 S.ubo[0][4].addr=(uintptr_t)arena+768;S.ubo[0][4].size=48;
 p_draw_idx draw={.prim=4,.itype=1,.count=3,.instances=1,.ibuf=(uintptr_t)arena+512};
 draw_packet(&draw); // wrong shader must not consume the one-shot request
 vs.key=0x123;
 if(!strcmp(argv[2],"large"))S.vbuf[0].size=2*1024*1024;
 draw_packet(&draw);
 memset(arena,0,sizeof arena);draw_packet(&draw); // must not overwrite the packet
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'packet.c').write_text(program)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'nxnative/dm/android'),str(p/'packet.c'),'-o',str(p/'packet')],check=True)
            for mode in ['good','large']:
                out=p/mode;out.mkdir()
                subprocess.run([str(p/'packet'),str(out),mode],check=True)
                data=json.loads((out/'draw_packet.json').read_text())
                self.assertEqual(data['vertex_shader'],'0000000000000123')
                self.assertEqual(data['present'],42)
                self.assertEqual(data['attributes'][1],{'location':4,'format':37,'stream':3,'offset':4})
                self.assertEqual(data['uniforms'][0]['register'],4)
                self.assertEqual((out/'draw_packet_uniform_04.bin').read_bytes(),bytes([0x7b])+bytes(range(1,48)))
                self.assertEqual((out/'draw_packet_indices.bin').read_bytes(),bytes(range(6)))
                self.assertEqual(data['complete'],mode=='good')
                if mode=='good':self.assertEqual((out/'draw_packet_stream_00.bin').read_bytes(),bytes(range(128,176)))
                else:self.assertFalse((out/'draw_packet_stream_00.bin').exists())
