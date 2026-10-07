"""Real container HTTP audit. Controlled synthetic inputs, no tuning."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import hashlib
import json
from pathlib import Path
from time import perf_counter
import cv2
import httpx
import numpy as np
from PIL import Image
from tools.demo import clean_image
from backend.gate.config import Thresholds

def png(image):
    if isinstance(image,np.ndarray):image=Image.fromarray(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
    buffer=BytesIO();image.save(buffer,format='PNG');return buffer.getvalue()

def main():
    base='http://localhost:8080';records=[];before=Path('config/thresholds.json').read_bytes()
    def check(client,name,data,mime='image/png',status=200,decision=None):
        start=perf_counter();response=client.post(base+'/api/v1/analyze',files={'image':(name,data,mime)})
        assert response.status_code==status,(name,response.status_code,response.text)
        body=response.json();assert body['request_id']==response.headers['X-Request-ID']
        assert response.headers['Cache-Control']=='no-store'
        if decision:assert body['decision']==decision,(name,body)
        records.append({'scenario':name,'status':status,'decision':body.get('decision'),'error':body.get('error'),'processing_time_ms':body.get('processing_time_ms'),'round_trip_ms':round((perf_counter()-start)*1000,2)})
        return body
    with httpx.Client(timeout=90) as client:
        assert client.get(base).status_code==200
        assert client.get(base+'/docs').status_code==200
        schema=client.get(base+'/openapi.json').json()
        assert schema['paths']['/api/v1/analyze']['post']['requestBody']['content']['multipart/form-data']
        assert client.get(base+'/api/v1/config').json()['thresholds']==Thresholds().model_dump()
        for turns in range(4):
            check(client,f'rotation-{turns*90}.png',png(np.ascontiguousarray(np.rot90(clean_image(),turns))),decision='ACCEPT')
        normalized=Image.fromarray(cv2.cvtColor(clean_image(),cv2.COLOR_BGR2RGB));exif=Image.Exif();exif[274]=6
        buffer=BytesIO();normalized.transpose(Image.Transpose.ROTATE_90).save(buffer,format='JPEG',quality=100,exif=exif)
        check(client,'exif-6.jpg',buffer.getvalue(),'image/jpeg',decision='ACCEPT')
        check(client,'empty.png',png(np.full((600,1000,3),180,np.uint8)),decision='RETAKE')
        check(client,'corrupt.png',b'broken',status=422)
        check(client,'heif.heic',b'\0\0\0\x18ftypheic\0\0\0\0heicmif1','image/heic',status=422)
        check(client,'spoof.jpg',png(clean_image()),'image/jpeg',status=422)
        check(client,'blank-mime.png',png(clean_image()),'application/octet-stream',decision='ACCEPT')
        check(client,'maximum-24mp.png',png(Image.new('L',(6000,4000),180)),decision='RETAKE')
        check(client,'over-24mp.png',png(Image.new('L',(6000,4001),180)),status=422)
        response=client.post(base+'/api/v1/analyze',content=b'x'*(12*1024*1024+70000),headers={'Content-Type':'application/octet-stream'})
        assert response.status_code==413
        records.append({'scenario':'oversized-body','status':response.status_code})
        response=client.post(base+'/api/v1/analyze',content=b'x'*(14*1024*1024),headers={'Content-Type':'application/octet-stream'})
        assert response.status_code==413
        assert response.json()['error']=='FILE_TOO_LARGE'
        assert response.json()['request_id']==response.headers['X-Request-ID']
        assert response.headers['Cache-Control']=='no-store'
        records.append({'scenario':'oversized-body-nginx-limit','status':response.status_code})
        data=png(clean_image())
        def concurrent(_):return client.post(base+'/api/v1/analyze',files={'image':('parallel.png',data,'image/png')})
        with ThreadPoolExecutor(max_workers=8) as pool:responses=list(pool.map(concurrent,range(24)))
        assert all(r.status_code in {200,503} for r in responses)
        assert len({r.json()['request_id'] for r in responses})==24
        assert all(r.json()['decision']=='ACCEPT' for r in responses if r.status_code==200)
        assert all(r.json()['error']=='BUSY' for r in responses if r.status_code==503)
        records.append({'scenario':'24-concurrent-submissions-8-client-workers','status_counts':dict(Counter(str(r.status_code) for r in responses))})
    assert Path('config/thresholds.json').read_bytes()==before
    report={'notice':'HTTP integrity/load smoke on synthetic inputs only; no threshold optimization or target-domain accuracy estimate.','threshold_file_sha256':hashlib.sha256(before).hexdigest(),'config_version':Thresholds().version,'scenarios':records}
    output=Path('reports/audit/docker-audit.json');output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
