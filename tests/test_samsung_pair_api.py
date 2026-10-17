from fastapi.testclient import TestClient
from backend import main


def test_production_flag_blocks_samsung_before_upload_processing(monkeypatch):
    monkeypatch.setenv('SAMSUNG_ENABLED','false')
    def forbidden(*args):raise AssertionError('Disabled module must not process uploads')
    monkeypatch.setattr(main,'process_samsung_case',forbidden)
    with TestClient(main.app) as client:
        assert client.get('/api/v1/capabilities').json()=={'barcode_qa':True,'samsung_enabled':False}
        response=client.post('/api/v1/samsung/validate-case',content=b'not multipart')
        assert response.status_code==503 and response.json()['error']=='SAMSUNG_DISABLED'
        assert response.headers['cache-control']=='no-store'
        assert client.get('/api/v1/health').status_code==200


def test_pair_multipart_contract_and_no_store(monkeypatch):
    def process(device,device_mime,scan,scan_mime):
        assert device==b'device-synthetic' and scan==b'scan-synthetic'
        return {'final_decision':'REJECTED','diagnostic_state':'UNKNOWN','rejection_basis':'insufficient_evidence'}
    monkeypatch.setattr(main,'process_samsung_case',process)
    with TestClient(main.app) as client:
        files={'device':('device.jpg',b'device-synthetic','image/jpeg'),'scan':('scan.jpg',b'scan-synthetic','image/jpeg')}
        r=client.post('/api/v1/samsung/validate-case',files=files)
        assert r.status_code==200 and r.json()['diagnostic_state']=='UNKNOWN'
        assert r.headers['cache-control']=='no-store'
        assert client.post('/api/v1/samsung/validate-case',files={'device':files['device']}).status_code==422
        assert client.post('/api/v1/samsung/validate-case',files=files,data={'expected':'APPROVED'}).status_code==422
        assert client.post('/api/v1/samsung/validate-case',files=[('device',files['device']),('scan',files['scan']),('device',files['device'])]).status_code==422


def test_samsung_ui_route_is_compiled_spa_only(tmp_path):
    from backend.render_app import create_app
    (tmp_path/'assets').mkdir();(tmp_path/'index.html').write_text('<html>synthetic-ui</html>')
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/samsung').status_code==200
        assert client.get('/reports/samsung-auto/results.json').status_code==404
        assert client.get('/dataset').status_code==404
