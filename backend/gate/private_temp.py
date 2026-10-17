"""Private OCR scratch directories with bounded Windows sharing-lock retries."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile
import time


@contextmanager
def private_directory(root,prefix='ocr-'):
    parent=Path(root).resolve();parent.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix=prefix,dir=parent)).resolve()
    # Verify the absolute recursive-delete target before any cleanup operation.
    if folder==parent or not folder.is_relative_to(parent) or folder.is_symlink():
        raise ValueError('UNSAFE_OCR_TEMP_DIRECTORY')
    try:
        yield str(folder)
    finally:
        for attempt in range(8):
            try:
                shutil.rmtree(folder)
                break
            except FileNotFoundError:
                break
            except PermissionError as exc:
                # Do not mask ACL errors or leave files silently. A transient
                # sharing violation after native OCR/virus scanning can clear.
                if getattr(exc,'winerror',None) not in {32,33} or attempt==7:raise
                time.sleep(min(1.,.05*2**attempt))
