"""Deterministic synthetic stress study via HTTP, never calibration/training data."""
import argparse
import csv
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from collections import Counter
import cv2
import httpx
import numpy as np
import zxingcpp
from backend.gate.models import Analysis

NOTICE = ('SYNTHETIC STRESS ONLY. No customer labels, no calibration, no accuracy estimate. '
          'An occluded ACCEPT is a completeness-policy candidate, not automatically a decode error.')


@dataclass
class Case:
    name: str
    family: str
    symbol: str
    image: np.ndarray
    payload: str
    parameters: dict = field(default_factory=dict)


def source(symbol):
    payload = 'VG-STRESS-123456'
    fmt = zxingcpp.BarcodeFormat.Code128 if symbol == 'code128' else zxingcpp.BarcodeFormat.QRCode
    # Keep both clean controls comfortably visible in the fixed 1000x600 frame.
    # Scale is a fixture parameter, never a production threshold adjustment.
    bars = np.asarray(zxingcpp.create_barcode(payload, fmt).to_image(scale=4 if symbol=='code128' else 12))
    if bars.ndim == 3:
        bars = cv2.cvtColor(bars, cv2.COLOR_RGB2GRAY)
    h, w = bars.shape
    image = np.full((600, 1000), 210, np.uint8)
    y, x = (600-h)//2, (1000-w)//2
    image[y:y+h, x:x+w] = bars
    ys, xs = np.where(bars < 128)
    box = (x+int(xs.min()), y+int(ys.min()), x+int(xs.max())+1, y+int(ys.max())+1)
    return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR), box, payload


def generate():
    for symbol in ('code128', 'qr'):
        base, (x1,y1,x2,y2), payload = source(symbol)
        w, h = x2-x1, y2-y1
        def case(name, family, image, **parameters):
            return Case(f'{symbol}-{name}', family, symbol, image, payload,
                        {'source_box': [x1,y1,x2,y2], **parameters})
        yield case('control', 'control', base)
        for sigma in (1, 2, 4, 8, 12):
            yield case(f'blur-{sigma}', 'blur', cv2.GaussianBlur(base,(0,0),sigma), sigma=sigma)
        for factor in (.7, .4, .2, .1):
            yield case(f'dark-{factor}', 'lighting', (base*factor).astype(np.uint8), factor=factor)
        for fraction in (.1,.25,.5):
            radius = max(1,round(w*fraction/2))
            mask=np.zeros(base.shape[:2],np.uint8)
            cv2.ellipse(mask,((x1+x2)//2,(y1+y2)//2),(radius,max(1,h//3)),0,0,360,255,-1)
            glare=base.copy();glare[mask>0]=255
            yield case(f'glare-{fraction}', 'glare', glare, width_fraction=fraction)
        for fraction in (.05,.15,.3):
            # Actual image boundary cuts through the left side of the symbol.
            cut=x1+max(1,round(w*fraction))
            yield case(f'crop-{fraction}', 'crop', base[:,cut:].copy(), removed_width_fraction=fraction)
        src=np.float32([[x1,y1],[x2,y1],[x2,y2],[x1,y2]])
        for fraction in (.15,.35,.6):
            dst=src.copy();dst[0]+=[w*fraction,h*fraction];dst[1]+=[-w*fraction,h*fraction]
            warped=cv2.warpPerspective(base,cv2.getPerspectiveTransform(src,dst),(1000,600),borderValue=(210,210,210))
            yield case(f'perspective-{fraction}', 'perspective', warped, top_inset_fraction=fraction)
        for axis in ('horizontal','vertical'):
            for location in ('start','middle','end'):
                for fraction in (.1,.25,.5,.75,.9):
                    for color, value in (('white',255),('black',0)):
                        extent=h if axis=='horizontal' else w
                        size=max(1,round(extent*fraction))
                        offset={'start':0,'middle':(extent-size)//2,'end':extent-size}[location]
                        xa,ya,xb,yb=(x1,y1+offset,x2,y1+offset+size) if axis=='horizontal' else (x1+offset,y1,x1+offset+size,y2)
                        image=base.copy();image[ya:yb,xa:xb]=value
                        yield case(f'occlusion-{axis}-{location}-{fraction}-{color}', 'occlusion', image,
                                   axis=axis, location=location, color=color,
                                   mask_box=[xa,ya,xb,yb], occluded_symbol_area_fraction=(xb-xa)*(yb-ya)/(w*h))
        for fraction in (.25,.5,.75):
            pw,ph=max(1,round(w*fraction)),max(1,round(h*fraction))
            xa,ya=x1+(w-pw)//2,y1+(h-ph)//2
            image=base.copy();image[ya:ya+ph,xa:xa+pw]=128
            yield case(f'occlusion-patch-{fraction}', 'occlusion', image,
                       axis='patch',mask_box=[xa,ya,xa+pw,ya+ph],
                       occluded_symbol_area_fraction=pw*ph/(w*h))


def review(case, result):
    flags=[]
    matches = result.barcode.value == case.payload if result.barcode.decoded else None
    if result.decision=='ACCEPT' and matches is not True:
        flags.append('ACCEPT_WITHOUT_EXPECTED_PAYLOAD')
    if result.decision=='ACCEPT' and case.family=='occlusion':
        flags.append('OCCLUDED_ACCEPT_COMPLETENESS_REVIEW')
    if result.decision=='ACCEPT' and case.family=='crop':
        flags.append('CROPPED_ACCEPT_REVIEW')
    if result.decision=='RETAKE' and case.family=='control':
        flags.append('CLEAN_CONTROL_REJECTED')
    if result.decision=='ACCEPT' and case.family in ('glare','perspective') and not result.issues:
        flags.append('DISTORTION_WITHOUT_ADVISORY_REVIEW')
    data=result.model_dump()
    data['barcode'].pop('value',None)
    if case.family in ('control','occlusion') and result.barcode.bounding_box:
        bx1,by1,bx2,by2=result.barcode.bounding_box
        sx1,sy1,sx2,sy2=case.parameters['source_box']
        data['decoded_roi_height_fraction_of_source']=(by2-by1+1)/(sy2-sy1)
        if case.family=='occlusion':
            mx1,my1,mx2,my2=case.parameters['mask_box']
            intersection=max(0,min(bx2+1,mx2)-max(bx1,mx1))*max(0,min(by2+1,my2)-max(by1,my1))
            data['decoded_roi_mask_overlap_fraction']=intersection/max(1,(bx2-bx1+1)*(by2-by1+1))
    return {**data,'payload_matches':matches,'review_flags':flags}


def safe_output(path):
    output=Path(path).resolve()
    reports=Path.cwd().resolve()/'reports'
    if output==reports or reports not in output.parents:
        raise ValueError('Output must be a subdirectory of workspace reports, never dataset/holdout')
    return output


def run(client, output):
    output=safe_output(output)
    if output.exists() and any(path.is_symlink() for path in output.rglob('*')):
        raise ValueError('Synthetic output must not contain symlinks')
    images=output/'images';images.mkdir(parents=True,exist_ok=True)
    (output/'NOTICE.txt').write_text(NOTICE,encoding='utf-8')
    config=client.get('/api/v1/config');config.raise_for_status();initial=config.json()
    rows=[]
    for case in generate():
        ok,encoded=cv2.imencode('.png',case.image)
        if not ok:raise RuntimeError('Failed to encode synthetic image')
        path=images/f'{case.name}.png'
        path.write_bytes(encoded.tobytes())
        row={'name':case.name,'family':case.family,'symbol':case.symbol,'image':f'images/{path.name}',
             'parameters':case.parameters,'sha256':hashlib.sha256(encoded).hexdigest()}
        try:
            response=client.post('/api/v1/analyze',files={'image':(path.name,encoded.tobytes(),'image/png')})
            row['http_status']=response.status_code
            response.raise_for_status()
            result=Analysis.model_validate(response.json())
            if result.config_version!=initial['config_version']:
                raise RuntimeError('API configuration changed during study')
            row.update(review(case,result))
        except (httpx.HTTPError, ValueError) as exc:
            # Transport/validation failures are technical errors, never RETAKE.
            row['technical_error']=type(exc).__name__
        rows.append(row)
    final=client.get('/api/v1/config');final.raise_for_status()
    if final.json()!=initial:raise RuntimeError('API configuration changed during study')
    report={'notice':NOTICE,'api_config':initial,'cases':rows,
            'counts':dict(Counter(row.get('decision','TECHNICAL_ERROR') for row in rows)),
            'occlusion_counts':{symbol:dict(Counter(row.get('decision','TECHNICAL_ERROR') for row in rows if row['family']=='occlusion' and row['symbol']==symbol)) for symbol in ('code128','qr')},
            'review_candidates':sum(bool(row.get('review_flags')) for row in rows)}
    (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    metrics=list(Analysis.model_fields['metrics'].annotation.model_fields)
    fields=['name','family','symbol','http_status','decision','quality_score','payload_matches','issues','review_flags','decoded_roi_height_fraction_of_source','decoded_roi_mask_overlap_fraction',*metrics]
    with (output/'results.csv').open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fields);writer.writeheader()
        for row in rows:
            flat={key:row.get(key) for key in fields if key not in metrics}
            flat.update(row.get('metrics',{}))
            writer.writerow(flat)
    text=['# Synthetic barcode stress study',NOTICE,'',f"Counts: {report['counts']}; review candidates: {report['review_candidates']}",
          f"Configuration: {initial['config_version']}",'',
          'Issue codes identify rules that fired; ACCEPT advisory issues do not imply rejection. Full metrics and thresholds are in JSON/CSV.',
          'Metric correspondence: BLUR→sharpness; TOO_DARK→brightness/dark_pixel_ratio; OVEREXPOSED→brightness/overexposed_pixel_ratio; LOW_CONTRAST→contrast; GLARE→glare; PERSPECTIVE→perspective; BARCODE_TOO_SMALL→area/width ratios; BARCODE_CROPPED→crop flags. Missing/failed/multiple decode are hard barcode gates. Scores combine all signals, so values remain available even without an issue code.',
          'Occlusion coverage is geometric mask area within the generated symbol bounds, not the fraction of information destroyed. Code128 can decode from remaining scanlines; QR has error correction.','',
          '| Image | Result | Score | Sharpness / brightness / contrast | Glare / perspective / area ratio | Issues | Review flags |','|---|---|---|---|---|---|---|']
    for row in rows:
        m=row.get('metrics',{})
        measured=lambda keys: ' / '.join(f'{m[key]:.3f}' for key in keys if key in m)
        text.append(f"| [{row['name']}]({row['image']}) | {row.get('decision','TECHNICAL_ERROR')} | {row.get('quality_score','')} | {measured(('sharpness','brightness','contrast'))} | {measured(('glare','perspective','barcode_area_ratio'))} | {', '.join(row.get('issues',[]))} | {', '.join(row.get('review_flags',[]))} |")
    (output/'report.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=NOTICE)
    parser.add_argument('--base',default='http://127.0.0.1:8080')
    parser.add_argument('--output',default='reports/barcode-stress')
    args=parser.parse_args()
    before=Path('config/thresholds.json').read_bytes()
    with httpx.Client(base_url=args.base,timeout=60,follow_redirects=False) as client:
        report=run(client,args.output)
    if Path('config/thresholds.json').read_bytes()!=before:
        raise RuntimeError('Local thresholds changed during study')
    print(json.dumps({key:report[key] for key in ('counts','review_candidates')}))
    if report['counts'].get('TECHNICAL_ERROR'):raise SystemExit(1)


if __name__=='__main__':main()
