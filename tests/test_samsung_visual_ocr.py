import hashlib
import cv2
import numpy as np
from tools import samsung_visual_ocr as pipeline


def test_predicted_roi_keeps_source_coordinates_and_single_evidence_group(monkeypatch):
    image=np.zeros((600,800,3),np.uint8);raw=cv2.imencode('.png',image)[1].tobytes()
    monkeypatch.setattr(pipeline,'read_pretrained',lambda *a,**k:dict(status='OK'))
    monkeypatch.setattr(pipeline,'extract_records',lambda *a:[dict(key='model',value='SM-A000',format_valid=True,source='test',variant='test-original',region=[[1,2],[9,2],[9,8],[1,8]],confidence=.9)])
    monkeypatch.setattr(pipeline,'scale2_bounded',lambda *a:(None,None))
    monkeypatch.setattr(pipeline,'ZXingDecoder',lambda:type('Empty',(),{'decode':lambda s,p:[]})())
    detection=dict(class_name='identification_region',confidence=.8,bbox=[100,200,300,250])
    result=pipeline.extract(raw,[detection])
    assert result['regions'][0]['bbox']==[90,197,310,253]
    assert not result['required_photo_checks_established'] and not result['photo_approval_produced']
    evidence=result['fields'][0]['evidence'][0]
    assert evidence['region'][0]==[91.,199.]
    assert evidence['evidence_group']==hashlib.sha256(raw).hexdigest()
    assert evidence['independent_evidence'] is False
    assert evidence['region_source']=='experimental_yolo_prediction'
