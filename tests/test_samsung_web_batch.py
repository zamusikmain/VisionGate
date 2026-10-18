import base64
import io
import zipfile
from xml.etree import ElementTree as E
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend import main
from backend.gate.samsung_web import preview_archive

def image():
    out=io.BytesIO();Image.new('RGB',(64,64),'white').save(out,format='PNG');return out.getvalue()
def archive(entries):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        for name,content in entries:z.writestr(name,content)
    return out.getvalue()

def test_preview_suggests_roles_without_extracting_or_classifying(monkeypatch):
    monkeypatch.setattr(main,'process_samsung_case',lambda *args:pytest.fail('Preview must not classify'))
    raw=image();data=archive([('arbitrary/device.png',raw),('arbitrary/scan.png',raw),('unmatched.png',raw)])
    with TestClient(main.app) as c:
        r=c.post('/api/v1/samsung/batch/preview',files={'image':('input.zip',data,'application/zip')})
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    body=r.json();assert len(body['assets'])==3 and len(body['pairs'])==1
    assert base64.b64decode(body['assets'][0]['data'])==raw
    assert body['pairs'][0]['device']=='f1' and body['pairs'][0]['scan']=='f2'
    assert 'final_decision' not in body

@pytest.mark.parametrize('name',['../secret.png','/root.png','C:/secret.png','a\\b.png'])
def test_archive_traversal_rejected(name):
    data=archive([(name,image())])
    # Windows zipfile normalizes backslashes while writing; restore hostile
    # central/local entry names to exercise an actual incoming ZIP.
    if '\\' in name:data=data.replace(name.replace('\\','/').encode(),name.encode())
    with pytest.raises(ValueError,match='UNSAFE_ARCHIVE_PATH'):preview_archive(data)

def test_ambiguous_roles_never_choose_first_file():
    d=preview_archive(archive([('case/device.png',image()),('case/device.jpg',b'broken'),('case/scan.png',image())]))
    assert d['pairs'][0]['device']==''
    assert d['assets'][1]['error']=='CORRUPTED_IMAGE' and d['assets'][1]['data'] is None

def test_unsupported_files_and_corrupt_images_are_visible_for_correction():
    d=preview_archive(archive([('case/device.gif',b'GIF89a'),('case/scan.png',b'broken')]))
    assert [a['error'] for a in d['assets']]==['INVALID_IMAGE_TYPE','CORRUPTED_IMAGE']

def test_drm_and_invalid_zip_stop():
    with pytest.raises(ValueError,match='NASCA_DRM_STOP'):preview_archive(archive([('scan.jpg',b'<## NASCA protected')]))
    with pytest.raises(ValueError,match='INVALID_ZIP'):preview_archive(b'not zip')

def test_symlink_and_expansion_limits(monkeypatch):
    import backend.gate.samsung_web as web
    link=zipfile.ZipInfo('link.png');link.external_attr=(0o120777<<16)
    with pytest.raises(ValueError,match='UNSAFE_ARCHIVE_PATH'):preview_archive(archive([(link,b'target')]))
    monkeypatch.setattr(web,'MAX_EXPANDED',10)
    with pytest.raises(ValueError,match='ARCHIVES_TOO_LARGE'):preview_archive(archive([('x.png',image())]))

def test_web_export_unknown_has_no_expected_label_or_accuracy_and_no_formula():
    name='=HYPERLINK("https://invalid.example","x")'
    payload={'cases':[dict(case_id=name,final_decision='REJECTED',diagnostic_state='UNKNOWN',review_required=True,
        rejection_basis='insufficient_evidence',rejection_status='REJECTED_UNVERIFIED',findings=[{'code':'DEVICE_TOP_VISIBLE'}],photos=[])]}
    with TestClient(main.app) as c:
        r=c.post('/api/v1/samsung/export',json=payload)
        assert r.status_code==200 and r.headers['cache-control']=='no-store'
        assert r.headers['content-disposition'].endswith('"samsung-results.xlsx"')
        assert c.post('/api/v1/samsung/export',json={'cases':[]}).status_code==422
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        root=E.fromstring(z.read('xl/worksheets/sheet1.xml'))
        cell=root.find('.//s:c[@r="A9"]',ns)
        assert cell.get('t')=='inlineStr' and ''.join(cell.find('s:is',ns).itertext())==name
        assert not root.findall('.//s:f',ns)
        assert 'REJECTED_UNVERIFIED' in ''.join(root.itertext())
        assert 'accuracy is not measured' in ''.join(root.itertext())

def test_batch_disabled_and_permit_cleanup(monkeypatch):
    with TestClient(main.app) as c:
        monkeypatch.setenv('SAMSUNG_ENABLED','false')
        assert c.post('/api/v1/samsung/batch/preview',content=b'x').status_code==503
        assert c.post('/api/v1/samsung/export',json={}).status_code==503
        monkeypatch.setenv('SAMSUNG_ENABLED','true')
        from threading import BoundedSemaphore
        semaphore=BoundedSemaphore(1);monkeypatch.setattr(main,'analysis_slots',semaphore)
        assert c.post('/api/v1/samsung/batch/preview',files={'image':('x.zip',b'broken')}).status_code==422
        assert semaphore.acquire(blocking=False)
        try:assert c.post('/api/v1/samsung/batch/preview',files={'image':('x.zip',archive([('x.png',image())]))}).status_code==503
        finally:semaphore.release()
