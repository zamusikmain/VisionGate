"""Explicit, hash-pinned public weight download. Inference never calls this tool."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request


def setup(names,download=False):
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'config/samsung-models.json').read_text())
    for name in names:
        model=manifest[name];target=root/'data/Samsung/models'/model['repo'].split('/')[1]
        print(name,model['repo'],model['revision'],model['license'],model['bytes'],'bytes')
        if not download:continue
        target.mkdir(parents=True,exist_ok=True)
        for filename,digest in [('inference.onnx',model['sha256']),('inference.yml',model['config_sha256'])]:
            dest=target/filename
            if dest.exists():
                if hashlib.sha256(dest.read_bytes()).hexdigest()!=digest:raise ValueError('Existing different file preserved: '+str(dest))
                continue
            url='https://huggingface.co/'+model['repo']+'/resolve/'+model['revision']+'/'+filename
            with urllib.request.urlopen(url,timeout=120) as response:data=response.read()
            if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Download SHA-256 mismatch')
            if filename.endswith('.onnx') and len(data)!=model['bytes']:raise ValueError('Download size mismatch')
            temp=dest.with_suffix(dest.suffix+'.download');temp.write_bytes(data);temp.replace(dest)
        (target/'provenance.json').write_text(json.dumps(model,indent=2))
    if not download:print('Plan only. Use --download to fetch these public weights; no images are read or uploaded.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--models',nargs='+',choices=['mobile-det','latin-rec','server-det','server-rec'],default=['mobile-det','latin-rec'])
    p.add_argument('--download',action='store_true');a=p.parse_args();setup(a.models,a.download)
