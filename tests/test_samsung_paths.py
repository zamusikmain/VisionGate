import hashlib
import json
import zipfile

import pytest
from backend.gate import samsung_paths as paths


@pytest.fixture
def project(tmp_path,monkeypatch):
    root=tmp_path/'project';root.mkdir()
    monkeypatch.setattr(paths,'PROJECT_ROOT',root)
    monkeypatch.delenv('SAMSUNG_ARCHIVE_DIR',raising=False)
    return root


def originals(root):
    root.mkdir(parents=True,exist_ok=True)
    result=[]
    for name in paths.ARCHIVE_NAMES[:2]:
        p=root/name
        with zipfile.ZipFile(p,'w') as archive:archive.writestr('synthetic.txt',name)
        result.append(p)
    return result


def test_default_stays_under_project_when_cwd_changes(project,tmp_path,monkeypatch):
    expected=originals(project/'data/Samsung/original')
    outside=tmp_path/'outside';outside.mkdir();monkeypatch.chdir(outside)
    assert paths.input_archives()==expected


def test_environment_and_explicit_directory_are_relative_to_project(project,monkeypatch):
    configured=originals(project/'private/original')
    explicit=originals(project/'explicit')
    monkeypatch.setenv('SAMSUNG_ARCHIVE_DIR','private/original')
    assert paths.input_archives()==configured
    assert paths.input_archives('explicit')==explicit


def test_no_fallback_to_unrelated_directories(project,tmp_path):
    originals(tmp_path/'Downloads')
    with pytest.raises(FileNotFoundError):paths.input_archives()


def test_index_selects_preserved_version_and_checks_integrity(project):
    root=project/'data/Samsung/original';created=originals(root)
    alternative=root/'Approved_cases.source-deadbeef.zip';alternative.write_bytes(created[0].read_bytes())
    created[0].write_bytes(b'preserved-different-version')
    record={'Approved_cases.zip':{'filename':alternative.name,'sha256':hashlib.sha256(alternative.read_bytes()).hexdigest(),'bytes':alternative.stat().st_size}}
    (root/'archive-index.json').write_text(json.dumps(record),encoding='utf-8')
    assert paths.input_archives()[0]==alternative
    assert created[0].read_bytes()==b'preserved-different-version'
    alternative.write_bytes(b'changed')
    with pytest.raises(ValueError,match='ARCHIVE_INDEX_INTEGRITY_FAILED'):paths.input_archives()


@pytest.mark.parametrize('filename',['../outside.zip','sub\\outside.zip','/absolute.zip'])
def test_index_cannot_escape_private_input_directory(project,filename):
    root=project/'data/Samsung/original';originals(root)
    (root/'archive-index.json').write_text(json.dumps({'Approved_cases.zip':{'filename':filename}}),encoding='utf-8')
    with pytest.raises(ValueError,match='UNSAFE_ARCHIVE_INDEX'):paths.input_archives()
