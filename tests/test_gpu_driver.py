"""Optional driver package validation and runtime loader routing."""
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile
from porter.gpu_driver import unpack_driver
from porter.upstream import BuildError

ROOT=Path(__file__).resolve().parents[1]

class DriverPackage(unittest.TestCase):
    def test_arm64_package_and_notice_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);elf=bytearray(64);elf[:6]=b'\x7fELF\x02\x01';struct.pack_into('<HH',elf,16,3,183)
            def make(entries):
                with zipfile.ZipFile(p/'driver.zip','w') as z:
                    for name,data in entries:z.writestr(name,data)
            make([('meta.json',json.dumps({'libraryName':'libvulkan_freedreno.so'})),('nested/libvulkan_freedreno.so',elf),('LICENSE','MIT notice')])
            name,libs,assets=unpack_driver(p/'driver.zip',p/'out')
            self.assertEqual(name,'libnx2a_turnip.so');self.assertEqual(libs[0].read_bytes(),elf)
            self.assertEqual(len(assets),2)
            make([('meta.json',json.dumps({'libraryName':'vulkan.ad07xx.so'})),('vulkan.ad07xx.so',elf)])
            name,libs,_=unpack_driver(p/'driver.zip',p/'renamed')
            self.assertEqual(name,'libnx2a_turnip.so')
            self.assertEqual(libs[0].name,'libnx2a_turnip.so')
            make([('libvulkan_freedreno.so',b'not ELF')])
            with self.assertRaises(BuildError):unpack_driver(p/'driver.zip',p/'bad')
            other=bytearray(elf);struct.pack_into('<H',other,18,62)
            make([('libvulkan_freedreno.so',other)])
            with self.assertRaisesRegex(BuildError,'ARM64'):unpack_driver(p/'driver.zip',p/'x86')
            make([('libdmhost.so',elf)])
            with self.assertRaisesRegex(BuildError,'reserved'):unpack_driver(p/'driver.zip',p/'reserved')
            make([('libvulkan_freedreno.so',elf),('sub/libvulkan_freedreno.so',elf)])
            with self.assertRaisesRegex(BuildError,'duplicate'):unpack_driver(p/'driver.zip',p/'duplicate')
            make([('meta.json','[]'),('libvulkan_freedreno.so',elf)])
            with self.assertRaisesRegex(BuildError,'object'):unpack_driver(p/'driver.zip',p/'metadata')

    @unittest.skipUnless(shutil.which('cc'),'host C compiler required')
    def test_system_custom_and_invalid_loader_selection(self):
        source=(ROOT/'nxnative/dm/android/vk_loader.c').read_text().replace('#include "gfx_vk.h"','').replace('#include <dlfcn.h>','')
        stub=r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define RTLD_NOW 2
#define RTLD_LOCAL 0
#define VKLOG(...) ((void)0)
#define die(...) do {fprintf(stderr,__VA_ARGS__);exit(9);}while(0)
typedef struct {const char *dli_fname;} Dl_info;
static int custom_calls,opens;
static const char *dlerror(void){return "test failure";}
static void *dlopen(const char *path,int flags){(void)flags;opens++;assert(!strcmp(path,"libvulkan.so") || !strcmp(path,"/apk/lib/arm64/libadrenotools.so"));return (void *)1;}
static int dladdr(const void *p,Dl_info *info){(void)p;info->dli_fname="/apk/lib/arm64/libdmhost.so";return 1;}
static void *custom(int mode,int flags,const char *tmp,const char *hooks,const char *driverdir,const char *name,const char *redirect,void **mapping){
 assert(mode==2 && flags==1 && !tmp && !redirect && !mapping);
 assert(!strcmp(hooks,"/apk/lib/arm64/") && !strcmp(driverdir,hooks));assert(!strcmp(name,"libnx2a_turnip.so"));custom_calls++;return (void *)2;
}
static void *dlsym(void *handle,const char *name){(void)handle;return !strcmp(name,"adrenotools_open_libvulkan")?(void *)&custom:(void *)3;}
'''+source+r'''
int main(int argc,char **argv){
 if(argc>1){setenv("DM_VK_DRIVER",argv[1],1);vk_open_loader();return 0;}
 unsetenv("DM_VK_DRIVER");assert(vk_open_loader()==(void *)1 && opens==1 && !custom_calls);
 setenv("DM_VK_DRIVER","system",1);assert(vk_open_loader()==(void *)1 && !custom_calls);
 setenv("DM_VK_DRIVER","turnip",1);assert(vk_open_loader()==(void *)2 && custom_calls==1);
 setenv("DM_VK_DRIVER","libnx2a_turnip.so",1);assert(vk_open_loader()==(void *)2 && custom_calls==2);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'loader.c').write_text(stub)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'loader.c'),'-o',str(p/'loader')],check=True)
            subprocess.run([str(p/'loader')],check=True)
            for name in ['../libevil.so','/sdcard/driver.so','lib../evil.so','garbage']:
                result=subprocess.run([str(p/'loader'),name],capture_output=True,text=True)
                self.assertEqual(result.returncode,9)
