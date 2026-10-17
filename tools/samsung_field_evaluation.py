"""Post-inference exact field metrics against a frozen private visual reference.

Only referenced photo/fields are scored. Unreadable/unlabelled fields are not
silently false positives or successes. No truth is sent to photo analysis.
"""
import argparse
import hashlib
import json
from pathlib import Path

KEYS=('imei1','imei2','model','sku')


def evaluate(report,annotations):
    photos={p['sha256']:p for c in report['cases'] for p in c['photos']}
    metrics={};details=[]
    for key in KEYS:
        scored=[]
        for reference in annotations['annotations']:
            truth=next((f['value'] for f in reference['fields'] if f['key']==key),None)
            if not truth:continue
            photo=photos[reference['sha256']]
            fields=[f for f in photo['fields'] if f['key']==key]
            def normalize(v):return v.removesuffix('/DS') if key=='model' else v
            candidates={normalize(f['value']) for f in fields}
            valid={normalize(f['value']) for f in fields if f['format_valid']}
            confirmed={normalize(f['value']) for f in fields if f['confirmed']}
            item=dict(photo_id=reference['photo_id'],field=key,tp=int(truth in candidates),
                fp=len(candidates-{truth}),fn=int(truth not in candidates),
                valid_tp=int(truth in valid),valid_fp=len(valid-{truth}),
                conflict=len(candidates)>1,exact_only=candidates=={truth},
                confirmed_tp=int(truth in confirmed),confirmed_fp=len(confirmed-{truth}),
                invalid_candidates=len(candidates-valid))
            scored.append(item);details.append(item)
        total=lambda name:sum(s[name] for s in scored)
        tp,fp,fn=total('tp'),total('fp'),total('fn');vt,vf=total('valid_tp'),total('valid_fp')
        metrics[key]=dict(references=len(scored),tp=tp,fp=fp,fn=fn,
            precision=tp/(tp+fp) if tp+fp else None,recall=tp/(tp+fn) if tp+fn else None,
            exact_only=total('exact_only'),conflicting_photo_fields=total('conflict'),
            valid_tp=vt,valid_fp=vf,valid_precision=vt/(vt+vf) if vt+vf else None,
            invalid_candidates=total('invalid_candidates'),confirmed_tp=total('confirmed_tp'),confirmed_fp=total('confirmed_fp'))
    return dict(fields=metrics,details=details,photos=len(photos),
        extra_passes=dict(zxing_scale2=sum(p.get('extra_passes',{}).get('zxing_scale2',{}).get('performed',False) for p in photos.values()),
            ppocr_illumination=sum(p.get('pretrained_ocr',{}).get('illumination',{}).get('performed',False) for p in photos.values())),
        conflicts_all_photos={k:sum(len({f['value'] for f in p['fields'] if f['key']==k})>1 for p in photos.values()) for k in KEYS},
        notice='Known development photos; source-visible single-review truth, not Samsung registry. Precision is per distinct candidate per referenced photo/field; recall is per reference. Unknown references excluded. Correct candidate among conflicts is not a safe chosen value.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path);parser.add_argument('annotations',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();raw=args.annotations.read_bytes()
    expected=args.annotations.with_suffix('.sha256')
    if not expected.is_file() or expected.read_text().strip()!=hashlib.sha256(raw).hexdigest():
        raise ValueError('Visual references must be frozen before scoring')
    result=evaluate(json.loads(args.report.read_text(encoding='utf-8')),json.loads(raw))
    result['annotations_sha256']=hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['fields'],indent=2))
