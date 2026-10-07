"""HTTP smoke for the single-service image, using generated synthetic data only."""
import argparse
from io import BytesIO
import re
import cv2
import httpx
from PIL import Image
from tools.demo import clean_image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:18080')
    args = parser.parse_args()
    with httpx.Client(base_url=args.base, timeout=60) as client:
        home = client.get('/')
        assert home.status_code == 200
        assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', home.text)
        assert assets
        for asset in assets:
            assert client.get(asset).status_code == 200
        assert client.get('/api/v1/health').json()['status'] == 'ok'
        assert client.get('/api/v1/config').json()['config_version'] == '01752f78a17d'
        assert client.get('/docs').status_code == 200
        assert '/api/v1/analyze' in client.get('/openapi.json').json()['paths']
        assert client.get('/api/v1/history').status_code == 403
        for path in ('/.env', '/data/history.sqlite3', '/config/thresholds.json', '/api/missing'):
            assert client.get(path).status_code == 404
        encoded = BytesIO()
        Image.fromarray(cv2.cvtColor(clean_image(), cv2.COLOR_BGR2RGB)).save(encoded, format='PNG')
        ids = set()
        for _ in range(2):
            response = client.post('/api/v1/analyze', files={'image': ('synthetic.png', encoded.getvalue(), 'image/png')})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['decision'] == 'ACCEPT'
            assert result['config_version'] == '01752f78a17d'
            ids.add(result['request_id'])
        assert len(ids) == 2
        assert client.post('/api/v1/analyze', files={'image': ('broken.png', b'broken', 'image/png')}).status_code == 422
        response = client.post('/api/v1/analyze', files={'image': ('large.png', b'x' * (12 * 1024 * 1024 + 1), 'image/png')})
        assert response.status_code == 413 and response.json()['error'] == 'FILE_TOO_LARGE'
        assert response.headers['X-Request-ID']
        encoded = BytesIO()
        Image.new('RGB', (6000, 4000), 'white').save(encoded, format='PNG')
        response = client.post('/api/v1/analyze', files={'image': ('synthetic-24mp.png', encoded.getvalue(), 'image/png')})
        assert response.status_code == 200 and response.json()['decision'] == 'RETAKE'
        print('Single-service HTTP smoke passed: frontend/assets/API/docs, protected paths, repeat, corrupt, 12MiB cap and 24MP input')


if __name__ == '__main__':
    main()
