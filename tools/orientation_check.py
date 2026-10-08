"""Synthetic orientation regressions over the real HTTP API; never calibration data."""
import argparse
from io import BytesIO
import json
from pathlib import Path
from statistics import median
import cv2
import httpx
import numpy as np
from PIL import Image
import zxingcpp
from tools.barcode_stress import generate

FORMATS = [('Code128','ABC123456'), ('Code39','ABC123456'), ('EAN13','5901234123457'),
           ('EAN8','96385074'), ('UPCA','012345678905'), ('UPCE','01234565'),
           ('ITF','12345678'), ('QRCode','ABC123456'), ('DataMatrix','ABC123456')]


def fixture(format_name, value):
    bars = np.asarray(zxingcpp.create_barcode(value, getattr(zxingcpp.BarcodeFormat, format_name)).to_image(scale=4))
    if bars.ndim == 3:
        bars = cv2.cvtColor(bars, cv2.COLOR_RGB2GRAY)
    h, w = bars.shape
    image = np.full((max(600,h+200), max(1000,w+200)),210,np.uint8)
    y,x = (image.shape[0]-h)//2,(image.shape[1]-w)//2
    image[y:y+h,x:x+w] = bars
    return cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)


def expected_value(name,value):
    return {'UPCA':'0012345678905','UPCE':'0012345000065'}.get(name,value)


def encode(image, orientation=None):
    image = Image.fromarray(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
    output = BytesIO()
    if orientation is None:
        image.save(output,format='PNG')
        return output.getvalue(),'image/png'
    exif = Image.Exif(); exif[274] = orientation
    image.save(output,format='JPEG',quality=100,exif=exif)
    return output.getvalue(),'image/jpeg'


def run(base):
    records=[]
    with httpx.Client(timeout=90) as client:
        def post(name,image,payload,orientation=None):
            data,mime=encode(image,orientation)
            response=client.post(base+'/api/v1/analyze',files={'image':('synthetic',data,mime)})
            response.raise_for_status(); result=response.json()
            barcode=result['barcode']
            assert not barcode['decoded'] or barcode['value']==payload,(name,barcode)
            records.append(dict(name=name,expected=payload,decoded=barcode['decoded'],value=barcode['value'],
                                decision=result['decision'],issues=result['issues'],method=barcode['decode_method'],
                                processing_time_ms=result['processing_time_ms']))
        for name,value in FORMATS:
            for turns in range(4):
                post(f'{name}-{turns*90}',np.ascontiguousarray(np.rot90(fixture(name,value),turns)),expected_value(name,value))
        case=next(c for c in generate() if c.name=='qr-glare-0.1')
        for turns in range(4):
            post(f'qr-glare-{turns*90}',np.ascontiguousarray(np.rot90(case.image,turns)),case.payload)
        inverse={1:0,3:2,6:1,8:3}
        for orientation,turns in inverse.items():
            post(f'exif-{orientation}',np.ascontiguousarray(np.rot90(fixture('Code128','ABC123456'),turns)),'ABC123456',orientation)
        clean=fixture('Code128','ABC123456')
        for index in range(10):
            for turns in (0,2):
                post(f'timing-Code128-{turns*90}-{index}',np.ascontiguousarray(np.rot90(clean,turns)),'ABC123456')
            post(f'timing-empty-{index}',np.full_like(clean,210),None)
    timing={prefix:median(r['processing_time_ms'] for r in records if r['name'].startswith(prefix))
            for prefix in ('timing-Code128-0-','timing-Code128-180-','timing-empty-')}
    return dict(notice='Synthetic only; no customer accuracy or completeness claim.',records=records,median_ms=timing)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://localhost:8080');parser.add_argument('--output',required=True)
    args=parser.parse_args(); report=run(args.base)
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(cases=len(report['records']),failures=[r['name'] for r in report['records'] if not r['decoded'] and r['expected']],median_ms=report['median_ms'])))
