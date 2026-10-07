from io import BytesIO
import cv2
import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError
from fastapi.testclient import TestClient
from backend.gate.config import Thresholds
from backend.gate.models import Barcode, Metrics
from backend.gate.decision_engine import decide
from backend.gate.image_input import read_image, InvalidImage
from backend.gate.decoder import ZXingDecoder, decode_attempts
from backend.gate.pipeline import analyze
from backend.main import app
from tools.demo import clean_image
from tools.calibrate import summary, optimize

@pytest.fixture
def good():
    return Metrics(sharpness=150,brightness=150,contrast=70,barcode_area_ratio=.1,barcode_width_ratio=.6,edge_margin=.1)

@pytest.mark.parametrize('change,expected',[(None,'ACCEPT'),('missing','RETAKE'),('decode','RETAKE'),('blur','RETAKE'),('small','RETAKE'),('crop','RETAKE'),('dark','RETAKE'),('overexposed','RETAKE'),('multiple','RETAKE')])
def test_decision(good,change,expected):
    b=Barcode(detected=True,decoded=True,count=1)
    if change=='missing': b.detected=False;b.decoded=False
    if change=='decode': b.decoded=False
    if change=='blur': good.sharpness=1
    if change=='small': good.barcode_area_ratio=.001
    if change=='crop': good.critical_crop=True
    if change=='dark': good.brightness=10
    if change=='overexposed': good.overexposed_pixel_ratio=.95
    if change=='multiple': b.count=2
    assert decide(b,good,Thresholds())[0]==expected

def test_margin_and_threshold(good):
    good.possible_crop=True
    b=Barcode(detected=True,decoded=True,count=1)
    assert decide(b,good,Thresholds())[0]=='ACCEPT'
    good.glare=.4;good.perspective=.5
    assert decide(b,good,Thresholds(quality_score_min=100))[0]=='RETAKE'

@pytest.mark.parametrize('kwargs',[{'brightness_min':250,'brightness_max':100},{'sharpness_critical':1000},{'barcode_area_min':-1},{'quality_score_min':101}])
def test_config_validation(kwargs):
    with pytest.raises(ValidationError):Thresholds(**kwargs)

@pytest.mark.parametrize('data',[b'not an image',b'\x89PNG\r\n\x1a\n'])
def test_corrupted(data):
    with pytest.raises(InvalidImage):read_image(data)

def test_image_security(monkeypatch):
    import backend.gate.image_input as module
    _,encoded=cv2.imencode('.png',clean_image())
    with pytest.raises(InvalidImage):read_image(encoded.tobytes(),'image/jpeg')
    monkeypatch.setattr(module,'MAX_IMAGE_PIXELS',100)
    with pytest.raises(InvalidImage):read_image(encoded.tobytes(),'image/png')
    monkeypatch.setattr(module,'MAX_UPLOAD_BYTES',10)
    with pytest.raises(InvalidImage):read_image(encoded.tobytes())

@pytest.mark.parametrize('transform',['clean','blur','resize','rotation','dark','contrast'])
def test_decode_regression(transform):
    image=clean_image()
    if transform=='blur':image=cv2.GaussianBlur(image,(3,3),.7)
    if transform=='resize':image=cv2.resize(image,None,fx=.75,fy=.75)
    if transform=='rotation':image=cv2.rotate(image,cv2.ROTATE_90_CLOCKWISE)
    if transform=='dark':image=(image*.6).astype('uint8')
    if transform=='contrast':image=(image*.5+60).astype('uint8')
    b=decode_attempts(image,ZXingDecoder())
    assert b.decoded and b.value=='ABC123456'

def test_pipeline():
    r=analyze(clean_image())
    assert r.decision=='ACCEPT'
    assert r.processing_time_ms>0 and r.config_version
    assert analyze(np.full((400,600,3),180,np.uint8)).decision=='RETAKE'
    assert analyze(cv2.GaussianBlur(clean_image(),(41,41),12)).decision=='RETAKE'
    assert analyze((clean_image()*.1).astype('uint8')).decision=='RETAKE'

def test_api(tmp_path,monkeypatch):
    monkeypatch.setenv('HISTORY_DB',str(tmp_path/'history.sqlite3'))
    monkeypatch.setenv('GATE_CONFIG',str(tmp_path/'thresholds.json'))
    monkeypatch.setenv('ADMIN_TOKEN','test-secret')
    client=TestClient(app)
    assert client.get('/api/v1/health').status_code==200
    assert client.get('/openapi.json').status_code==200
    assert client.get('/api/v1/config').json()['calibrated'] is False
    assert client.get('/api/v1/history').status_code==403
    assert client.post('/api/v1/analyze',files={'image':('fake.png',b'bad','image/png')}).status_code==422
    _,encoded=cv2.imencode('.png',clean_image())
    response=client.post('/api/v1/analyze',files={'image':('../../photo.png',encoded.tobytes(),'image/png')})
    assert response.status_code==200,response.text
    assert response.json()['decision']=='ACCEPT'
    assert response.headers['X-Request-ID']==response.json()['request_id']
    h=client.get('/api/v1/history',headers={'X-Admin-Token':'test-secret'}).json()
    assert h[0]['barcode']['value'] is None
    assert client.put('/api/v1/config',json=Thresholds().model_dump()).status_code==403
    assert client.put('/api/v1/config',json=Thresholds().model_dump(),headers={'X-Admin-Token':'test-secret'}).status_code==200

def test_report(good):
    rows=[{'expected':'GOOD','predicted':'ACCEPT'},{'expected':'BAD','predicted':'ACCEPT'},{'expected':'GOOD','predicted':'RETAKE'},{'expected':'BAD','predicted':'RETAKE'}]
    s=summary(rows)
    assert s['false_accept_rate']==.5 and s['false_reject_rate']==.5
    assert s['confusion_matrix']==[[1,1],[1,1]]
    assert summary([])['accuracy'] is None

def test_private_storage(tmp_path,monkeypatch):
    from backend.gate.storage import store_image
    from uuid import uuid4
    monkeypatch.setenv('PRIVATE_IMAGE_DIR',str(tmp_path/'private'))
    monkeypatch.setenv('STORE_ANALYSIS_IMAGES','false')
    store_image(b'pixels',str(uuid4()))
    assert not (tmp_path/'private').exists()
    monkeypatch.setenv('STORE_ANALYSIS_IMAGES','true')
    store_image(b'pixels',str(uuid4()))
    assert len(list((tmp_path/'private').glob('*.image')))==1
    with pytest.raises(ValueError):store_image(b'bad','../../evil')

@pytest.mark.parametrize('format_name,value',[('Code39','ABC123456'),('EAN13','5901234123457'),('EAN8','96385074'),('UPCA','012345678905'),('UPCE','01234565'),('ITF','12345678'),('QRCode','ABC123456'),('DataMatrix','ABC123456')])
def test_additional_formats(format_name,value):
    import zxingcpp
    code=zxingcpp.create_barcode(value,getattr(zxingcpp.BarcodeFormat,format_name))
    bars=np.asarray(code.to_image(scale=4))
    if bars.ndim==2:bars=cv2.cvtColor(bars,cv2.COLOR_GRAY2BGR)
    b=decode_attempts(bars,ZXingDecoder())
    # ZXing returns GTIN-13 text for these UPC fixtures, retaining UPC-E type.
    expected={'UPCA':'0012345678905','UPCE':'0012345000065'}.get(format_name,value)
    assert b.decoded and b.value==expected

def test_optimization(good):
    from types import SimpleNamespace
    b=Barcode(detected=True,decoded=True,count=1)
    r=SimpleNamespace(barcode=b,metrics=good)
    rows=[{'expected':'GOOD','predicted':'ACCEPT'},{'expected':'BAD','predicted':'ACCEPT'}]
    best=optimize(rows,[r,r],Thresholds(),{'quality_score_min':[75,100]})
    assert best['summary']['total']==2

