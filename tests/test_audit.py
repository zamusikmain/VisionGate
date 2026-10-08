"""Final audit: input integrity, real decoder geometry, lifecycle and concurrency.

Controlled synthetic regression only; these tests do not tune any thresholds.
"""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore, Event
from uuid import uuid4
import hashlib
import asyncio
import os
import sqlite3
import cv2
import numpy as np
import pytest
import zxingcpp
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from backend import main
from backend.gate import storage
from backend.gate.config import Thresholds, MAX_IMAGE_PIXELS, MAX_UPLOAD_BYTES
from backend.gate.decoder import ZXingDecoder, decode_attempts
from backend.gate.image_input import InvalidImage, read_image
from backend.gate.models import Barcode, Metrics
from backend.gate.pipeline import analyze
from backend.gate.decision_engine import decide
from tools.demo import clean_image


def encoded(image=None, format='PNG', **kwargs):
    if image is None: image = Image.fromarray(cv2.cvtColor(clean_image(),cv2.COLOR_BGR2RGB))
    stream = BytesIO(); image.save(stream,format=format,**kwargs)
    return stream.getvalue()


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('HISTORY_DB',str(tmp_path/'history.sqlite3'))
    monkeypatch.setenv('GATE_CONFIG',str(tmp_path/'config.json'))
    monkeypatch.setenv('PRIVATE_IMAGE_DIR',str(tmp_path/'private'))
    monkeypatch.setenv('STORE_ANALYSIS_IMAGES','false')
    monkeypatch.setenv('ADMIN_TOKEN','audit-test-key')
    with TestClient(main.app) as client: yield client


def post(client,data=None,mime='image/png',**kwargs):
    return client.post('/api/v1/analyze',files={'image':('photo.png',encoded() if data is None else data,mime)},**kwargs)


def test_thresholds_not_modified():
    assert hashlib.sha256(Path('config/thresholds.json').read_bytes()).hexdigest() == 'e346e8121e8419c5e630bb0289ab41f688d6a1f067f297551f87072a3e25e1fc'
    assert Thresholds.model_validate_json(Path('config/thresholds.json').read_text()) == Thresholds()


@pytest.mark.parametrize('quarter_turns',[0,1,2,3])
def test_real_decoding_and_final_decision_at_all_rotations(quarter_turns):
    image=np.ascontiguousarray(np.rot90(clean_image(),quarter_turns))
    r=analyze(image)
    assert r.barcode.decoded and r.barcode.value=='ABC123456'
    assert r.decision=='ACCEPT',r.model_dump()
    x1,y1,x2,y2=r.barcode.bounding_box
    assert 0<=x1<x2<image.shape[1] and 0<=y1<y2<image.shape[0]
    assert 0<=r.quality_score<=100


@pytest.mark.parametrize('orientation',range(1,9))
def test_exif_orientation_and_mirrors(orientation):
    clean=Image.fromarray(cv2.cvtColor(clean_image(),cv2.COLOR_BGR2RGB))
    inverse={2:Image.Transpose.FLIP_LEFT_RIGHT,3:Image.Transpose.ROTATE_180,4:Image.Transpose.FLIP_TOP_BOTTOM,
             5:Image.Transpose.TRANSPOSE,6:Image.Transpose.ROTATE_90,7:Image.Transpose.TRANSVERSE,8:Image.Transpose.ROTATE_270}
    raw=clean.transpose(inverse[orientation]) if orientation!=1 else clean
    exif=Image.Exif();exif[274]=orientation
    pixels=read_image(encoded(raw,'JPEG',quality=100,exif=exif),'image/jpeg')
    assert pixels.shape==clean_image().shape
    assert np.mean(np.abs(pixels.astype(float)-clean_image()))<1
    r=analyze(pixels)
    assert r.barcode.value=='ABC123456' and r.decision=='ACCEPT'


@pytest.mark.parametrize('format,mime',[('JPEG','image/jpeg'),('PNG','image/png'),('WEBP','image/webp')])
def test_formats_and_unspecified_mobile_mime(format,mime):
    data=encoded(format=format)
    assert analyze(read_image(data,mime)).barcode.decoded
    assert analyze(read_image(data,'application/octet-stream')).barcode.decoded
    with pytest.raises(InvalidImage,match='INVALID_IMAGE_TYPE'):read_image(data,'image/gif')


@pytest.mark.parametrize('brand',[b'heic',b'heix',b'mif1',b'msf1'])
def test_heif_container_rejected_explicitly(client,brand):
    data=b'\x00\x00\x00\x18ftyp'+brand+b'\x00\x00\x00\x00heicmif1'
    response=post(client,data,'image/heic')
    assert response.status_code==422 and response.json()['error']=='UNSUPPORTED_HEIF'
    assert response.headers['X-Request-ID']==response.json()['request_id']


def test_actual_large_image_boundary():
    assert MAX_IMAGE_PIXELS==24_000_000
    allowed=encoded(Image.new('L',(6000,4000),128))
    pixels=read_image(allowed,'image/png')
    assert pixels.shape==(4000,6000,3)
    del pixels
    oversized=encoded(Image.new('L',(6000,4001),128))
    with pytest.raises(InvalidImage,match='INVALID_IMAGE_DIMENSIONS'):read_image(oversized,'image/png')
    with pytest.raises(InvalidImage,match='FILE_TOO_LARGE'):read_image(b'x'*(MAX_UPLOAD_BYTES+1))


def test_decompression_bomb_and_truncation(monkeypatch):
    with pytest.raises(InvalidImage):read_image(encoded(format='JPEG')[:300],'image/jpeg')
    png=bytearray(encoded());png[-5]^=255
    with pytest.raises(InvalidImage):read_image(bytes(png),'image/png')
    monkeypatch.setattr(Image,'MAX_IMAGE_PIXELS',100)
    with pytest.raises(InvalidImage):read_image(encoded(),'image/png')


def test_animation_rejected_and_transparent_content_not_decoded():
    frames=[Image.new('RGB',(64,64),color) for color in ['white','black']]
    with pytest.raises(InvalidImage,match='UNSUPPORTED_ANIMATION'):
        read_image(encoded(frames[0],save_all=True,append_images=frames[1:]),'image/png')
    rgba=Image.fromarray(cv2.cvtColor(clean_image(),cv2.COLOR_BGR2RGB)).convert('RGBA')
    rgba.putalpha(0)
    pixels=read_image(encoded(rgba),'image/png')
    assert np.all(pixels==255)
    assert analyze(pixels).decision=='RETAKE'
    rgba.putalpha(255)
    assert analyze(read_image(encoded(rgba),'image/png')).barcode.decoded


def bars(value='ABC123456'):
    return np.asarray(zxingcpp.create_barcode(value,zxingcpp.BarcodeFormat.Code128).to_image(scale=4))


@pytest.mark.parametrize('second_value',['XYZ987654','ABC123456'])
@pytest.mark.parametrize('quarter_turns',range(4))
def test_multiple_real_barcodes_are_rejected(second_value,quarter_turns):
    canvas=np.full((1200,1000),210,np.uint8)
    for value,y in [('ABC123456',200),(second_value,800)]:
        code=bars(value);h,w=code.shape
        canvas[y:y+h,200:200+w]=code
    r=analyze(cv2.cvtColor(np.ascontiguousarray(np.rot90(canvas,quarter_turns)),cv2.COLOR_GRAY2BGR))
    assert r.barcode.decoded and r.barcode.count==2
    assert r.decision=='RETAKE' and r.issues[0]=='MULTIPLE_BARCODES'


def test_real_readable_barcode_near_edge_not_rejected_for_margin_alone():
    code=bars();h,w=code.shape
    canvas=np.full((400,2500),210,np.uint8)
    canvas[100:100+h,:w]=code
    r=analyze(cv2.cvtColor(canvas,cv2.COLOR_GRAY2BGR))
    assert r.barcode.decoded and r.metrics.possible_crop and not r.metrics.critical_crop
    assert r.decision=='ACCEPT',r.model_dump()
    x1,y1,x2,y2=r.barcode.bounding_box
    cropped=canvas[:,x1+10:x2+1]
    assert analyze(cv2.cvtColor(cropped,cv2.COLOR_GRAY2BGR)).decision=='RETAKE'


def test_decoder_stops_on_success_and_does_not_accept_localization_only():
    class Decoder:
        calls=0
        def decode(self,image):
            self.calls+=1
            return [Barcode(detected=True,decoded=True,value='TEST',bounding_box=[50,50,250,150])]
    decoder=Decoder();b=decode_attempts(clean_image(),decoder)
    assert decoder.calls==1 and b.decode_method=='original'
    class Missing:
        calls=0
        def decode(self,image):self.calls+=1;return []
    missing=Missing();r=analyze(clean_image(),decoder=missing)
    assert missing.calls==8 and r.decision=='RETAKE' and not r.barcode.decoded


@pytest.mark.parametrize('field',['sharpness','brightness','contrast','glare','perspective'])
def test_nonfinite_metrics_rejected(field):
    with pytest.raises(ValidationError):Metrics(**{field:float('nan')})
    with pytest.raises(ValidationError):Metrics(**{field:float('inf')})


def test_hard_decode_requirement_even_at_minimum_score():
    metrics=Metrics(sharpness=10000,brightness=150,contrast=100,barcode_area_ratio=.9,barcode_width_ratio=.9)
    b=Barcode(detected=True,decoded=False,count=1)
    assert decide(b,metrics,Thresholds(quality_score_min=0))[0]=='RETAKE'

def test_legal_extreme_aspect_ratio_does_not_resize_to_zero_pixels():
    image=np.full((200000,32,3),180,np.uint8)
    class Decoder:
        def decode(self,pixels):
            return [Barcode(detected=True,decoded=True,value='adapter-fixture',bounding_box=[1,100,30,2000],count=1)]
    result=analyze(image,decoder=Decoder())
    assert result.decision=='RETAKE' and 0<=result.quality_score<=100

def test_http_busy_and_unicode_admin_headers(client,monkeypatch):
    monkeypatch.setattr(main,'analysis_slots',BoundedSemaphore(1))
    main.analysis_slots.acquire()
    try:
        response=post(client)
        assert response.status_code==503 and response.json()['error']=='BUSY'
        assert response.headers['X-Request-ID']==response.json()['request_id']
    finally:main.analysis_slots.release()
    assert client.get('/api/v1/history',headers={b'X-Admin-Token':b'\xff'}).status_code==403


@pytest.mark.parametrize('body,headers',[(b'',{}),(b'{}',{'Content-Type':'application/json'}),(b'bad',{'Content-Type':'multipart/form-data'})])
def test_missing_or_malformed_upload(client,body,headers):
    response=client.post('/api/v1/analyze',content=body,headers=headers)
    assert response.status_code in {400,422}
    assert response.json()['request_id']==response.headers['X-Request-ID']
    assert response.headers['Cache-Control']=='no-store'


def test_api_duplicate_fields_extra_fields_and_repeated_submission(client):
    data=encoded()
    duplicates=[('image',('first.png',data,'image/png')),('image',('second.png',data,'image/png'))]
    assert client.post('/api/v1/analyze',files=duplicates).status_code==422
    assert client.post('/api/v1/analyze',files={'image':('a.png',data,'image/png')},data={'unexpected':'hidden'}).status_code==422
    first=post(client,data);second=post(client,data)
    assert first.status_code==second.status_code==200
    assert first.json()['decision']==second.json()['decision']=='ACCEPT'
    assert first.json()['request_id']!=second.json()['request_id']
    history=client.get('/api/v1/history',headers={'X-Admin-Token':'audit-test-key'}).json()
    assert len(history)==2 and all(r['barcode']['value'] is None for r in history)


def test_size_headers_and_validation_errors(client,monkeypatch):
    for length in ['invalid','-1',str(MAX_UPLOAD_BYTES+65537)]:
        response=client.post('/api/v1/analyze',content=b'x',headers={'Content-Length':length})
        assert response.status_code==(413 if length.isdigit() else 400)
        assert response.json()['request_id']==response.headers['X-Request-ID']
        assert response.headers['Cache-Control']=='no-store'
    response=client.put('/api/v1/config',json={'quality_score_min':'private-payload'},headers={'X-Admin-Token':'audit-test-key'})
    assert response.status_code==422 and 'private-payload' not in response.text
    assert response.json()['error']=='INVALID_REQUEST'


def test_multipart_files_closed_on_success_validation_and_stream_limit(client,monkeypatch):
    import starlette.formparsers as parser
    original=parser.SpooledTemporaryFile
    opened=[]
    def tracked(*args,**kwargs):
        f=original(*args,**kwargs);opened.append(f);return f
    monkeypatch.setattr(parser,'SpooledTemporaryFile',tracked)
    assert post(client,encoded()+b'\0'*(1100*1024)).status_code==200
    assert post(client,b'broken'+b'\0'*(1100*1024)).status_code==422
    assert opened and all(f.closed for f in opened)
    monkeypatch.setattr(main,'MAX_UPLOAD_BYTES',100)
    # Generator body supplies no Content-Length and crosses limit mid-parse.
    prefix=b'--audit\r\nContent-Disposition: form-data; name="image"; filename="x.png"\r\nContent-Type: image/png\r\n\r\n'
    def chunks():
        yield prefix+b'a'*1000
        yield b'b'*70000
        yield b'\r\n--audit--\r\n'
    response=client.post('/api/v1/analyze',content=chunks(),headers={'Content-Type':'multipart/form-data; boundary=audit'})
    assert response.status_code==413,response.text
    assert all(f.closed for f in opened)

def test_unfinished_multipart_does_not_leave_an_unowned_tempfile(client,monkeypatch):
    import starlette.formparsers as parser
    original=parser.SpooledTemporaryFile;opened=[]
    def tracked(*args,**kwargs):
        f=original(*args,**kwargs);opened.append(f);return f
    monkeypatch.setattr(parser,'SpooledTemporaryFile',tracked)
    incomplete=b'--audit\r\nContent-Disposition: form-data; name="image"; filename="x.png"\r\nContent-Type: image/png\r\n\r\n'+encoded()+b'\0'*(1100*1024)
    response=client.post('/api/v1/analyze',content=incomplete,headers={'Content-Type':'multipart/form-data; boundary=audit'})
    assert response.status_code==422
    assert opened and all(f.closed for f in opened)

def test_actual_chunked_body_limit_closes_partial_multipart(monkeypatch):
    import starlette.formparsers as parser
    original=parser.SpooledTemporaryFile;opened=[]
    def tracked(*args,**kwargs):
        f=original(*args,**kwargs);opened.append(f);return f
    monkeypatch.setattr(parser,'SpooledTemporaryFile',tracked)
    monkeypatch.setattr(main,'MAX_UPLOAD_BYTES',100)
    prefix=b'--audit\r\nContent-Disposition: form-data; name="image"; filename="x.png"\r\nContent-Type: image/png\r\n\r\n'
    messages=iter([{'type':'http.request','body':prefix+b'a'*1000,'more_body':True},{'type':'http.request','body':b'b'*70000,'more_body':False}])
    output=[]
    async def exercise():
        never=asyncio.Event()
        async def receive():
            try:return next(messages)
            except StopIteration:await never.wait()
        async def send(message):output.append(message)
        scope={'type':'http','method':'POST','path':'/api/v1/analyze','raw_path':b'/api/v1/analyze','query_string':b'','headers':[(b'content-type',b'multipart/form-data; boundary=audit')],'scheme':'http','server':('test',80),'client':('test',1),'http_version':'1.1','asgi':{'version':'3.0','spec_version':'2.0'}}
        await asyncio.wait_for(main.app(scope,receive,send),5)
    asyncio.run(exercise())
    assert output[0]['status']==413
    assert opened and all(f.closed for f in opened)

def test_parallel_api_uploads_are_consistent_and_redacted(client):
    def send(i):
        value=f'AUD{i:06d}';code=bars(value);h,w=code.shape
        canvas=np.full((600,1000),210,np.uint8);canvas[200:200+h,200:200+w]=code
        response=post(client,encoded(Image.fromarray(canvas)))
        if response.status_code==200:assert response.json()['barcode']['value']==value
        return response
    with ThreadPoolExecutor(max_workers=8) as pool:responses=list(pool.map(send,range(16)))
    assert all(r.status_code in {200,503} for r in responses)
    assert len({r.json()['request_id'] for r in responses})==16
    success=[r for r in responses if r.status_code==200]
    assert success and all(r.json()['decision']=='ACCEPT' for r in success)
    records=client.get('/api/v1/history',headers={'X-Admin-Token':'audit-test-key'}).json()
    assert len(records)==len(success) and all(r['barcode']['value'] is None for r in records)

def test_concurrent_config_audit_has_no_partial_json_or_temp_leak(tmp_path,monkeypatch):
    # All writers save the SAME initial defaults in a private test directory.
    # This never changes production thresholds or searches for better scores.
    monkeypatch.setenv('GATE_CONFIG',str(tmp_path/'config.json'))
    monkeypatch.setenv('HISTORY_DB',str(tmp_path/'history.sqlite3'))
    monkeypatch.setenv('ADMIN_TOKEN','audit-test-key')
    with ThreadPoolExecutor(max_workers=4) as pool:
        saved=list(pool.map(lambda _:main.set_config(Thresholds(),'audit-test-key'),range(12)))
    assert all(r['config_version']==Thresholds().version for r in saved)
    assert Thresholds.model_validate_json((tmp_path/'config.json').read_text())==Thresholds()
    assert not list(tmp_path.glob('*.tmp'))
    with storage.connection() as db:assert db.execute('SELECT COUNT(*) FROM audit').fetchone()[0]==12

def test_windows_transient_config_replace_error_is_retried(tmp_path,monkeypatch):
    monkeypatch.setenv('GATE_CONFIG',str(tmp_path/'config.json'));monkeypatch.setenv('HISTORY_DB',str(tmp_path/'history.sqlite3'));monkeypatch.setenv('ADMIN_TOKEN','audit-test-key')
    original=Path.replace;attempts=[]
    def replace(path,target):
        attempts.append(path)
        if len(attempts)<=2:raise PermissionError('transient sharing violation')
        return original(path,target)
    monkeypatch.setattr(Path,'replace',replace)
    assert main.set_config(Thresholds(),'audit-test-key')['config_version']==Thresholds().version
    assert len(attempts)==3 and not list(tmp_path.glob('*.tmp'))


def test_system_error_does_not_leak_and_slot_is_reusable(client,monkeypatch):
    monkeypatch.setattr(main,'analysis_slots',BoundedSemaphore(1))
    original=main.analyze
    def fail(*args):raise RuntimeError('sensitive-decoded-value')
    monkeypatch.setattr(main,'analyze',fail)
    response=post(client)
    assert response.status_code==500 and 'sensitive-decoded-value' not in response.text
    assert response.json()['error']=='SYSTEM_ERROR'
    monkeypatch.setattr(main,'analyze',original)
    assert post(client).status_code==200


def test_capacity_limit_owned_by_worker(client,monkeypatch):
    monkeypatch.setattr(main,'analysis_slots',BoundedSemaphore(1))
    entered=Event();release=Event();original=main.analyze
    def slow(*args):
        entered.set();assert release.wait(5);return original(*args)
    monkeypatch.setattr(main,'analyze',slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(main.process_image,encoded(),'image/png',str(uuid4()))
        assert entered.wait(5)
        try:
            with pytest.raises(HTTPException) as exc:main.process_image(encoded(),'image/png',str(uuid4()))
            assert exc.value.status_code==503 and exc.value.detail=='BUSY'
        finally:release.set()
        assert first.result().decision=='ACCEPT'
    assert main.process_image(encoded(),'image/png',str(uuid4())).decision=='ACCEPT'


def test_concurrent_history_connections_closed_and_retention_race(tmp_path,monkeypatch):
    monkeypatch.setenv('HISTORY_DB',str(tmp_path/'history.sqlite3'))
    result=analyze(clean_image())
    def write(i):
        copy=result.model_copy(update={'request_id':str(uuid4())})
        storage.save_result(copy)
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(write,range(24)))
    assert len(storage.history())==24
    with storage.connection() as db:assert db.execute('SELECT COUNT(*) FROM history').fetchone()[0]==24
    with pytest.raises(sqlite3.ProgrammingError):db.execute('SELECT 1')
    root=tmp_path/'private';root.mkdir()
    expired=root/(str(uuid4())+'.image');expired.write_bytes(b'old');os.utime(expired,(0,0))
    other=root/'unrelated.image';other.write_bytes(b'keep');os.utime(other,(0,0))
    monkeypatch.setenv('PRIVATE_IMAGE_DIR',str(root));monkeypatch.setenv('STORE_ANALYSIS_IMAGES','true')
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:storage.store_image(b'new',str(uuid4())),range(16)))
    assert not expired.exists() and other.exists()
    assert len(list(root.glob('*.image')))==17
