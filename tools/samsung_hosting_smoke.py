"""Verify an existing deployment using generated synthetic inputs only."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import time
import zipfile
import cv2
import httpx
import numpy as np
import zxingcpp
from backend.gate.samsung import valid_imei


def synthetic_pair():
    def imei(prefix):
        return next(prefix+str(i) for i in range(10) if valid_imei(prefix+str(i)))
    first,second=imei('99000000000001'),imei('99000000000002')
    def photo(value,device):
        pixels=np.full((540,760,3),210,np.uint8)
        cv2.rectangle(pixels,(90,160),(670,460),(255,255,255),-1)
        if device:cv2.polylines(pixels,[np.int32([[90,160],[200,70],[650,70],[670,160]])],True,(80,80,80),3)
        cv2.putText(pixels,'SYNTHETIC TEST',(105,210),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,0,0),2)
        cv2.putText(pixels,'IMEI1: '+value,(110,255),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,0,0),2)
        code=np.asarray(zxingcpp.create_barcode(value,zxingcpp.BarcodeFormat.Code128).to_image(scale=3))
        if code.ndim==2:code=cv2.cvtColor(code,cv2.COLOR_GRAY2BGR)
        code=cv2.resize(code,(510,100),interpolation=cv2.INTER_NEAREST);pixels[280:380,115:625]=code[:,:,:3]
        return cv2.imencode('.png',pixels)[1].tobytes()
    return photo(first,True),photo(first,False),photo(second,False)


def run(base,output):
    out=Path(output);out.mkdir(parents=True,exist_ok=True);start=time.perf_counter();checks=[]
    device,scan,other=synthetic_pair()
    for name,raw in [('device.png',device),('scan.png',scan),('other-scan.png',other)]: (out/name).write_bytes(raw)
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('synthetic/device.png',device);z.writestr('synthetic/scan.png',scan)
    (out/'synthetic-pair.zip').write_bytes(archive.getvalue())
    with httpx.Client(base_url=base,timeout=240,follow_redirects=True) as c:
        home=c.get('/samsung');home.raise_for_status();assets=re.findall(r'(?:src|href)="(/assets/[^\"]+)"',home.text);assert assets
        for asset in assets:
            response=c.get(asset);response.raise_for_status()
            local=Path('frontend/dist')/asset.removeprefix('/')
            assert local.exists() and hashlib.sha256(response.content).digest()==hashlib.sha256(local.read_bytes()).digest(),'STALE_FRONTEND_ASSET'
        checks.append('frontend/assets match local production build')
        assert c.get('/api/v1/health').json()['status']=='ok'
        assert c.get('/api/v1/capabilities').json()['samsung_enabled'] is True
        checks.append('backend and Samsung enabled')
        def pair(second):
            response=c.post('/api/v1/samsung/validate-case',files={'device':('device.png',device,'image/png'),'scan':('scan.png',second,'image/png')})
            response.raise_for_status();return response.json()
        same=pair(scan);assert same['final_decision']=='REJECTED' and same['rejection_status']=='REJECTED_UNVERIFIED'
        assert all(p['pretrained_ocr']['status']=='OK' for p in same['photos']),'OCR_UNAVAILABLE'
        (out/'same-case.json').write_text(json.dumps(same,indent=2),encoding='utf-8');checks.append('pair uses installed PP-OCRv5; UNKNOWN stays unverified')
        different=pair(other)
        assert different['rejection_status']=='REJECTED_CONFIRMED' and different['rejection_basis']=='identifier_mismatch'
        checks.append('independent synthetic mismatch confirmed')
        preview=c.post('/api/v1/samsung/batch/preview',files={'image':('synthetic.zip',archive.getvalue(),'application/zip')});preview.raise_for_status()
        (out/'batch-preview.json').write_text(json.dumps(preview.json(),indent=2),encoding='utf-8');checks.append('ZIP preview')
        report=dict(same,case_id='Synthetic case')
        exported=c.post('/api/v1/samsung/export',json={'cases':[report]});exported.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(exported.content)) as z:assert z.testzip() is None and 'xl/workbook.xml' in z.namelist()
        (out/'synthetic-results.xlsx').write_bytes(exported.content);checks.append('XLSX ZIP integrity')
        assert c.post('/api/v1/samsung/validate-case',files={'device':('broken.png',b'broken','image/png'),'scan':('scan.png',scan,'image/png')}).status_code==422
        assert c.post('/api/v1/samsung/batch/preview',files={'image':('broken.zip',b'broken','application/zip')}).status_code==422
        for path in ('/.env','/data/history.sqlite3','/data/Samsung/models/provenance.json','/reports/private.json'):
            assert c.get(path).status_code==404
        checks.append('corrupt uploads and private paths')
    summary=dict(base=base,synthetic_only=True,checks=checks,seconds=round(time.perf_counter()-start,2))
    (out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary));return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.base,a.output)
