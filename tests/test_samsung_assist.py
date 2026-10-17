import hashlib
import cv2
import numpy as np
import pytest
from tools.samsung_assist import extract_region

def test_manual_region_is_bound_to_image_and_cannot_override_photo_checks(monkeypatch):
    from tools import samsung_assist as module
    image=np.zeros((160,200,3),np.uint8);data=cv2.imencode('.png',image)[1].tobytes()
    manifest=dict(image_sha256=hashlib.sha256(data).hexdigest(),role='scan',quad=[[20,30],[170,30],[170,120],[20,120]])
    monkeypatch.setattr(module,'read_pretrained',lambda *a,**k:dict(lines=[],seconds=0))
    result=extract_region(data,manifest)
    assert result['manual_region'] and not result['automatic'] and not result['approval_produced']
    assert not result['required_photo_checks_established'] and not image.any()
    manifest['image_sha256']='0'*64
    with pytest.raises(ValueError,match='HASH_MISMATCH'):extract_region(data,manifest)

def test_region_cannot_invent_pixels_outside_the_source():
    data=cv2.imencode('.png',np.zeros((100,100,3),np.uint8))[1].tobytes()
    with pytest.raises(ValueError,match='OUTSIDE_IMAGE'):
        extract_region(data,dict(image_sha256=hashlib.sha256(data).hexdigest(),role='device',quad=[[-1,0],[99,0],[99,99],[0,99]]))
