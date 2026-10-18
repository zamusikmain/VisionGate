import hashlib
import json
import cv2
import numpy as np
from tools import samsung_region_benchmark as module
from tools.samsung_region_annotations import initialize

def test_unvalidated_region_observation_never_becomes_a_confirmed_defect(tmp_path,monkeypatch):
    images=[];photos=[]
    for i,role in enumerate(['device','scan']):
        raw=cv2.imencode('.png',np.full((100,100,3),100+i,np.uint8))[1].tobytes()
        source=tmp_path/(role+'.png');source.write_bytes(raw);digest=hashlib.sha256(raw).hexdigest()
        images.append(dict(photo_id=role,sha256=digest,image=str(source),width=100,height=100,case_group='g',role=role,objects=[]))
        photos.append(dict(role=role,sha256=digest,fields=[],barcodes=[],checks={'screen_recapture_absent':dict(state='UNKNOWN',reason='unverified')},
                           mandatory_checks=['screen_recapture_absent'],extraction=dict(confirmed_imeis=[],confirmed_models=[]),label_index=None,
                           problems=[],screen_ui_ocr=dict(status='OK',reads=[])))
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(initialize(dict(images=images))))
    baseline=tmp_path/'baseline.json';baseline.write_text(json.dumps(dict(cases=[dict(case_id='g',photos=photos)])))
    monkeypatch.setattr(module,'display_boundaries',lambda _: [dict(polygon=[[0,0],[99,0],[99,99],[0,99]])])
    monkeypatch.setattr(module,'framed_gallery_evidence',lambda *a:dict(code='CANDIDATE',regions=[[1,1,5,5]],reason='unvalidated observation'))
    result=module.run(manifest,baseline,tmp_path/'output')
    assert result['cases'][0]['rejection_status']=='REJECTED_UNVERIFIED'
    assert all(not p['experimental_region_candidates'][0]['verified_defect'] for p in result['cases'][0]['photos'])
    assert not any(f['state']=='FAIL' for f in result['cases'][0]['findings'])
