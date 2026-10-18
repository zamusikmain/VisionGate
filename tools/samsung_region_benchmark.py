"""Private offline region benchmark. Manual polygons score predictions only.

This does not change the application's pipeline. Expected outcomes are joined
after inference. Use --fresh for a full OCR pass without a pre-existing cache.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
from backend.gate.image_input import read_image
from backend.gate.samsung_auto import analyze_photo,classify_case
from backend.gate.samsung_display_geometry import display_boundaries,framed_gallery_evidence,read_framed_ui
from backend.gate.samsung_screen import read_screen_ui
from tools.samsung_region_annotations import validate
from tools.samsung_run import evaluate,swaps
from tools.samsung_visual_resources import peak_working_set

def run(manifest,base_report,output,fresh=False,reference=None):
    start=time.perf_counter();out=Path(output)
    if out.exists():raise ValueError('OUTPUT_EXISTS_KEEP_PRIOR_VERSIONS')
    data=validate(json.loads(Path(manifest).read_text(encoding='utf-8')))
    baseline=json.loads(Path(base_report).read_text(encoding='utf-8'))
    cached={p['sha256']:p for c in baseline['cases'] for p in c['photos']}
    identifiers={p['sha256']:c['case_id'] for c in baseline['cases'] for p in c['photos']}
    # Baseline IDs map pairs and report rows; never enter any image analyzer.
    out.mkdir(parents=True);grouped={};rows=[]
    for item in data['images']:
        before=time.perf_counter();raw=Path(item['image']).read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if digest!=item['sha256']:raise ValueError('SOURCE_CHANGED')
        if item.get('role') not in {'device','scan'}:raise ValueError('ROLE_REQUIRED')
        pixels=read_image(raw)
        photo=analyze_photo(pixels,raw,item['role'],use_ocr=True,cache_dir=None) if fresh else copy.deepcopy(cached[digest])
        boundaries=display_boundaries(pixels);ocr=photo.get('screen_ui_ocr',{})
        if boundaries and ocr.get('status')!='OK':ocr=read_screen_ui(pixels)
        finding=framed_gallery_evidence(ocr,boundaries)
        if boundaries and not finding:finding=framed_gallery_evidence(read_framed_ui(pixels,boundaries),boundaries)
        if finding:
            # This prototype has not established real-positive reliability.
            # Preserve observations for review; do not counterfeit a confirmed
            # Samsung defect or replace a required UNKNOWN with FAIL/PASS.
            photo.setdefault('experimental_region_candidates',[]).append(
                dict(evidence=finding,verified_defect=False,automatic_decision_allowed=False))
        row=dict(photo_id=item['photo_id'],sha256=digest,boundaries=boundaries,finding=finding,seconds=round(time.perf_counter()-before,3))
        rows.append(row);grouped.setdefault(identifiers.get(digest,item['case_group']),[]).append(photo)
        print(f"{len(rows)}/{len(data['images'])}: frames={len(boundaries)} evidence={bool(finding)}",flush=True)
        (out/'progress.json').write_text(json.dumps(dict(rows=rows),indent=2))
    cases=[]
    for group,photos in sorted(grouped.items()):
        result=classify_case(photos);result['case_id']=group;cases.append(result)
    expected={}
    if reference:
        from backend.gate.samsung_reference import final_status_labels
        expected=final_status_labels(reference)
    # Human semantic regions are consulted only AFTER all pixel predictions.
    scoring=[]
    predicted={r['sha256']:r for r in rows}
    for item in data['images']:
        prediction=predicted[item['sha256']];h,w=item['height'],item['width']
        refs=[o for o in item['objects'] if o['class']=='screen_frame' and o.get('reviewed') and o.get('scope','target')=='target']
        overlaps=[]
        for obj in refs:
            reference_poly=cv2.convexHull(np.float32(obj['polygon'])*np.float32([w,h]))
            best=0.
            for candidate in prediction['boundaries']:
                poly=cv2.convexHull(np.float32(candidate['polygon']));intersection=cv2.intersectConvexConvex(reference_poly,poly)[0]
                best=max(best,intersection/max(1,cv2.contourArea(reference_poly)+cv2.contourArea(poly)-intersection))
            overlaps.append(round(best,4))
        scoring.append(dict(photo_id=item['photo_id'],visible_screen_review=item['reviews']['screen_recapture'],
                            finding=bool(prediction['finding']),frame_ious=overlaps))
    report=dict(cases=cases,evaluation=evaluate(cases,expected),permutations=swaps(cases),region_predictions=rows,
                region_evaluation=scoring,fresh_ocr=fresh,manual_regions_used_for_inference=False,integrated=False,
                elapsed_seconds=round(time.perf_counter()-start,3),peak_working_set_bytes=peak_working_set(),
                notice='Previously inspected development data; not independent accuracy. Geometry alone never changes a decision.')
    (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(cases=len(cases),new_evidence=sum(bool(r['finding']) for r in rows),
                         status_counts=report['evaluation']['rejection_status_counts'],seconds=report['elapsed_seconds'])),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('base_report',type=Path);p.add_argument('output',type=Path);p.add_argument('--fresh',action='store_true');p.add_argument('--reference-xlsx',type=Path);a=p.parse_args()
    run(a.manifest,a.base_report,a.output,a.fresh,a.reference_xlsx)
