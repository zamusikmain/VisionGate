"""Explicit manual-region OCR aid. Never an automatic photo-approval endpoint."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from backend.gate.image_input import read_image
from backend.gate.samsung_vision import rectify,ordered_quad
from backend.gate.samsung_pretrained import read_pretrained,extract_records
from backend.gate.samsung_auto import summarize_fields
from backend.gate.samsung import valid_imei
from backend.gate.decoder import ZXingDecoder
from backend.gate.samsung_preprocessing import variant_to_original,scale2_bounded
from backend.gate.samsung_barcodes import LINEAR_IMEI_FORMATS


def extract_region(data,manifest):
    digest=hashlib.sha256(data).hexdigest()
    if manifest.get('image_sha256')!=digest:raise ValueError('MANUAL_REGION_SOURCE_HASH_MISMATCH')
    if manifest.get('role') not in {'device','scan'}:raise ValueError('MANUAL_REGION_ROLE_REQUIRED')
    image=read_image(data);h,w=image.shape[:2];q=np.asarray(manifest.get('quad'),dtype=np.float32)
    if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('INVALID_MANUAL_QUAD')
    if q[:,0].min()<0 or q[:,1].min()<0 or q[:,0].max()>w-1 or q[:,1].max()>h-1:raise ValueError('MANUAL_QUAD_OUTSIDE_IMAGE')
    q=ordered_quad(q)
    if not cv2.isContourConvex(q) or cv2.contourArea(q)<64:raise ValueError('DEGENERATE_MANUAL_QUAD')
    crop,matrix=rectify(image,q)
    result=read_pretrained(crop,cache_dir=None,enhance=True);records=extract_records(result)
    for r in records:
        r['region']=variant_to_original(r['region'],matrix);r['polygon']=r['region']
        r['original_to_manual_roi']=matrix.tolist();r['coordinate_space']='original'
    decoder=ZXingDecoder();codes=[]
    def collect(pixels,transform,variant):
        for b in decoder.decode(pixels):
            if not b.decoded or b.type not in LINEAR_IMEI_FORMATS or not valid_imei(b.value):continue
            polygon=variant_to_original(b.polygon,transform)
            codes.append(dict(value=b.value,polygon=polygon,type=b.type,variant=variant))
            records.append(dict(key='imei',value=b.value,format_valid=True,source='barcode',variant=variant,
                polygon=polygon,coordinate_space='original',original_to_manual_roi=matrix.tolist(),confidence=None))
    collect(crop,matrix,'manual-roi-native')
    if not codes:
        up,scaling=scale2_bounded(crop)
        if up is not None:collect(up,np.float64(scaling)@matrix,'manual-roi-2x')
    for r in records:r.update(evidence_group=digest,independent_evidence=False,region_source='explicit_manual_quad')
    return dict(mode='ASSISTED_REGION_EXTRACTION',automatic=False,manual_region=True,source_sha256=digest,
                role=manifest['role'],quad=q.tolist(),original_to_roi=matrix.tolist(),fields=summarize_fields(records),barcodes=codes,
                required_photo_checks_established=False,approval_produced=False,ocr_seconds=result.get('elapsed_seconds',result.get('seconds')),
                notice='Manual area selection can improve extraction. It does not establish box faces, completeness, no occlusion or no screen recapture. Do not replace automatic UNKNOWN checks with this result.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('image',type=Path);p.add_argument('manifest',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    if a.output.resolve() in {a.image.resolve(),a.manifest.resolve()}:p.error('Output must not overwrite image or region manifest')
    result=extract_region(a.image.read_bytes(),json.loads(a.manifest.read_text(encoding='utf-8')))
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Assisted extraction saved; no automatic photo approval produced.')
