"""Orientation regressions use synthetic fixtures, never customer datasets."""
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend import main
from backend.gate.decoder import ZXingDecoder, decode_attempts
from backend.gate.models import Barcode
from tools.orientation_check import FORMATS, fixture, expected_value, encode
from tools.barcode_stress import generate


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('HISTORY_DB',str(tmp_path/'history.sqlite3'))
    monkeypatch.setenv('GATE_CONFIG',str(tmp_path/'config.json'))
    monkeypatch.setenv('STORE_ANALYSIS_IMAGES','false')
    with TestClient(main.app) as client:
        yield client


def post(client,image,orientation=None):
    data,mime=encode(image,orientation)
    response=client.post('/api/v1/analyze',files={'image':('synthetic',data,mime)})
    assert response.status_code==200,response.text
    return response.json()


@pytest.mark.parametrize('name,value',FORMATS)
@pytest.mark.parametrize('turns',range(4))
def test_all_formats_via_api(client,name,value,turns):
    image=np.ascontiguousarray(np.rot90(fixture(name,value),turns))
    r=post(client,image); b=r['barcode']
    assert b['decoded'] and b['value']==expected_value(name,value)
    assert b['decode_method']=='original'  # Ordinary fast path remains intact.
    x1,y1,x2,y2=b['bounding_box']
    assert 0<=x1<x2<image.shape[1] and 0<=y1<y2<image.shape[0]


@pytest.mark.parametrize('orientation,turns',[(1,0),(3,2),(6,1),(8,3)])
def test_camera_exif_via_api(client,orientation,turns):
    image=np.ascontiguousarray(np.rot90(fixture('Code128','ABC123456'),turns))
    r=post(client,image,orientation)
    assert r['barcode']['value']=='ABC123456' and r['decision']=='ACCEPT'


@pytest.mark.parametrize('turns',range(4))
def test_real_rotation_sensitive_glare(client,turns):
    case=next(c for c in generate() if c.name=='qr-glare-0.1')
    image=np.ascontiguousarray(np.rot90(case.image,turns))
    r=post(client,image)
    assert r['barcode']['decoded'] and r['barcode']['value']==case.payload
    x1,y1,x2,y2=r['barcode']['bounding_box']
    assert 0<=x1<x2<image.shape[1] and 0<=y1<y2<image.shape[0]


@pytest.mark.parametrize('turns,expected',[(2,[[79,49],[59,49],[59,39],[79,39]]),
                                         (1,[[89,20],[89,40],[79,40],[79,20]]),
                                         (3,[[10,39],[10,19],[20,19],[20,39]])])
def test_fallback_geometry_and_budget(turns,expected):
    image=np.full((60,100,3),180,np.uint8)
    class Decoder:
        calls=0
        def decode(self,pixels):
            self.calls+=1
            if self.calls=={2:6,1:7,3:8}[turns]:
                assert pixels.flags.c_contiguous
                return [Barcode(detected=True,decoded=True,value='VALID',polygon=[[20,10],[40,10],[40,20],[20,20]],bounding_box=[20,10,40,20])]
            return []
    decoder=Decoder();b=decode_attempts(image,decoder)
    assert b.polygon==expected
    assert b.bounding_box==[min(p[0] for p in expected),min(p[1] for p in expected),max(p[0] for p in expected),max(p[1] for p in expected)]
    assert b.decode_method==f'rotated-{turns*90}'
    assert decoder.calls=={2:6,1:7,3:8}[turns]


@pytest.mark.parametrize('turns',range(4))
def test_cut_and_missing_symbols_never_accepted(client,turns):
    image=fixture('Code128','ABC123456')
    # Remove complete stop/start data columns, not merely redundant bar height.
    ys,xs=np.where(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)<128)
    image[:,int(xs.max())-40:]=210
    for sample in (image,np.full_like(image,210)):
        r=post(client,np.ascontiguousarray(np.rot90(sample,turns)))
        assert not r['barcode']['decoded'] and r['decision']=='RETAKE'


def test_rotated_errors_not_promoted_and_multiple_count_preserved():
    class Errors:
        calls=0
        def decode(self,image):
            self.calls+=1
            return [Barcode(detected=True,decoded=False,value=None,bounding_box=[1,1,20,20])]
    decoder=Errors();b=decode_attempts(fixture('Code128','ABC123456'),decoder)
    assert decoder.calls==8 and not b.decoded and b.value is None
    class Multiple:
        calls=0
        def decode(self,image):
            self.calls+=1
            if self.calls==6:
                return [Barcode(detected=True,decoded=True,value=value,bounding_box=box)
                        for value,box in [('A',[10,10,40,30]),('A',[60,10,90,30])]]
            return []
    assert decode_attempts(np.full((60,100,3),210,np.uint8),Multiple()).count==2
