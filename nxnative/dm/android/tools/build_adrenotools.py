#!/usr/bin/env python3
"""Build the optional AdrenoTools helpers with the porter's NDK (no CMake)."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys


def build(ndk, output):
    source=Path(__file__).resolve().parents[2]/'third_party/adrenotools'
    host='windows-x86_64' if os.name=='nt' else 'darwin-x86_64' if sys.platform=='darwin' else 'linux-x86_64'
    bins=Path(ndk)/'toolchains/llvm/prebuilt'/host/'bin';exe='.exe' if os.name=='nt' else ''
    cpp=bins/('clang++'+exe);cc=bins/('clang'+exe)
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    names=['adrenotools','hook_impl','main_hook','file_redirect_hook','gsl_alloc_hook']
    digest=hashlib.sha256(str(Path(ndk).resolve()).encode()+Path(__file__).read_bytes())
    for p in sorted(source.rglob('*')):
        if p.is_file():digest.update(p.relative_to(source).as_posix().encode()+p.read_bytes())
    stamp=output/'build.sha256';signature=digest.hexdigest()
    if stamp.exists() and stamp.read_text()==signature and all((output/f'lib{n}.so').exists() for n in names):return
    common=['--target=aarch64-linux-android31','-O2','-fPIC','-shared','-Wl,--no-undefined','-Wl,-z,max-page-size=16384',
            '-I',str(source),'-I',str(source/'include'),'-I',str(source/'lib/linkernsbypass')]
    linker=[source/'lib/linkernsbypass'/n for n in ['android_linker_ns.cpp','elf_soname_patcher.cpp']]
    jobs=[('adrenotools',[source/'src/driver.cpp',source/'src/bcenabler.cpp',*linker]),
          ('hook_impl',[source/'src/hook/hook_impl.cpp',*linker])]
    for name,files in jobs:
        subprocess.run([str(cpp),*common,'-std=c++17','-static-libstdc++',*(['-fvisibility=hidden'] if name=='hook_impl' else []),'-Wl,--exclude-libs,ALL',
                        '-Wl,-soname,lib'+name+'.so',*map(str,files),'-landroid','-ldl','-llog','-o',str(output/f'lib{name}.so')],check=True)
    for name in names[2:]:
        subprocess.run([str(cc),*common,'-fvisibility=hidden','-Wl,-z,global','-Wl,-soname,lib'+name+'.so',
                        str(source/f'src/hook/{name}.c'),'-L',str(output),'-lhook_impl','-o',str(output/f'lib{name}.so')],check=True)
    stamp.write_text(signature)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ndk',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();build(args.ndk,args.out)
