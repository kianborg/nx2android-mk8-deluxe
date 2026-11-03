#!/usr/bin/env python3
"""Compare captured MK8 diffuse light inputs with target zero (requires NumPy).

Reference equations for VS 35696712904ac390 / FS 30b45cd2223d3964. This is
not GPU execution or a rasterizer: coverage, depth/stencil, other light shaders,
FMA precision and driver sampling are not reproduced. A discrepancy is evidence
to investigate, not proof of a driver bug. Capture data stays outside the repo.
"""
import argparse
import json
from pathlib import Path
import re

import numpy as np

WHEEL_FS = '30b45cd2223d3964'


def decode_normals(packed):
    # Vulkan format 64, A2B10G10R10_UNORM_PACK32; sampled RGB, alpha unused.
    return np.stack([((packed >> shift) & 1023)/1023.0 for shift in (0,10,20)],axis=-1)


def decode_lights(packed):
    channels=[]
    for shift, mantissa in ((0,6),(11,6),(22,5)):
        value=(packed >> shift) & ((1 << (mantissa+5))-1)
        exponent=value >> mantissa; fraction=value & ((1 << mantissa)-1)
        channel=np.where(exponent==0, fraction*2.0**(-14-mantissa),
                         (1+fraction/2.0**mantissa)*2.0**(exponent.astype(float)-15))
        channel=np.where(exponent==31,np.where(fraction==0,np.inf,np.nan),channel)
        channels.append(channel)
    return np.stack(channels,axis=-1)


def diffuse(normal, linear_depth, camera, light):
    """Unoccluded diffuse equations from the recorded wheel SPIR-V, in float64."""
    h,w=linear_depth.shape;y,x=np.mgrid[:h,:w]
    ndcx=2*(x+.5)/w-1;ndcy=1-2*(y+.5)/h
    ray=np.stack((-ndcx*camera[11,0]-camera[11,2],
                  ndcy*camera[11,1]-camera[11,3],np.ones((h,w))),axis=-1)
    distance_z=linear_depth*camera[10,1]+camera[10,0]
    delta=-distance_z[...,None]*ray-light[3,:3]
    distance=np.linalg.norm(delta,axis=-1)
    with np.errstate(divide='ignore',invalid='ignore'):
        lambert=np.clip(-np.sum((2*normal-1)*delta,axis=-1)/distance,0,1)
    falloff=np.clip(1-distance*light[1,3],0,1)**light[3,3]
    return lambert[...,None]*falloff[...,None]*light[1,:3]


def read_image(folder,index,dtype):
    name=f'pass_{index:02d}.ppm'
    with (folder/name).open('rb') as f:
        if f.readline()!=b'P6\n':raise ValueError(f'Unsupported preview header: {name}')
        w,h=map(int,f.readline().split())
        if f.readline()!=b'255\n' or not 0<w*h<=4_000_000:raise ValueError('Invalid dimensions/header')
    suffix='.u32' if dtype=='light' else '.raw'
    kind='<f2' if dtype=='depth' else '<u4'
    path=folder/(name+suffix)
    if path.stat().st_size!=w*h*np.dtype(kind).itemsize:raise ValueError(f'Raw size mismatch: {path.name}')
    return np.fromfile(path,dtype=kind).reshape(h,w)


def analyze(folder):
    folder=Path(folder);log=(folder/'log.txt').read_text(errors='replace')
    inputs={};targets={};uniforms={};draws={}
    for f,pa,index,binding,fmt in re.findall(r'pass capture input: present (\d+) pass (\d+) dump (\d+) binding (\d+) format (\d+)',log):
        inputs.setdefault((int(f),int(pa)),{})[int(fmt)]=int(index)
    for f,pa,index in re.findall(r'pass capture: present (\d+) pass (\d+) dump (\d+) target 0 layer 0',log):
        targets[int(f),int(pa)]=int(index)
    for f,pa,d,vs,fs in re.findall(r'pass capture draw: present (\d+) pass (\d+) draw (\d+) VS (\w+) FS (\w+)',log):
        if vs=='35696712904ac390' and fs==WHEEL_FS:draws[int(f),int(pa),int(d)]=fs
    for f,pa,d,reg,words in re.findall(r'pass capture uniform: present (\d+) pass (\d+) draw (\d+) stage 1 binding \d+ c(\d+) address \w+ size \d+ bytes \d+ hex ([0-9a-f ]+)',log):
        uniforms[int(f),int(pa),int(d),int(reg)]=np.array([int(v,16) for v in words.split()],dtype='<u4').view('<f4').astype(float)
    result=[]
    for key,images in sorted(inputs.items()):
        if not {64,76}<=images.keys() or key not in targets:continue
        normal=decode_normals(read_image(folder,images[64],'normal'))
        depth=read_image(folder,images[76],'depth').astype(float)
        actual=decode_lights(read_image(folder,targets[key],'light'))
        if normal.shape!=actual.shape or depth.shape!=actual.shape[:2]:raise ValueError('Sampling scale changed; model requires matching input/output dimensions')
        prediction=np.zeros_like(actual);count=0
        for draw in sorted(k for k in draws if k[:2]==key):
            camera=uniforms.get((*draw,0));light=uniforms.get((*draw,1))
            if camera is None or light is None or camera.size<56 or light.size<24:raise ValueError('Incomplete fragment uniform snapshot')
            if not np.all(np.isfinite(camera)) or not np.all(np.isfinite(light)):raise ValueError('Nonfinite uniform snapshot')
            prediction+=diffuse(normal,depth,camera[:56].reshape(14,4),light[:24].reshape(6,4));count+=1
        if not count:continue
        # Actual target includes other lights. Flag strong reference light that
        # is absent even from that sum; geometry/occlusion must still be checked.
        valid=np.all(np.isfinite(prediction),axis=-1)&np.all(np.isfinite(actual),axis=-1)
        strong=valid&(prediction[...,1]>1)
        low=strong&(actual[...,1]<prediction[...,1]*.1)
        result.append({'effect_present':key[0],'final_frame':key[0]+1,'pass':key[1],
                       'width':depth.shape[1],'height':depth.shape[0],'diffuse_draws':count,
                       'strong_green_pixels':int(strong.sum()),'underlit_candidates':int(low.sum()),
                       'predicted_green_sum':float(np.nansum(prediction[...,1])),
                       'actual_green_sum':float(np.nansum(actual[...,1]))})
    if not result:raise ValueError('No complete wheel-inputs passes found; motion/status logs alone lack sampled inputs.')
    return {'method':'float64 unoccluded diffuse reference; not full GPU/raster replay',
            'limitations':['Assumes observed nearest sampling, identity normal RGB swizzle, matching dimensions and full viewport',
                           'Uses last sampled images and CPU uniforms; cannot prove actual GPU input contents',
                           'Candidate pixels may be occluded or outside the actual light mesh; inspect mesh/depth before diagnosing'],
            'passes':result}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path);args=parser.parse_args()
    try:
        report=analyze(args.folder)
        path=args.folder/'wheel-inputs-report.json';path.write_text(json.dumps(report,indent=2)+'\n')
        print(path)
    except (ValueError,OSError) as error:parser.exit(1,f'{error}\n')


if __name__=='__main__':main()
