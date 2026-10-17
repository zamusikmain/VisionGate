import pytest
from backend.gate import private_temp


def test_transient_windows_lock_is_retried_and_private_pixels_are_removed(tmp_path,monkeypatch):
    original=private_temp.shutil.rmtree;attempts=[]
    def locked(path):
        attempts.append(path)
        if len(attempts)<3:
            exc=PermissionError('sharing violation');exc.winerror=32;raise exc
        original(path)
    monkeypatch.setattr(private_temp.shutil,'rmtree',locked)
    monkeypatch.setattr(private_temp.time,'sleep',lambda _:None)
    with private_temp.private_directory(tmp_path) as directory:
        target=private_temp.Path(directory);(target/'pixels.png').write_bytes(b'private synthetic pixels')
    assert len(attempts)==3 and not target.exists() and tmp_path.exists()
    assert all(p.resolve().is_relative_to(tmp_path.resolve()) and p!=tmp_path for p in attempts)


def test_permanent_acl_error_is_not_hidden(tmp_path,monkeypatch):
    def denied(path):
        exc=PermissionError('ACL denied');exc.winerror=5;raise exc
    monkeypatch.setattr(private_temp.shutil,'rmtree',denied)
    with pytest.raises(PermissionError,match='ACL denied'):
        with private_temp.private_directory(tmp_path):pass
