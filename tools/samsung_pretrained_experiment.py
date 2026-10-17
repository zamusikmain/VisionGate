"""Independent local pretrained OCR comparison; no changes to deployed decisions."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import time
import zipfile

import cv2

from backend.gate.image_input import read_image
from backend.gate.pretrained_ocr import PaddleONNX,text_crop
from backend.gate.samsung_auto import parse_fields,summarize_fields
from backend.gate.samsung_pretrained import extract_records
from backend.gate.samsung_paths import input_archives
from tools.samsung_intake import inspect_archives


def infer(engine,image,data,detections=None):
    result=engine.read(image,detections)
    records=extract_records(result)
    result.update(sha256=hashlib.sha256(data).hexdigest(),fields=summarize_fields(records),records=records)
    return result


def run(baseline,output,refresh=False,recognizer='latin',detection_report=None,detector='mobile'):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    diagnostics=output/'diagnostics';diagnostics.mkdir(exist_ok=True)
    cache=output/'photo-cache';cache.mkdir(exist_ok=True)
    old=json.loads(Path(baseline).read_text(encoding='utf-8'))
    old_photos={p['sha256']:p for c in old['cases'] for p in c['photos']}
    sources=input_archives();intake=inspect_archives(sources);by_name={p.name:p for p in sources}
    # CPU cascade: the server recognizer revisits field-like mobile lines. This
    # uses generic printed syntax, never expected digits, labels or case metadata.
    detected={p['sha256']:[dict(polygon=l['polygon'],detection_score=l['detection_score'],rotation_hint=l['rotation'])
        for l in p['lines'] if re.search(r'IME|[I1]ME|SM-|S/N|SERIAL|EID|[0-9]{10}|^[A-Z0-9]{8,16}$',l['text'],re.I)]
        for p in json.loads(Path(detection_report).read_text(encoding='utf-8'))['photos']} if detection_report else {}
    engine_start=time.perf_counter();engine=PaddleONNX(recognizer=recognizer,detector=detector);load_seconds=time.perf_counter()-engine_start
    photos=[];seen=set()
    for entry in intake['files']:
        digest=entry.get('sha256')
        if digest not in old_photos or digest in seen:continue
        seen.add(digest)
        with zipfile.ZipFile(by_name[entry['archive']]) as z:data=z.read(entry['path'])
        assert hashlib.sha256(data).hexdigest()==digest
        image=read_image(data);cached=cache/(digest+'.json')
        if cached.exists() and not refresh:result=json.loads(cached.read_text(encoding='utf-8'))
        else:
            result=infer(engine,image,data,detected.get(digest))
            cached.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        result['records']=extract_records(result);result['fields']=summarize_fields(result['records'])
        # Evaluation metadata is attached only after inference.
        result.update(role=entry['role'],case_id=entry['case_id']);photos.append(result)
        canvas=image.copy()
        for i,line in enumerate(result['lines']):
            import numpy as np
            cv2.polylines(canvas,[np.int32(line['polygon'])],True,(0,170,255),2)
            if any(r['line_index']==i for r in result['records']):
                crop=text_crop(image,line['polygon']);scale=min(5,1500/max(crop.shape[:2]))
                cv2.imencode('.png',cv2.resize(crop,None,fx=scale,fy=scale))[1].tofile(str(diagnostics/(digest+f'-line{i}.png')))
        scale=min(1,1800/max(canvas.shape[:2]));canvas=cv2.resize(canvas,None,fx=scale,fy=scale)
        cv2.imencode('.jpg',canvas)[1].tofile(str(diagnostics/(digest+'.jpg')))
        print(f"{len(photos)}/28 {digest[:10]} {result['seconds']}s: "+json.dumps([(f['key'],f['value'],f['format_valid']) for f in result['fields']]),flush=True)
    comparisons=[]
    for photo in photos:
        old_photo=old_photos[photo['sha256']]
        comparisons.append(dict(sha256=photo['sha256'],case_id=photo['case_id'],role=photo['role'],seconds=photo['seconds'],
            before=[dict(key=f['key'],value=f['value'],confirmed=f['confirmed']) for f in old_photo['fields']],
            after=[dict(key=f['key'],value=f['value'],confirmed=f['confirmed']) for f in photo['fields']]))
    report=dict(photos=photos,comparisons=comparisons,model_load_seconds=round(load_seconds,3),
                inference_seconds=round(sum(p['seconds'] for p in photos),3),
                notice='Independent development experiment. OCR candidates are not verified fields or photo-quality approval. Decisions remain the baseline until separately validated integration.')
    (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,default=Path('reports/samsung-v03/final/results.json'))
    p.add_argument('--output-dir',type=Path,default=Path('reports/samsung-pretrained/mobile'))
    p.add_argument('--recognizer',choices=['latin','server'],default='latin')
    p.add_argument('--detection-report',type=Path)
    p.add_argument('--detector',choices=['mobile','server'],default='mobile')
    p.add_argument('--refresh',action='store_true');a=p.parse_args();run(a.baseline,a.output_dir,a.refresh,a.recognizer,a.detection_report,a.detector)
