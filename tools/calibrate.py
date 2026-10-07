"""Offline evaluation. Suggestions never modify production configuration."""
import argparse
import csv
import html
import itertools
import json
import math
import hashlib
from pathlib import Path
import cv2
from backend.gate.config import Thresholds, load_config
from backend.gate.image_input import read_image
from backend.gate.pipeline import analyze
from backend.gate.decision_engine import decide
from tools.dataset_audit import audit_dataset, dataset_files, bounded_read

def summary(rows):
    counts = {'true_accept':0,'true_reject':0,'false_accept':0,'false_reject':0}
    for r in rows:
        good = r['expected']=='GOOD'
        accept = r['predicted']=='ACCEPT'
        counts[('true_accept' if accept else 'false_reject') if good else ('false_accept' if accept else 'true_reject')] += 1
    ta,tr,fa,fr = (counts[k] for k in ['true_accept','true_reject','false_accept','false_reject'])
    ratio = lambda a,b: a/b if b else None
    return dict(total=len(rows),good=ta+fr,bad=tr+fa,**counts,false_accept_rate=ratio(fa,fa+tr),false_reject_rate=ratio(fr,fr+ta),precision=ratio(ta,ta+fa),recall=ratio(ta,ta+fr),accuracy=ratio(ta+tr,len(rows)),confusion_matrix=[[ta,fr],[fa,tr]])

def evaluate(dataset, config, debug_dir=None):
    dataset=Path(dataset).resolve()
    rows, results = [], []
    for label,file in dataset_files(dataset):
        try:
            data=bounded_read(file)
            image=read_image(data)
            r=analyze(image,config)
        except Exception as exc:
            raise RuntimeError(f'Dataset file cannot be evaluated: {file}') from exc
        row=dict(filename=file.relative_to(dataset).as_posix(),sha256=hashlib.sha256(data).hexdigest(),expected=label,predicted=r.decision,score=r.quality_score,metrics=r.metrics.model_dump(),issues=r.issues,decode_success=r.barcode.decoded,correct=(r.decision=='ACCEPT')==(label=='GOOD'),algorithm_version=r.algorithm_version,config_version=r.config_version)
        rows.append(row);results.append(r)
        if debug_dir:
            copy=image.copy()
            if r.barcode.bounding_box:
                x1,y1,x2,y2=r.barcode.bounding_box
                cv2.rectangle(copy,(x1,y1),(x2,y2),(0,200,0),2)
            h,w=copy.shape[:2];margin=config.edge_margin_min
            cv2.rectangle(copy,(int(w*margin),int(h*margin)),(int(w*(1-margin)),int(h*(1-margin))),(0,180,255),2)
            cv2.putText(copy,f'{r.decision} score={r.quality_score} sharp={r.metrics.sharpness:.1f}',(10,30),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,255),2)
            # Keep extensions in debug filenames to avoid jpg/png basename collisions.
            target=Path(debug_dir)/file.relative_to(dataset).with_name(file.name+'.debug.png')
            target.parent.mkdir(parents=True,exist_ok=True)
            success,png=cv2.imencode('.png',copy)
            if not success:raise RuntimeError(f'Debug encoding failed: {file}')
            target.write_bytes(png.tobytes())
    return rows,results

def optimize(rows, results, current, grid, fa_weight=10, fr_weight=1):
    keys = list(grid)
    best = None
    for values in itertools.product(*(grid[k] for k in keys)):
        c = Thresholds.model_validate({**current.model_dump(),**dict(zip(keys,values))})
        candidate = [{**row,'predicted':decide(r.barcode,r.metrics,c)[0]} for row,r in zip(rows,results)]
        s = summary(candidate)
        loss = fa_weight*(s['false_accept_rate'] or 0)+fr_weight*(s['false_reject_rate'] or 0)
        if best is None or loss < best['loss']: best = {'loss':loss,'config':c.model_dump(),'summary':s}
    return best

def main():
    p=argparse.ArgumentParser()
    p.add_argument('dataset',type=Path); p.add_argument('--output',type=Path,default=Path('reports/baseline'))
    p.add_argument('--config',type=Path); p.add_argument('--grid',type=Path); p.add_argument('--debug',action='store_true')
    p.add_argument('--false-accept-weight',type=float,default=10); p.add_argument('--false-reject-weight',type=float,default=1)
    args=p.parse_args()
    if args.output.resolve().is_relative_to(args.dataset.resolve()):p.error('Report must be outside the dataset')
    try:intake=audit_dataset(args.dataset)
    except (ValueError,OSError) as exc:p.error(str(exc))
    if not intake['ready_for_baseline']:p.error('Dataset intake failed: '+json.dumps(intake['errors']))
    c=Thresholds.model_validate_json(args.config.read_text()) if args.config else load_config()
    rows,results=evaluate(args.dataset,c,args.output/'debug' if args.debug else None)
    expected_hashes={r['filename']:r['sha256'] for r in intake['files'] if r['valid']}
    if {r['filename']:r['sha256'] for r in rows}!=expected_hashes:p.error('Dataset changed during evaluation; rerun with immutable inputs')
    if not rows or not any(r['expected']=='GOOD' for r in rows) or not any(r['expected']=='BAD' for r in rows): p.error('Both good/ and bad/ must contain valid labelled images')
    args.output.mkdir(parents=True,exist_ok=True)
    report={'notice':'Evaluation on supplied split only. Initial thresholds require calibration against target-domain images.','dataset_manifest_sha256':intake['manifest_sha256'],'dataset_duplicates':intake['duplicates'],'current_config':c.model_dump(),'summary':summary(rows),'rows':rows,'false_accepts':[r for r in rows if r['expected']=='BAD' and r['predicted']=='ACCEPT'],'false_rejects':[r for r in rows if r['expected']=='GOOD' and r['predicted']=='RETAKE']}
    if args.grid:
        grid=json.loads(args.grid.read_text())
        if not grid or any(not isinstance(v,list) or not v for v in grid.values()): p.error('Grid must contain nonempty value lists')
        if math.prod(len(v) for v in grid.values())>10000: p.error('Grid exceeds 10000 combinations')
        if args.false_accept_weight<0 or args.false_reject_weight<0: p.error('Loss weights must be nonnegative')
        report['suggested']=optimize(rows,results,c,grid,args.false_accept_weight,args.false_reject_weight)
        (args.output/'suggested-config.json').write_text(json.dumps(report['suggested']['config'],indent=2))
    (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    with (args.output/'report.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader()
        for row in rows: writer.writerow({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    (args.output/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Calibration report</title><h1>Dataset evaluation</h1><pre>'+html.escape(json.dumps(report,indent=2))+'</pre>',encoding='utf-8')
    print(json.dumps(report['summary'],indent=2))

if __name__=='__main__': main()
