"""Offline API comparison. Known synthetic geometry is explicitly oracle-only."""
import argparse
from collections import Counter
import json
from pathlib import Path
import cv2
import httpx
import numpy as np
from backend.gate.models import Analysis
from tools.barcode_stress import Case,generate,source,safe_output
from experiments.barcode_integrity import inspect,VERSION,RELATIVE_SUPPORT,ROW_VARIATION,MIN_GAP_FRACTION


def controls():
    base,box,payload=source('code128')
    x1,y1,x2,y2=box
    for height in (20,40,100,200):
        for turn in range(4):
            image=np.full_like(base,210)
            short=cv2.resize(base[y1:y2,x1:x2],(x2-x1,height),interpolation=cv2.INTER_NEAREST)
            top=(600-height)//2
            image[top:top+height,x1:x2]=short
            yield Case(f'normal-height-{height}-rotation-{turn*90}','normal','code128',
                       np.ascontiguousarray(np.rot90(image,turn)),payload)
    for name,image in [('blur',cv2.GaussianBlur(base,(0,0),1)),('dim',(base*.5).astype('uint8')),
                       ('bright-label',np.where(base==210,255,base).astype('uint8')),
                       ('clutter',base.copy())]:
        if name=='clutter':cv2.putText(image,'NORMAL LABEL',(40,80),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),2)
        yield Case(f'normal-{name}','normal','code128',image,payload)
    # Same pixels as the 90%-occluded example, but interpreted as a legitimate
    # short barcode on a tall white label. Intrinsic methods cannot distinguish.
    ambiguous=base.copy();ambiguous[y1:y1+round((y2-y1)*.9),x1:x2]=255
    yield Case('normal-short-on-tall-label','normal','code128',ambiguous,payload)


def evaluate(client, output):
    output=safe_output(output)
    if output.exists() and any(p.is_symlink() for p in output.rglob('*')):
        raise ValueError('No symlinks in research output')
    (output/'images').mkdir(parents=True,exist_ok=True)
    initial=client.get('/api/v1/config');initial.raise_for_status();initial=initial.json()
    rows=[]
    from itertools import chain
    for case in chain(generate(),controls()):
        ok,encoded=cv2.imencode('.png',case.image)
        if not ok:raise RuntimeError('Encoding failed')
        response=client.post('/api/v1/analyze',files={'image':(case.name+'.png',encoded.tobytes(),'image/png')})
        response.raise_for_status()
        analysis=Analysis.model_validate(response.json())
        if analysis.config_version!=initial['config_version']:raise RuntimeError('Config drift')
        barcode=analysis.barcode.model_dump()
        # Oracle region supplied only for unrotated occlusion/control fixtures.
        prior=case.parameters.get('source_box') if case.family in ('occlusion','control') else None
        findings=inspect(case.image,barcode,prior)
        row={'name':case.name,'family':case.family,'symbol':case.symbol,
             'decision':analysis.decision,'quality_score':analysis.quality_score,
             'issues':analysis.issues,'metrics':analysis.metrics.model_dump(),
             'payload_matches':barcode['value']==case.payload if barcode['decoded'] else None,
             'parameters':case.parameters,'integrity':findings}
        rows.append(row)
        (output/'images'/f'{case.name}.png').write_bytes(encoded.tobytes())
    final=client.get('/api/v1/config');final.raise_for_status()
    if final.json()!=initial:raise RuntimeError('Config drift')
    accepted=[r for r in rows if r['decision']=='ACCEPT' and r['family']=='occlusion']
    normal=[r for r in rows if r['family'] in ('normal','control')]
    counts={'total':len(rows),'current_decisions':dict(Counter(r['decision'] for r in rows)),
            'occluded_accepts':len(accepted),
            'occluded_accepts_supported':sum(r['integrity']['supported'] for r in accepted),
            'occluded_accepts_intrinsic_flagged':sum(bool(r['integrity']['intrinsic_flags']) for r in accepted),
            'occluded_accepts_intrinsic_or_oracle_flagged':sum(bool(r['integrity']['intrinsic_flags'] or r['integrity']['prior_flags']) for r in accepted),
            'normal_count':len(normal),'normal_supported':sum(r['integrity']['supported'] for r in normal),
            'normal_intrinsic_flagged':sum(bool(r['integrity']['intrinsic_flags']) for r in normal),
            'unsupported_count':sum(not r['integrity']['supported'] for r in rows)}
    report={'notice':'OFFLINE SYNTHETIC RESEARCH ONLY. Prior result uses generator ground truth, not image-only detection. No production integration or calibrated accuracy.',
            'prototype_version':VERSION,
            'research_parameters':{'relative_support':RELATIVE_SUPPORT,'row_variation':ROW_VARIATION,
                                   'minimum_gap_fraction':MIN_GAP_FRACTION,'prior_support_fraction':.90},
            'api_config':initial,'counts':counts,'cases':rows}
    (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    text=['# Barcode Integrity experiment',report['notice'],'',json.dumps(counts,indent=2),'',
          '| Image | Current result | Intrinsic flags | Oracle prior flags | Supported |',
          '|---|---|---|---|---|']
    for r in rows:
        f=r['integrity']
        text.append(f"| [{r['name']}](images/{r['name']}.png) | {r['decision']} | {', '.join(f['intrinsic_flags'])} | {', '.join(f['prior_flags'])} | {f['supported']} |")
    (output/'report.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base',default='http://127.0.0.1:8080')
    parser.add_argument('--output',default='reports/barcode-integrity')
    args=parser.parse_args()
    before=Path('config/thresholds.json').read_bytes()
    with httpx.Client(base_url=args.base,timeout=60) as client:report=evaluate(client,args.output)
    assert Path('config/thresholds.json').read_bytes()==before
    print(json.dumps(report['counts'],indent=2))


if __name__=='__main__':main()
