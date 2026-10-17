"""Optional installed Windows OCR adapter; no network, downloads, or OCR corrections."""
import json
import os
from pathlib import Path
import re
import subprocess
import hashlib
from .private_temp import private_directory

import cv2


def read_local_text(image):
    if os.name != 'nt': return {'status': 'LOCAL_OCR_UNAVAILABLE', 'lines': []}
    script = Path(__file__).resolve().parents[2] / 'tools' / 'windows_ocr.ps1'
    if not script.exists(): return {'status': 'LOCAL_OCR_UNAVAILABLE', 'lines': []}
    h, w = image.shape[:2]
    scale = min(1., 2400/max(h, w))
    bounded = cv2.resize(image, (max(1, round(w*scale)), max(1, round(h*scale)))) if scale < 1 else image
    try:
        private_root = Path(os.getenv('SAMSUNG_OCR_TEMP_DIR', 'reports/.ocr-temp'))
        private_root.mkdir(parents=True, exist_ok=True)
        with private_directory(private_root,prefix='visiongate-ocr-') as folder:
            path = Path(folder)/'input.png'
            ok, buffer = cv2.imencode('.png', bounded)
            if not ok: return {'status': 'LOCAL_OCR_INPUT_ERROR', 'lines': []}
            path.write_bytes(buffer.tobytes())
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(script),
                                     '-ImagePath', str(path)], capture_output=True, timeout=30)
            if result.returncode: return {'status': 'LOCAL_OCR_UNAVAILABLE', 'lines': []}
            data = json.loads(result.stdout.decode('utf-8-sig'))
            data.update(status='OK', coordinate_scale=scale)
            return data
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {'status': 'LOCAL_OCR_UNAVAILABLE', 'lines': []}


def field_candidates(ocr):
    """Context-tagged candidates, unverified and incomplete until reviewed.

    Bare digits and diagonal watermark tokens are never interpreted as identifiers.
    """
    from .samsung import Identifier
    found = {}
    for line in ocr.get('lines', []):
        text = line.get('text', '')
        patterns = [('imei_set', r'\bIMEI\s*[12]?\s*[:：]?\s*([0-9]{15})(?![0-9])'),
                    ('serial', r'(?:\bS\s*/\s*N|\bSerial(?:\s+No\.?)?)\s*[:：]?\s*([A-Za-z0-9-]{5,30})\b'),
                    ('model', r'\b(SM-[A-Za-z0-9/]{3,25})\b')]
        for key, pattern in patterns:
            values = re.findall(pattern, text, flags=re.I)
            if values: found.setdefault(key, set()).update(values)
    return [Identifier(key=key, values=sorted(values), complete=False, verified=False, source='local_ocr')
            for key, values in sorted(found.items())]


def read_local_variants(images, cache_dir=None):
    """One native process for a bounded group; cache keys depend only on pixels/version."""
    if len(images)>40: raise ValueError('TOO_MANY_OCR_VARIANTS')
    if os.name!='nt':return [{'status':'LOCAL_OCR_UNAVAILABLE','lines':[]} for _ in images]
    script=Path(__file__).resolve().parents[2]/'tools'/'windows_ocr.ps1'
    version=hashlib.sha256(script.read_bytes()).hexdigest()[:12]
    private=Path(os.getenv('SAMSUNG_OCR_TEMP_DIR','reports/.ocr-temp'));private.mkdir(parents=True,exist_ok=True)
    cache=Path(cache_dir) if cache_dir else None
    if cache:cache.mkdir(parents=True,exist_ok=True)
    output=[None]*len(images);missing=[]
    with private_directory(private,prefix='variants-') as folder:
        paths=[]
        for i,image in enumerate(images):
            ok,buffer=cv2.imencode('.png',image)
            if not ok:output[i]={'status':'LOCAL_OCR_INPUT_ERROR','lines':[]};continue
            key=hashlib.sha256(version.encode()+buffer.tobytes()).hexdigest()
            cached=cache/f'{key}.json' if cache else None
            if cached and cached.exists():
                try:output[i]=json.loads(cached.read_text(encoding='utf-8'));continue
                except (OSError,ValueError):pass
            path=Path(folder)/f'{i}.png';path.write_bytes(buffer.tobytes());paths.append(str(path))
            missing.append((i,cached))
        if missing:
            manifest=Path(folder)/'paths.json';manifest.write_text(json.dumps(paths),encoding='utf-8')
            try:
                result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-File',str(script),
                                       '-ManifestPath',str(manifest)],capture_output=True,timeout=120)
                records=json.loads(result.stdout.decode('utf-8-sig')) if result.returncode==0 else []
                if isinstance(records,dict):records=[records]
            except (OSError,ValueError,subprocess.TimeoutExpired):records=[]
            for j,(i,cached) in enumerate(missing):
                record=records[j] if j<len(records) else {'status':'LOCAL_OCR_UNAVAILABLE','lines':[]}
                record.setdefault('status','OK');output[i]=record
                if cached and record['status']=='OK':cached.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
    return output
