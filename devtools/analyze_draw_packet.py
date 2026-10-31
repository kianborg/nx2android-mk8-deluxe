#!/usr/bin/env python3
"""Reference linear-blend reconstruction of the inspected MK8 driver draw packet.

This reconstructs positions on the CPU, not the complete SPIR-V program or GPU
reads. Extract the packet archive first; generated reports/images stay beside it.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import struct


def reconstruct(folder):
    folder=Path(folder).resolve()
    manifest=json.loads((folder/'draw_packet.json').read_text())
    if manifest.get('version')!=1 or not manifest.get('complete'):
        raise ValueError('A complete v1 draw packet is required.')
    if manifest.get('vertex_shader')!='45539f60801ff5e3':
        raise ValueError('This reference model is only established for shader 45539f60801ff5e3.')

    def blob(name):
        path=(folder/name).resolve()
        if not path.is_relative_to(folder) or path.stat().st_size>1024*1024:
            raise ValueError('Packet file escapes the folder or exceeds the capture limit.')
        return path.read_bytes()

    attrs={a['location']:a for a in manifest['attributes']}
    streams={s['stream']:s for s in manifest['streams']}
    def attribute(location, fmt, width):
        a=attrs[location];s=streams[a['stream']]
        if a['format']!=fmt or not s['saved'] or s['divisor'] or s['stride']<width:
            raise ValueError(f'Unsupported format, stride or divisor at location {location}.')
        data=blob(s['file'])
        if len(data)!=s['size']:raise ValueError('Stream size does not match manifest.')
        return data,s['stride'],a['offset']

    positions,ps,po=attribute(0,0x22,12)
    weights,ws,wo=attribute(4,0x25,4)
    indices,bs,bo=attribute(6,0x27,4)
    palette=next(u for u in manifest['uniforms'] if u['binding']==1)
    if not palette['saved']:raise ValueError('Bone palette is absent.')
    bones=blob(palette['file'])
    if len(bones)!=palette['size'] or len(bones)%48:raise ValueError('Invalid 3x4 bone palette.')
    matrices=struct.unpack('<'+'f'*(len(bones)//4),bones)
    if not all(math.isfinite(x) for x in matrices):raise ValueError('Nonfinite bone matrix.')
    bone_count=len(bones)//48
    types={0:('B',1),1:('H',2),2:('I',4)}
    code,size=types[manifest['index_type']];raw=blob('draw_packet_indices.bin')
    if len(raw)!=manifest['count']*size:raise ValueError('Index count does not match manifest.')
    order=struct.unpack('<'+code*manifest['count'],raw)
    if not order:raise ValueError('Empty draw.')
    used=sorted(set(order));points={};sums=Counter();weighted_invalid=0
    for index in used:
        v=index+manifest['base_vertex']
        if v<0 or v*ps+po+12>len(positions) or v*ws+wo+4>len(weights) or v*bs+bo+4>len(indices):
            raise ValueError(f'Vertex {v} is outside a captured stream.')
        point=(*struct.unpack_from('<3f',positions,v*ps+po),1.)
        w=weights[v*ws+wo:v*ws+wo+4];ids=indices[v*bs+bo:v*bs+bo+4]
        sums[sum(w)]+=1;world=[0.,0.,0.]
        for weight,bone in zip(w,ids):
            if not weight:continue
            if bone>=bone_count:
                weighted_invalid+=1;continue
            for row in range(3):
                world[row]+=(weight/255.)*sum(matrices[bone*12+row*4+k]*point[k] for k in range(4))
        if not all(math.isfinite(x) for x in world):raise ValueError('Nonfinite reconstructed position.')
        points[index]=world
    report={'method':'CPU reference linear-blend skinning, not full SPIR-V execution or GPU readback',
            'present':manifest['present'],'vertex_shader':manifest['vertex_shader'],
            'index_count':len(order),'index_range':[min(order),max(order)],'referenced_vertices':len(used),
            'bone_count':bone_count,'weight_sum_histogram':dict(sorted(sums.items())),
            'invalid_weighted_bone_references':weighted_invalid,
            'world_bounds':[[min(p[k] for p in points.values()),max(p[k] for p in points.values())] for k in range(3)]}
    return report,points,order


def render(points,order,output):
    from PIL import Image,ImageDraw
    for name,a,b in [('xy',0,1),('xz',0,2),('zy',2,1)]:
        lo=[min(p[k] for p in points.values()) for k in (a,b)]
        hi=[max(p[k] for p in points.values()) for k in (a,b)]
        scale=650/max(hi[0]-lo[0],hi[1]-lo[1],1e-9)
        projected={i:(50+(p[a]-lo[0])*scale,700-(p[b]-lo[1])*scale) for i,p in points.items()}
        image=Image.new('RGB',(800,800),'#10151c');draw=ImageDraw.Draw(image)
        for i in range(0,len(order)-2,3):
            tri=[projected[x] for x in order[i:i+3]]
            draw.line(tri+[tri[0]],fill='#db42dc',width=1)
        image.save(output/f'cpu-skin-{name}.png')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        report,points,order=reconstruct(args.folder)
        output=args.output or args.folder/'analysis';output.mkdir(parents=True,exist_ok=True)
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        render(points,order,output)
        print(json.dumps(report,indent=2))
    except (OSError,ValueError,KeyError,StopIteration) as e:
        parser.exit(1,f'Error: {e}\n')

if __name__=='__main__':main()
