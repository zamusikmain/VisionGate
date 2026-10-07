"""Deployment routing contract; no quality algorithm changes."""
from fastapi.testclient import TestClient
import pytest
from backend.render_app import create_app


@pytest.fixture
def render_client(tmp_path):
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'index.html').write_text('<html>VisionGate</html>')
    (tmp_path / 'assets' / 'app.js').write_text('console.log("asset")')
    with TestClient(create_app(tmp_path)) as client:
        yield client


def test_frontend_and_existing_api_share_one_origin(render_client):
    assert render_client.get('/').text == '<html>VisionGate</html>'
    assert render_client.get('/').headers['cache-control'] == 'no-store'
    assert render_client.get('/assets/app.js').status_code == 200
    assert render_client.get('/api/v1/health').json()['status'] == 'ok'
    assert render_client.get('/api/v1/config').json()['config_version'] == '01752f78a17d'
    assert render_client.get('/docs').status_code == 200
    assert '/api/v1/analyze' in render_client.get('/openapi.json').json()['paths']


@pytest.mark.parametrize('path', [
    '/api/unknown', '/data/history.sqlite3', '/config/thresholds.json',
    '/.env', '/backend/main.py', '/dataset/good/photo.jpg',
    '/assets/../index.html', '/assets/%2e%2e/index.html',
])
def test_runtime_and_source_files_are_not_public(render_client, path):
    assert render_client.get(path).status_code == 404


def test_missing_frontend_fails_startup(tmp_path):
    with pytest.raises(RuntimeError, match='Built frontend is missing'):
        create_app(tmp_path)
