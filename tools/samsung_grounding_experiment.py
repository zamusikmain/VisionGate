"""Frozen-prompt open-vocabulary detection on local source pixels, without uploads."""
import json
import hashlib
from pathlib import Path
import time
import zipfile

import cv2

from backend.gate.image_input import read_image
from backend.gate.samsung_paths import input_archives
from backend.gate.pretrained_grounding import GroundingONNX


def run():
    root=Path('reports/samsung-pretrained/grounding');root.mkdir(parents=True,exist_ok=True)
    old=json.loads(Path('reports/samsung-v03/final/results.json').read_text(encoding='utf-8'))
    entries={e['sha256']:e for e in old['intake']['files'] if e.get('sha256')}
    sources={p.name:p for p in input_archives()}
    start=time.perf_counter();engine=GroundingONNX();load=time.perf_counter()-start;rows=[]
    print('Model loaded',round(load,2),'seconds',flush=True)
    for case in old['cases']:
        for photo in case['photos']:
            entry=entries[photo['sha256']]
            with zipfile.ZipFile(sources[entry['archive']]) as z:data=z.read(entry['path'])
            assert hashlib.sha256(data).hexdigest()==photo['sha256']
            image=read_image(data);result=engine.predict(image)
            # Attach evaluation metadata after pixel-only inference.
            result.update(sha256=photo['sha256'],case_id=case['case_id'],role=photo['role']);rows.append(result)
            (root/(photo['sha256']+'.json')).write_text(json.dumps(result,indent=2))
            canvas=image.copy()
            for d in result['detections']:
                x1,y1,x2,y2=map(int,d['bbox']);color={'box':(255,120,0),'label':(0,170,255),'phone':(0,0,255)}[d['kind']]
                cv2.rectangle(canvas,(x1,y1),(x2,y2),color,3)
                cv2.putText(canvas,d['kind']+' '+str(round(d['score'],2)),(x1,max(30,y1)),cv2.FONT_HERSHEY_SIMPLEX,1,color,2)
            scale=min(1,1400/max(canvas.shape[:2]));canvas=cv2.resize(canvas,None,fx=scale,fy=scale)
            cv2.imencode('.jpg',canvas)[1].tofile(str(root/(photo['sha256']+'.jpg')))
            print(len(rows),'/28',photo['sha256'][:10],result['seconds'],[(d['kind'],round(d['score'],2)) for d in result['detections']],flush=True)
    (root/'results.json').write_text(json.dumps(dict(rows=rows,load_seconds=load,inference_seconds=sum(r['seconds'] for r in rows)),indent=2))


if __name__=='__main__':run()
