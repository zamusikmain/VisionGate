"""Offline review/export of LOCAL visual annotations; never predicts case status.

Unreviewed classes are unknown, not negative examples. Export requires exhaustive
review of the selected classes and case-group disjointness, including shared
physical identities when known. Augmentations stay within the training split.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import random
import shutil

CLASSES=('box','factory_label','identification_region','phone_screen')


def validate(data):
    if data.get('classes')!=list(CLASSES):raise ValueError('UNEXPECTED_CLASSES')
    seen=set()
    for p in data['images']:
        digest=p['sha256']
        if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest) or digest in seen:
            raise ValueError('INVALID_OR_DUPLICATE_DIGEST')
        seen.add(digest)
        if not p.get('case_group'):raise ValueError('CASE_GROUP_REQUIRED')
        if not set(p.get('reviewed_classes',[]))<=set(CLASSES):raise ValueError('INVALID_REVIEW')
        for o in p.get('objects',[]):
            if o['class'] not in CLASSES:raise ValueError('INVALID_CLASS')
            x1,y1,x2,y2=o['bbox']
            if not (0<=x1<x2<=1 and 0<=y1<y2<=1):raise ValueError('INVALID_BBOX')
    return data


def split_groups(images,seed=20261017,val_fraction=.3):
    groups=sorted({p['case_group'] for p in images})
    if len(groups)<3:raise ValueError('INSUFFICIENT_INDEPENDENT_GROUPS')
    random.Random(seed).shuffle(groups)
    n=max(1,min(len(groups)-1,round(len(groups)*val_fraction)))
    validation=set(groups[:n])
    return {p['sha256']:('val' if p['case_group'] in validation else 'train') for p in images}


def export_yolo(manifest,output,classes=CLASSES,seed=20261017):
    data=validate(json.loads(Path(manifest).read_text(encoding='utf-8')))
    selected=tuple(classes)
    if not selected or not set(selected)<=set(CLASSES):raise ValueError('INVALID_CLASS_SELECTION')
    # Never export a proposal or an incompletely reviewed image as training truth.
    images=[p for p in data['images'] if set(selected)<=set(p.get('reviewed_classes',[]))]
    split=split_groups(images,seed)
    output=Path(output).resolve()
    if output.exists():raise ValueError('OUTPUT_EXISTS_KEEP_PRIOR_VERSIONS')
    output.mkdir(parents=True)
    for p in images:
        source=Path(p['image'])
        if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest()!=p['sha256']:
            raise ValueError('SOURCE_CHANGED')
        part=split[p['sha256']];folder=output/'images'/part;folder.mkdir(parents=True,exist_ok=True)
        labels=output/'labels'/part;labels.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,folder/(p['sha256']+'.jpg'))
        rows=[]
        for o in p.get('objects',[]):
            if o['class'] not in selected:continue
            if o.get('status')!='reviewed':raise ValueError('UNREVIEWED_OBJECT')
            x1,y1,x2,y2=o['bbox'];rows.append(f'{selected.index(o["class"])} {(x1+x2)/2:.8f} {(y1+y2)/2:.8f} {x2-x1:.8f} {y2-y1:.8f}')
        (labels/(p['sha256']+'.txt')).write_text('\n'.join(rows),encoding='utf-8')
    metadata=dict(seed=seed,classes=list(selected),splits=split,groups={p['sha256']:p['case_group'] for p in images},
                  notice='Private pilot annotations. Grouped development split, not independent Samsung accuracy.')
    (output/'split.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    # Use JSON quoted paths/names, also valid in YAML, for Windows portability.
    config='path: '+json.dumps(output.as_posix())+'\ntrain: images/train\nval: images/val\nnames:\n'
    config+=''.join(f'  {i}: {json.dumps(c)}\n' for i,c in enumerate(selected))
    (output/'dataset.yaml').write_text(config,encoding='utf-8')
    return metadata


def editor(manifest,output):
    data=validate(json.loads(Path(manifest).read_text(encoding='utf-8')))
    for p in data['images']:
        raw=Path(p['image']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=p['sha256']:raise ValueError('SOURCE_CHANGED')
        p['data_url']='data:image/jpeg;base64,'+base64.b64encode(raw).decode('ascii')
    # Standalone file: no server, CDN, network requests, analytics or external AI.
    html='''<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; img-src data:; style-src 'unsafe-inline'">
<title>PRIVATE local object annotation</title><style>body{font:16px sans-serif}canvas{max-width:95vw;max-height:78vh;border:1px solid;touch-action:none}</style>
<p>PRIVATE. Draw normalized visible boxes only. A depiction is not proof of a physical box. Do not infer hidden label boundaries. Pending class review is UNKNOWN. No final approval labels.</p>
<button id="prev">Previous</button><button id="next">Next</button><select id="kind"></select><button id="undo">Undo box</button><button id="review">Mark selected class exhaustively reviewed</button><button id="save">Export JSON</button><p id="status"></p><canvas id="canvas"></canvas>
<script>const data=DATA;let index=0,start=null;const c=document.getElementById('canvas'),ctx=c.getContext('2d'),im=new Image(),kind=document.getElementById('kind');data.classes.forEach(k=>kind.add(new Option(k,k)));
function draw(){ctx.drawImage(im,0,0,c.width,c.height);const p=data.images[index];for(const o of p.objects){const [x,y,r,b]=o.bbox;ctx.strokeStyle=o.status==='reviewed'?'#00ff00':'#ffaa00';ctx.lineWidth=3;ctx.strokeRect(x*c.width,y*c.height,(r-x)*c.width,(b-y)*c.height);ctx.fillStyle=ctx.strokeStyle;ctx.fillText(o.class,x*c.width,y*c.height+18)}document.getElementById('status').textContent=(index+1)+'/'+data.images.length+' reviewed: '+JSON.stringify(p.reviewed_classes||[])}
function load(){im.onload=()=>{c.width=im.width;c.height=im.height;draw()};im.src=data.images[index].data_url}function point(e){const r=c.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))]}
c.onpointerdown=e=>{start=point(e);c.setPointerCapture(e.pointerId)};c.onpointerup=e=>{if(!start)return;const q=point(e),b=[Math.min(start[0],q[0]),Math.min(start[1],q[1]),Math.max(start[0],q[0]),Math.max(start[1],q[1])];start=null;if(b[2]<=b[0]||b[3]<=b[1])return;data.images[index].objects.push({class:kind.value,bbox:b,status:'reviewed',source:'local visual reviewer'});draw()};
document.getElementById('prev').onclick=()=>{index=(index+data.images.length-1)%data.images.length;load()};document.getElementById('next').onclick=()=>{index=(index+1)%data.images.length;load()};document.getElementById('undo').onclick=()=>{data.images[index].objects.pop();draw()};document.getElementById('review').onclick=()=>{const p=data.images[index];p.reviewed_classes=[...new Set([...(p.reviewed_classes||[]),kind.value])];draw()};
document.getElementById('save').onclick=()=>{const result=JSON.parse(JSON.stringify(data));result.images.forEach(p=>delete p.data_url);const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));a.download='annotations-reviewed.json';a.click();URL.revokeObjectURL(a.href)};load();</script>'''
    Path(output).write_text(html.replace('DATA',json.dumps(data).replace('<','\\u003c')),encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['editor','export']);p.add_argument('manifest',type=Path);p.add_argument('output',type=Path);p.add_argument('--classes',nargs='+',choices=CLASSES,default=CLASSES)
    a=p.parse_args()
    if a.action=='editor':editor(a.manifest,a.output)
    else:export_yolo(a.manifest,a.output,a.classes)


if __name__=='__main__':main()
