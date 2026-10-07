"""Run against the real Nginx/container API, record actual processing times."""
import json
from pathlib import Path
import httpx

def main():
    base='http://localhost:8080'
    records=[]
    with httpx.Client(timeout=60) as client:
        assert client.get(base).status_code==200
        assert client.get(base+'/docs').status_code==200
        assert client.get(base+'/openapi.json').status_code==200
        assert client.get(base+'/api/v1/health').json()['status']=='ok'
        assert client.get(base+'/api/v1/history').status_code==403
        for path in sorted(Path('demo/synthetic').rglob('*.png')):
            r=client.post(base+'/api/v1/analyze',files={'image':(path.name,path.read_bytes(),'image/png')})
            assert r.status_code==200,r.text
            payload=r.json()
            assert payload['decision']==('ACCEPT' if path.parent.name=='good' else 'RETAKE'),payload
            records.append({'filename':str(path),'decision':payload['decision'],'processing_time_ms':payload['processing_time_ms'],'issues':payload['issues']})
        assert client.post(base+'/api/v1/analyze',files={'image':('broken.png',b'broken','image/png')}).status_code==422
    Path('reports').mkdir(exist_ok=True)
    Path('reports/docker-smoke.json').write_text(json.dumps(records,indent=2))
    print(json.dumps(records,indent=2))

if __name__=='__main__':main()
