import json
import os
import sqlite3
import time
from contextlib import contextmanager
from uuid import UUID
from pathlib import Path

@contextmanager
def connection():
    path = Path(os.getenv('HISTORY_DB', 'data/history.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    try:
        db.execute('PRAGMA busy_timeout=10000')
        db.execute('CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY, result TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS audit (timestamp TEXT, config_version TEXT, config TEXT)')
        with db:
            yield db
    finally:
        db.close()

def save_result(result):
    safe = result.model_dump()
    safe['barcode']['value'] = None
    with connection() as db:
        db.execute('INSERT INTO history VALUES (?,?)', (result.request_id,json.dumps(safe)))
        db.execute('DELETE FROM history WHERE rowid NOT IN (SELECT rowid FROM history ORDER BY rowid DESC LIMIT 1000)')

def history():
    with connection() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT result FROM history ORDER BY rowid DESC LIMIT 100')]

def audit(config, timestamp):
    with connection() as db:
        db.execute('INSERT INTO audit VALUES (?,?,?)',(timestamp,config.version,config.model_dump_json()))

def store_image(data: bytes, request_id: str):
    enabled = os.getenv('STORE_ANALYSIS_IMAGES',os.getenv('STORE_IMAGES','false')).lower() == 'true'
    if not enabled:
        return
    name = str(UUID(request_id)) + '.image'
    root = Path(os.getenv('PRIVATE_IMAGE_DIR','data/private-images'))
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    path = root/name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as f:
            f.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    cutoff = time.time() - max(1,int(os.getenv('IMAGE_RETENTION_DAYS','7')))*86400
    for old in root.glob('*.image'):
        try:
            UUID(old.stem)
        except ValueError:
            continue
        try:
            if not old.is_symlink() and old.stat().st_mtime < cutoff:
                old.unlink(missing_ok=True)
        except (FileNotFoundError, PermissionError):
            # Windows may report access denied while another worker's deletion
            # is pending. Retry retention on the next save; do not fail analysis.
            pass
