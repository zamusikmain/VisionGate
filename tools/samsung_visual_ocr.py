"""Experimental OCR on predicted boxes; no manual ROI, no photo classification.

Full source context remains available. All readings share the same photo evidence
group; repeated detector/processing variants are never independent evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
from backend.gate.image_input import read_image
from backend.gate.samsung_pretrained import read_pretrained,extract_records
from backend.gate.samsung_auto import summarize_fields
from backend.gate.samsung_preprocessing import variant_to_original,scale2_bounded
from backend.gate.decoder import ZXingDecoder


def extract(data,detections):
    image=read_image(data);h,w=image.shape[:2];digest=hashlib.sha256(data).hexdigest()
    records=[];symbols=[];regions=[];decoder=ZXingDecoder();start=time.perf_counter()
    # Fixed budget, detector confidence only. No expected identifiers or labels.
    targets=sorted((d for d in detections if d['class_name']=='identification_region' and d['confidence']>=.25),key=lambda d:-d['confidence'])[:3]
    for d in targets:
        x1,y1,x2,y2=d['bbox'];padx=.05*(x2-x1);pady=.05*(y2-y1)
        x1=max(0,int(x1-padx));y1=max(0,int(y1-pady));x2=min(w,int(np.ceil(x2+padx)));y2=min(h,int(np.ceil(y2+pady)))
        if x2<=x1 or y2<=y1:continue
        crop=image[y1:y2,x1:x2];matrix=np.float64([[1,0,-x1],[0,1,-y1],[0,0,1]])
        result=read_pretrained(crop,cache_dir=None,enhance=True)
        for r in extract_records(result):
            r['region']=variant_to_original(r['region'],matrix);r['polygon']=r['region'];r['coordinate_space']='original';records.append(r)
        def collect(pixels,transform,variant):
            n=0
            for b in decoder.decode(pixels):
                if not b.decoded:continue
                polygon=variant_to_original(b.polygon,transform)
                symbols.append(dict(value=b.value,type=b.type,polygon=polygon,variant=variant))
                # Keep only valid IMEI strings as unindexed identity candidates.
                from backend.gate.samsung import valid_imei
                if b.type in {'Code 128','Code 39','ITF'} and valid_imei(b.value):
                    n+=1;records.append(dict(key='imei',value=b.value,format_valid=True,source='barcode',variant=variant,polygon=polygon,coordinate_space='original',confidence=None))
            return n
        if not collect(crop,matrix,'predicted-roi-native'):
            up,scaling=scale2_bounded(crop)
            if up is not None:collect(up,np.float64(scaling)@matrix,'predicted-roi-2x')
        regions.append(dict(bbox=[x1,y1,x2,y2],detector=d,original_to_roi=matrix.tolist(),ocr_status=result['status']))
    for r in records:r.update(evidence_group=digest,independent_evidence=False,region_source='experimental_yolo_prediction')
    return dict(source_sha256=digest,mode='EXPERIMENTAL_PREDICTED_ROI',automatic_localization=True,
                photo_approval_produced=False,required_photo_checks_established=False,regions=regions,
                fields=summarize_fields(records),barcodes=symbols,elapsed_seconds=time.perf_counter()-start)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('predictions',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    manifest=json.loads(a.manifest.read_text(encoding='utf-8'));pred=json.loads(a.predictions.read_text(encoding='utf-8'));pred={r['sha256']:r for r in pred['rows']}
    a.output.mkdir(parents=True,exist_ok=True);rows=[]
    for p in manifest['images']:
        raw=Path(p['image']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=p['sha256']:raise ValueError('SOURCE_CHANGED')
        result=extract(raw,pred[p['sha256']]['detections']);rows.append(result)
        (a.output/(p['sha256']+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print('Images',len(rows),flush=True)
    (a.output/'results.json').write_text(json.dumps(dict(rows=rows,total_seconds=sum(r['elapsed_seconds'] for r in rows)),ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
