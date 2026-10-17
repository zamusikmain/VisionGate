"""Run the reviewed OpenCV NanoDet COCO baseline locally; never a sticker classifier."""
import hashlib
import argparse
import importlib.util
import json
from pathlib import Path
import time
import zipfile

import cv2
import numpy as np

from backend.gate.samsung_paths import PROJECT_ROOT,input_archives
from backend.gate.image_input import read_image


def run(name='nanodet'):
    root=PROJECT_ROOT/('data/Samsung/models/'+name)
    helper=root/(name+'.py');weight=root/('object_detection_'+name+'_2022nov.onnx')
    hashes=('5ba84922eaefdc48d0066cffdfb721d0d434c5f3b92213563161e00da26cea1b','4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186') if name=='nanodet' else ('538b1961890f8112e2851c3f01624be1cf6f5120a27ce8da9b390c73a0f5ada1','c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063')
    for path,digest in zip((helper,weight),hashes):
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('MODEL_HASH_MISMATCH')
    spec=importlib.util.spec_from_file_location('reviewed_opencv_nanodet',helper)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    model=module.NanoDet(str(weight)) if name=='nanodet' else module.YoloX(str(weight))
    old=json.loads((PROJECT_ROOT/'reports/samsung-v03/final/results.json').read_text(encoding='utf-8'))
    sources={p.name:p for p in input_archives()}
    entries={e['sha256']:e for e in old['intake']['files'] if e.get('sha256')}
    rows=[];dest=PROJECT_ROOT/('reports/samsung-pretrained/'+name+'-diagnostics');dest.mkdir(parents=True,exist_ok=True)
    for case in old['cases']:
        for photo in case['photos']:
            entry=entries[photo['sha256']]
            with zipfile.ZipFile(sources[entry['archive']]) as z:data=z.read(entry['path'])
            assert hashlib.sha256(data).hexdigest()==photo['sha256']
            image=read_image(data);start=time.perf_counter()
            if name=='nanodet':
                # Match the official demo: RGB plus aspect-preserving black letterbox.
                scale=416/max(image.shape[:2]);nw=max(1,int(image.shape[1]*scale));nh=max(1,int(image.shape[0]*scale))
                left=(416-nw)//2;top=(416-nh)//2
                resized=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2RGB),(nw,nh),interpolation=cv2.INTER_AREA)
                padded=cv2.copyMakeBorder(resized,top,416-nh-top,left,416-nw-left,cv2.BORDER_CONSTANT,value=0)
                model.net.setInput(model.pre_process(padded))
                tensors=model.net.forward(model.net.getUnconnectedOutLayersNames())
                # OpenCV 5 reports classes first, then distributions. The upstream
                # helper expects alternating tensors. Pair by shape, never names/IDs.
                classes=sorted([a for a in tensors if a.shape[-1]==80],key=lambda a:-a.shape[-2])
                boxes={a.shape[-2]:a for a in tensors if a.shape[-1]==32}
                pred=model.post_process([a for cls in classes for a in (cls,boxes[cls.shape[-2]])])
                elapsed=time.perf_counter()-start
            else:
                scale=640/max(image.shape[:2]);nw=int(image.shape[1]*scale);nh=int(image.shape[0]*scale)
                padded=np.full((640,640,3),114.,np.float32)
                padded[:nh,:nw]=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2RGB),(nw,nh)).astype(np.float32)
                start=time.perf_counter();pred=model.infer(padded);elapsed=time.perf_counter()-start
            detections=[]
            for row in pred:
                if name=='yolox':bbox=[float(row[0]/scale),float(row[1]/scale),float(row[2]/scale),float(row[3]/scale)]
                else:
                    bbox=[float(np.clip((row[0]-left)*image.shape[1]/nw,0,image.shape[1])),float(np.clip((row[1]-top)*image.shape[0]/nh,0,image.shape[0])),
                          float(np.clip((row[2]-left)*image.shape[1]/nw,0,image.shape[1])),float(np.clip((row[3]-top)*image.shape[0]/nh,0,image.shape[0]))]
                detections.append(dict(bbox=bbox,score=float(row[4]),class_id=int(row[5])))
                cv2.rectangle(image,(int(bbox[0]),int(bbox[1])),(int(bbox[2]),int(bbox[3])),(0,0,255),3)
                cv2.putText(image,str(int(row[5]))+' '+str(round(float(row[4]),2)),(int(bbox[0]),max(30,int(bbox[1]))),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,255),2)
            scale=min(1,1400/max(image.shape[:2]));image=cv2.resize(image,None,fx=scale,fy=scale)
            cv2.imencode('.jpg',image)[1].tofile(str(dest/(photo['sha256']+'.jpg')))
            # Case metadata is attached after pixel-only inference.
            rows.append(dict(sha256=photo['sha256'],case_id=case['case_id'],role=photo['role'],seconds=elapsed,detections=detections))
            print(case['case_id'],photo['role'],[(d['class_id'],round(d['score'],2)) for d in detections],flush=True)
    (dest.parent/(name+'-results.json')).write_text(json.dumps(dict(rows=rows,inference_seconds=sum(r['seconds'] for r in rows),threshold=.35,iou_threshold=.6 if name=='nanodet' else .5),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',choices=['nanodet','yolox'],default='nanodet');a=p.parse_args();run(a.model)
