"""Isolated, offline YOLO localization benchmark; never a Samsung decision engine.

Install optional Ultralytics/PyTorch CPU in a SEPARATE environment. See the
Ultralytics AGPL/Enterprise terms before integration or distribution. No model
weights, corporate annotations or pictures belong in a release bundle.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import threading
import time


def runtime(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    os.environ['YOLO_CONFIG_DIR']=str((output/'settings').resolve())
    os.environ['YOLO_AUTOINSTALL']='false'
    os.environ['ULTRALYTICS_OFFLINE']='true'
    os.environ['WANDB_MODE']='disabled'
    os.environ['MPLCONFIGDIR']=str((output/'matplotlib').resolve())
    import torch
    from ultralytics import YOLO,settings
    disabled={k:False for k in ('sync','hub','comet','clearml','dvc','mlflow','neptune','raytune','wandb','tensorboard') if k in settings}
    disabled.update({k:str((output/k).resolve()) for k in ('datasets_dir','weights_dir','runs_dir')})
    settings.update(disabled)
    torch.set_num_threads(4)
    return YOLO


def benchmark(weights,manifest,output):
    import cv2
    import psutil
    from tools.samsung_visual_dataset import validate
    output=Path(output);YOLO=runtime(output)
    weights=Path(weights)
    if not weights.is_file():raise ValueError('LOCAL_WEIGHT_REQUIRED_NO_AUTO_DOWNLOAD')
    data=validate(json.loads(Path(manifest).read_text(encoding='utf-8')))
    process=psutil.Process();peak=[process.memory_info().rss];stop=threading.Event()
    def sample():
        while not stop.wait(.1):peak[0]=max(peak[0],process.memory_info().rss)
    monitor=threading.Thread(target=sample,daemon=True);monitor.start()
    start=time.perf_counter();model=YOLO(str(weights),task='detect');load=time.perf_counter()-start
    rows=[]
    try:
        # Public COCO weights: box/factory-label/critical-field classes are absent.
        # For custom pilot weights, names describe objects only, never statuses.
        for p in data['images']:
            raw=Path(p['image']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=p['sha256']:raise ValueError('SOURCE_CHANGED')
            import numpy as np
            image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
            started=time.perf_counter()
            result=model.predict(image,device='cpu',imgsz=640,conf=.25,iou=.7,verbose=False,save=False)[0]
            elapsed=time.perf_counter()-started
            detections=[]
            for b in result.boxes:
                box=b.xyxy[0].cpu().tolist();cls=int(b.cls[0]);score=float(b.conf[0])
                detections.append(dict(bbox=box,class_id=cls,class_name=result.names[cls],confidence=score,calibrated=False))
                x1,y1,x2,y2=map(round,box);cv2.rectangle(image,(x1,y1),(x2,y2),(0,180,255),3)
                cv2.putText(image,result.names[cls]+f' {score:.2f}',(x1,max(20,y1)),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,150,255),2)
            scale=min(1,1200/max(image.shape[:2]));image=cv2.resize(image,None,fx=scale,fy=scale)
            cv2.imwrite(str(output/(p['sha256']+'.jpg')),image)
            rows.append(dict(sha256=p['sha256'],seconds=elapsed,width=p['width'],height=p['height'],detections=detections))
            print('Images',len(rows),'/',len(data['images']),flush=True)
    finally:
        stop.set();monitor.join()
    import importlib.metadata
    report=dict(weights_sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),weights_bytes=weights.stat().st_size,
                classes=model.names,rows=rows,load_seconds=load,total_seconds=sum(r['seconds'] for r in rows),
                peak_rss_bytes=peak[0],rss_measurement='process after imports, sampled every 100ms; excludes other processes',
                os_peak_working_set_bytes=getattr(process.memory_info(),'peak_wset',None),
                versions={k:importlib.metadata.version(k) for k in ('torch','torchvision','ultralytics','onnxruntime')},
                confidence_threshold=.25,iou_threshold=.7,imgsz=640,threads=4,device='cpu',integrated=False)
    (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('weights',type=Path);p.add_argument('manifest',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();benchmark(a.weights,a.manifest,a.output)


if __name__=='__main__':main()
