"""Local Samsung archive paths, independent of cwd and user-specific directories."""
import hashlib
import json
import os
from pathlib import Path

PROJECT_ROOT=Path(__file__).resolve().parents[2]
ARCHIVE_NAMES=('Approved_cases.zip','Rejected_cases.zip','Description.zip')


def original_directory(override=None):
    configured=override or os.getenv('SAMSUNG_ARCHIVE_DIR')
    directory=Path(configured).expanduser() if configured else Path('data/Samsung/original')
    return (directory if directory.is_absolute() else PROJECT_ROOT/directory).resolve()


def input_archives(directory=None):
    root=original_directory(directory)
    index_path=root/'archive-index.json'
    index=json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {}
    result=[]
    for name in ARCHIVE_NAMES:
        record=index.get(name,{})
        filename=record.get('filename',name)
        if not isinstance(filename,str) or Path(filename).name!=filename or '\\' in filename or '/' in filename:
            raise ValueError('UNSAFE_ARCHIVE_INDEX')
        path=root/filename
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('UNSAFE_ARCHIVE_INDEX')
        if not path.is_file():
            if name=='Description.zip' and name not in index:continue
            raise FileNotFoundError(f'Samsung archive missing: {path}')
        if record:
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if path.stat().st_size!=record.get('bytes') or digest!=record.get('sha256'):
                raise ValueError(f'ARCHIVE_INDEX_INTEGRITY_FAILED: {name}')
        result.append(path)
    return result
