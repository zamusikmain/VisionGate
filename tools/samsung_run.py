"""Samsung automatic offline evaluation. Labels enter only after photo analysis."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import time
import zipfile
import cv2

from backend.gate.image_input import read_image, InvalidImage
from backend.gate.samsung_auto import analyze_photo, classify_case
from tools.samsung_intake import inspect_archives
from backend.gate.samsung_paths import input_archives


def fingerprint():
    root=Path(__file__).resolve().parents[1]
    files=['backend/gate/samsung_auto.py','backend/gate/samsung_vision.py','backend/gate/samsung_barcodes.py','backend/gate/local_ocr.py','tools/windows_ocr.ps1','backend/gate/samsung_pretrained.py','backend/gate/pretrained_ocr.py','backend/gate/samsung_preprocessing.py','backend/gate/samsung_policy.py','backend/gate/samsung_screen.py','tools/windows_ui_ocr.ps1']
    profile=json.dumps([os.getenv('SAMSUNG_OCR_ENGINE','legacy'),os.getenv('SAMSUNG_OCR_DETECTOR','mobile'),os.getenv('SAMSUNG_RECOGNITION_PROFILE','original'),os.getenv('SAMSUNG_POLICY_PROFILE','role-v1')])
    return hashlib.sha256(profile.encode()+b''.join((root/f).read_bytes() for f in files)).hexdigest()[:16]


def evaluate(cases, expected):
    matrix={truth:{pred:0 for pred in ('APPROVED','REJECTED')} for truth in ('APPROVED','REJECTED')}
    rows=[]
    for case in cases:
        truth=expected.get(case['case_id'])
        if truth not in matrix:continue
        actual=case['final_decision'];matrix[truth][actual]+=1
        rows.append(dict(case_id=case['case_id'],expected=truth,actual=actual,
                         diagnostic=case['diagnostic_state'],review=case['review_required'],basis=case['rejection_basis'],
                         issues=sorted({f['code'] for f in case['findings']})))
    checks=[check for c in cases for p in c['photos'] for check in p['checks'].values()]
    photos=[p for c in cases for p in c['photos']]
    n=len(cases)
    return dict(rows=rows,confusion_matrix=matrix,false_approved=matrix['REJECTED']['APPROVED'],
        false_rejected=matrix['APPROVED']['REJECTED'],
        false_approved_rate=matrix['REJECTED']['APPROVED']/sum(matrix['REJECTED'].values()) if sum(matrix['REJECTED'].values()) else None,
        false_rejected_rate=matrix['APPROVED']['REJECTED']/sum(matrix['APPROVED'].values()) if sum(matrix['APPROVED'].values()) else None,
        counts=dict(Counter(c['final_decision'] for c in cases)),
        diagnostic_counts=dict(Counter(c['diagnostic_state'] for c in cases)),
        rejection_status_counts=dict(Counter(c.get('rejection_status','legacy') for c in cases)),
        confirmed_decision_coverage=sum(c.get('confirmed_decision',False) for c in cases)/n if n else None,
        review_count=sum(c['review_required'] for c in cases),
        decisive_coverage=sum(c['decisive_coverage'] for c in cases)/n if n else None,
        binary_output_coverage=1. if n else None,
        unknown_check_rate=sum(c['state']=='UNKNOWN' for c in checks)/len(checks) if checks else None,
        extraction=dict(photos=len(photos),label_supported=sum(p['label_index'] is not None for p in photos),
            imei_photos=sum(bool(p['extraction']['confirmed_imeis']) for p in photos),
            model_photos=sum(bool(p['extraction']['confirmed_models']) for p in photos),
            serial_photos=sum(any(f['key']=='serial' and f['confirmed'] for f in p['fields']) for p in photos)),
        notice='Development examples already inspected; not independent accuracy. Extraction coverage is not field accuracy. FAIL from engineering rules is not an official Samsung adjudication.')


def swaps(cases):
    outcomes=[]
    for a in cases:
        device=next((p for p in a['photos'] if p['role']=='device'),None)
        if not device:continue
        for b in cases:
            if a['case_id']==b['case_id']:continue
            scan=next((p for p in b['photos'] if p['role']=='scan'),None)
            if not scan:continue
            result=classify_case([device,scan])
            mismatch=any(f['category']=='identifier_mismatch' for f in result['findings'])
            outcomes.append(dict(device_case=a['case_id'],scan_case=b['case_id'],
                                 final=result['final_decision'],diagnostic=result['diagnostic_state'],confirmed_mismatch=mismatch))
    return dict(total=len(outcomes),confirmed_mismatches=sum(r['confirmed_mismatch'] for r in outcomes),
                unsafe_approvals=sum(r['final']=='APPROVED' for r in outcomes),
                unresolved_identity=sum(not r['confirmed_mismatch'] for r in outcomes),rows=outcomes,
                notice='Scan permutations across different provided cases. A binary rejection for unknown data is not successful mismatch detection.')


def run(paths, output, ocr=True, refresh=False,reference_xlsx=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    paths=list(map(Path,paths))
    if len({p.name for p in paths})!=len(paths):raise ValueError('DUPLICATE_ARCHIVE_NAMES')
    intake=inspect_archives(paths);source={p.name:p for p in paths};grouped={};seen=set();key=fingerprint()
    cache=output/'photo-cache';cache.mkdir(exist_ok=True);start=time.perf_counter()
    rows=[r for r in intake['files'] if 'case_id' in r and 'role' in r]
    if not rows:raise ValueError('NO_DEVICE_SCAN_CASES')
    total=len({(r['case_id'],r['role'],r.get('sha256')) for r in rows})
    for row in rows:
        dedup=(row['case_id'],row['role'],row['sha256'])
        if dedup in seen:continue
        seen.add(dedup)
        # Case IDs/paths/labels are deliberately not passed to analyze_photo.
        cached=cache/f'{row["sha256"]}-{row["role"]}-{key}-{int(ocr)}.json'
        if row['status']!='OK':
            photo=invalid_photo(row['sha256'],row['role'],row['status'])
        elif cached.exists() and not refresh:photo=json.loads(cached.read_text(encoding='utf-8'))
        else:
            with zipfile.ZipFile(source[row['archive']]) as z:data=z.read(row['path'])
            if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('SOURCE_CHANGED')
            try:photo=analyze_photo(read_image(data),data,row['role'],use_ocr=ocr,cache_dir=output/'ocr-cache',diagnostic_dir=output/'diagnostics')
            except (InvalidImage,ValueError,cv2.error) as exc:
                photo=invalid_photo(row['sha256'],row['role'],str(exc) if isinstance(exc,InvalidImage) else 'ANALYSIS_ERROR')
            cached.write_text(json.dumps(photo,ensure_ascii=False,indent=2),encoding='utf-8')
        grouped.setdefault(row['case_id'],[]).append(photo)
        print(f'Photos analyzed: {len(seen)}/{total}',flush=True)
    cases=[]
    for cid,photos in sorted(grouped.items()):
        result=classify_case(photos);result['case_id']=cid;cases.append(result)
        structural=next((c['issues'] for c in intake['cases'] if c['case_id']==cid),[])
        if structural:
            result['final_decision']='REJECTED';result['diagnostic_state']='FAIL';result['decisive_coverage']=True
            result['rejection_status']='REJECTED_CONFIRMED';result['confirmed_decision']=True
            result['rejection_basis']='input_error'
            result['findings'].extend(dict(code=s,state='FAIL',category='input_error') for s in structural)
    # Evaluation labels are attached AFTER predictions; never supplied to classifiers.
    expected={c['case_id']:c['labels'][0] for c in intake['cases'] if len(c['labels'])==1}
    if reference_xlsx:
        from backend.gate.samsung_reference import final_status_labels
        expected=final_status_labels(reference_xlsx)
    report=dict(cases=cases,evaluation=evaluate(cases,expected),permutations=swaps(cases),
                elapsed_seconds=round(time.perf_counter()-start,2),pipeline_fingerprint=key,intake=intake)
    (output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report['evaluation'].items() if k not in {'rows'}},ensure_ascii=True,indent=2))
    return report


def invalid_photo(digest,role,error):
    return dict(sha256=digest,role=role,width=0,height=0,proposals=[],label_index=None,fields=[],barcodes=[],ocr=[],problems=[],
                checks={'input_valid':dict(state='FAIL',reason=error)},
                extraction={'confirmed_imeis':[],'confirmed_models':[],'expects_two_imeis':False})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    inputs=p.add_mutually_exclusive_group()
    inputs.add_argument('--archives',nargs='+',type=Path)
    inputs.add_argument('--archive-dir',type=Path,help='Default: SAMSUNG_ARCHIVE_DIR or project data/Samsung/original')
    p.add_argument('--output-dir',type=Path,default=Path('reports/samsung-auto'))
    p.add_argument('--reference-xlsx',type=Path,help='Evaluation only: use Final_Status after predictions, never Registration Status')
    p.add_argument('--no-ocr',action='store_true');p.add_argument('--refresh',action='store_true')
    a=p.parse_args()
    try:run(a.archives or input_archives(a.archive_dir),a.output_dir,not a.no_ocr,a.refresh,a.reference_xlsx)
    except (zipfile.BadZipFile,FileNotFoundError,ValueError) as exc:
        p.exit(2,'Samsung batch input error: '+str(exc)+'\n')


if __name__=='__main__':main()
