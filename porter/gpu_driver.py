"""Package an explicit ARM64 Vulkan driver ZIP; normal ports keep system Vulkan."""
import json
from pathlib import Path
import re
import struct
import sys
import zipfile
from porter.upstream import BuildError, DM, nsp, say

HELPERS=('adrenotools','hook_impl','main_hook','file_redirect_hook','gsl_alloc_hook')


def unpack_driver(source, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    libraries={};assets=[];metadata={}
    try:
        with zipfile.ZipFile(source) as archive:
            members=archive.infolist()
            if sum(m.file_size for m in members)>256*1024*1024:
                raise BuildError('Vulkan driver ZIP exceeds 256 MiB uncompressed.')
            for entry in members:
                if entry.is_dir():continue
                name=Path(entry.filename.replace('\\','/')).name
                if name=='meta.json':
                    if entry.file_size>65536:raise BuildError('Vulkan driver metadata is too large.')
                    metadata=json.loads(archive.read(entry))
                if name.endswith('.so'):
                    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*\.so',name) or '..' in name or name in libraries or name in {f'lib{n}.so' for n in HELPERS}|{'libdmhost.so','libvulkan.so'}:
                        raise BuildError(f'Invalid, reserved or duplicate driver library: {name}')
                    if entry.file_size<64 or entry.file_size>128*1024*1024:raise BuildError(f'Invalid driver library size: {name}')
                    data=archive.read(entry)
                    if data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<HH',data,16)!=(3,183):
                        raise BuildError(f'Driver library is not an ARM64 ELF shared object: {name}')
                    path=output/name;path.write_bytes(data);libraries[name]=path
                elif name=='meta.json' or name.lower().startswith(('license','copying','notice')):
                    if entry.file_size>1024*1024:raise BuildError('Driver notice is too large.')
                    safe='notice-'+str(len(assets))+'.txt';path=output/safe;path.write_bytes(archive.read(entry));assets.append((f'vulkan-driver/{safe}',path))
    except (OSError,zipfile.BadZipFile,ValueError,TypeError) as e:
        raise BuildError(f'Cannot read Vulkan driver ZIP: {e}') from e
    if not isinstance(metadata,dict):raise BuildError('Vulkan driver metadata must be an object.')
    primary=metadata.get('libraryName','libvulkan_freedreno.so')
    if not isinstance(primary,str) or primary not in libraries:
        raise BuildError('Vulkan driver ZIP must contain its meta.json libraryName, or libvulkan_freedreno.so.')
    normalized='libnx2a_turnip.so'
    if normalized in libraries and primary!=normalized:raise BuildError('Driver ZIP collides with the packaged driver name.')
    primary_path=libraries.pop(primary)
    target=output/normalized
    if primary_path!=target:primary_path.replace(target)
    if any(not name.startswith('lib') for name in libraries):raise BuildError('Driver dependencies must use lib*.so names for Android APK extraction.')
    return normalized,[target,*libraries.values()],assets


def apk_args(source, ndk, output, log):
    output=Path(output)
    primary,libraries,assets=unpack_driver(source,output/'driver')
    helpers=output/'helpers'
    nsp.run([sys.executable,DM/'android/tools/build_adrenotools.py','--ndk',ndk,'--out',helpers],log)
    libraries.extend(helpers/f'lib{n}.so' for n in HELPERS)
    third=DM/'third_party/adrenotools'
    assets.extend([('vulkan-driver/adrenotools-LICENSE',third/'LICENSE'),
                   ('vulkan-driver/linkernsbypass-LICENSE',third/'lib/linkernsbypass/LICENSE')])
    args=[]
    for path in libraries:args+=['--extra-so',str(path)]
    for name,path in assets:args+=['--asset',f'{name}={path}']
    say(f'Custom Vulkan driver bundled: {primary}; system driver remains default. Set DM_VK_DRIVER={primary} in the installed env.txt to test it.')
    return args
