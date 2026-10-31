"""Stripped native libraries must retain useful module-relative crash addresses."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'host C compiler required')
class CrashSymbols(unittest.TestCase):
    def test_hidden_native_symbol_and_raw_address(self):
        source = (ROOT/'nxnative/dm/host/crash.c').read_text()
        start = source.index('void crash_off(')
        function = source[start:source.index('// Frame pointer backtrace', start)]
        code = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>
typedef struct {const char *name;void *base;} module_t;
typedef struct {const char *dli_fname;void *dli_fbase;const char *dli_sname;void *dli_saddr;} Dl_info;
static module_t *module_of(void *a) {(void)a;return NULL;}
static int dladdr(void *a,Dl_info *di) {
    if ((uintptr_t)a==0x1128) {*di=(Dl_info){"/apk/libnx2a_turnip.so",(void *)0x1000,NULL,NULL};return 1;}
    if ((uintptr_t)a==0x2004) {*di=(Dl_info){"/lib/libc.so",(void *)0x1000,"known_function",(void *)0x2000};return 1;}
    return 0;
}
''' + function + r'''
int main(void) {crash_off("pc",0x1128);fputc('\n',stderr);crash_off("lr",0x2004);fputc('\n',stderr);crash_off("pc",0xdead);return 0;}
'''
        with tempfile.TemporaryDirectory() as folder:
            src=Path(folder)/'test.c';src.write_text(code);exe=Path(folder)/'test'
            subprocess.run(['cc',str(src),'-o',str(exe)],check=True)
            result=subprocess.run([str(exe)],capture_output=True,text=True,check=True)
            self.assertEqual(result.stderr,' pc=libnx2a_turnip.so+0x128\n lr=known_function+0x4\n pc=0xdead')
