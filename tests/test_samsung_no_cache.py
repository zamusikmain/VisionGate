import hashlib
import zipfile
import cv2
import numpy as np
from tools import samsung_run

def test_fresh_mode_ignores_poisoned_photo_cache_and_passes_no_ocr_cache(tmp_path,monkeypatch):
    output=tmp_path/'result';cache=output/'photo-cache';cache.mkdir(parents=True)
    archive=tmp_path/'input.zip';calls=[]
    with zipfile.ZipFile(archive,'w') as z:
        for i,role in enumerate(('device','scan')):
            raw=cv2.imencode('.jpg',np.full((240,320,3),100+i,np.uint8))[1].tobytes()
            z.writestr(f'Approved_000000000000001/{role}_000000000000001.jpg',raw)
            digest=hashlib.sha256(raw).hexdigest()
            (cache/f'{digest}-{role}-{samsung_run.fingerprint()}-1.json').write_text('POISONED OLD CACHE')
    def analyze(image,raw,role,**kw):
        assert kw['cache_dir'] is None
        calls.append(role)
        return samsung_run.invalid_photo(hashlib.sha256(raw).hexdigest(),role,'synthetic_no_cache_contract')
    monkeypatch.setattr(samsung_run,'analyze_photo',analyze)
    report=samsung_run.run([archive],output,cache_enabled=False)
    assert calls==['device','scan'] and report['cache_policy']['preexisting_ocr_cache_used'] is False
    assert all(p.read_text()=='POISONED OLD CACHE' for p in cache.iterdir())
