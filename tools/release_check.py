"""Reject sensitive paths in the Git index, including files force-added by mistake."""
from pathlib import PurePosixPath
import subprocess

PRIVATE_DIRS = {
    'dataset', 'holdout', 'uploads', 'upload', 'data', 'reports', 'logs',
    'analysis-images', 'analysis_images', 'private-images', 'customer-data',
    'customer-datasets', 'tmp', 'temp', '.aws', '.ssh', '.venv',
    '.python-packages', '.audit-packages', 'node_modules', 'dist', 'build',
    '__pycache__', '.vscode', '.idea', '.pytest_cache', '.cache',
}
PRIVATE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.gif', '.bmp',
    '.tif', '.tiff', '.image', '.log', '.db', '.sqlite', '.sqlite3',
    '.avif', '.dng', '.raw', '.cr2', '.nef', '.jfif',
    '.pem', '.key', '.p12', '.pfx', '.zip', '.7z', '.tar', '.gz',
}
KEEP = {f'{directory}/{label}/.gitkeep'
        for directory in ('dataset', 'holdout') for label in ('good', 'bad')}


def forbidden(path):
    normalized = path.lower()
    if normalized in KEEP or normalized == '.env.example':
        return False
    file = PurePosixPath(normalized)
    return (bool(set(file.parts) & PRIVATE_DIRS)
            or file.suffix in PRIVATE_EXTENSIONS
            or file.name.startswith(('.env', 'credentials', 'secrets', '.test-'))
            or file.name in {'.npmrc', '.netrc', '.pypirc', '.ds_store', 'thumbs.db'})


def main():
    records = subprocess.check_output(['git', 'ls-files', '--stage', '-z'])
    blocked = []
    for record in records.split(b'\0'):
        if not record:
            continue
        metadata, name = record.split(b'\t', 1)
        path = name.decode('utf-8')
        if forbidden(path) or metadata.startswith(b'120000'):
            blocked.append(path)
    if blocked:
        print('Publication blocked: sensitive paths or symlinks in Git index:')
        print('\n'.join(blocked))
        raise SystemExit(1)
    print('Git index publication policy: passed (no sensitive paths or symlinks)')


if __name__ == '__main__':
    main()
