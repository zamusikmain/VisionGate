import io
import zipfile
import pytest
from PIL import Image
from tools.samsung_intake import inspect_archives, compare_identifiers


def jpeg():
    out = io.BytesIO(); Image.new('RGB', (40, 60), 'white').save(out, format='JPEG'); return out.getvalue()


def archive(tmp_path, name, files):
    path = tmp_path / name
    with zipfile.ZipFile(path, 'w') as z:
        for key, data in files.items():
            info = zipfile.ZipInfo('placeholder')
            info.filename = key
            z.writestr(info, data)
    return path


def test_nested_label_duplicates_and_drm(tmp_path):
    files = {f'Approved_cases/Approved_490154203237518/{r}_490154203237518.jpg': jpeg() for r in ('device', 'scan')}
    a = archive(tmp_path, 'Approved.zip', files)
    b = archive(tmp_path, 'Rejected.zip', files | {'Description/VALIDATION.xlsx': b'<## NASCA DRM protected'})
    result = inspect_archives([a,b])
    assert result['ready_for_pair_baseline']
    assert len(result['cases']) == 1
    assert result['cases'][0]['labels'] == ['APPROVED']
    assert result['files'][-1]['status'] == 'NASCA_DRM_STOP'
    assert result['duplicates']


@pytest.mark.parametrize('name', ['../escape.jpg', '/abs.jpg', 'C:/abs.jpg', 'x\\file.jpg'])
def test_unsafe_paths(tmp_path, name):
    with pytest.raises(ValueError, match='UNSAFE_ARCHIVE_PATH'):
        inspect_archives([archive(tmp_path, 'x.zip', {name: b'x'})])


def test_missing_and_mismatched_member(tmp_path):
    result = inspect_archives([archive(tmp_path, 'x.zip', {
        'Approved_490154203237518/device_490154203237518.jpg': jpeg(),
        'Approved_490154203237518/scan_356938035643809.jpg': jpeg()})])
    assert not result['ready_for_pair_baseline']
    assert 'MISSING_PAIR_MEMBER' in result['cases'][0]['issues']
    assert result['errors'][0]['status'] == 'CASE_ID_MISMATCH'


def test_conflicting_labels(tmp_path):
    result = inspect_archives([archive(tmp_path, 'x.zip', {
        f'{label}_490154203237518/{role}_490154203237518.jpg': jpeg()
        for label in ('Approved','Rejected') for role in ('device','scan')})])
    assert not result['ready_for_pair_baseline']
    assert 'CONFLICTING_CASE_LABELS' in result['cases'][0]['issues']


def test_pair_states():
    a, b = '490154203237518', '356938035643809'
    assert compare_identifiers([a], [a])['status'] == 'MATCH'
    assert compare_identifiers([], [a])['status'] == 'REVIEW'
    assert compare_identifiers(['000-invalid'], [a])['status'] == 'REVIEW'
    assert compare_identifiers(['000000000000000'], ['000000000000000'])['status'] == 'REVIEW'
    assert compare_identifiers([a], [b])['status'] == 'MISMATCH'
    assert compare_identifiers([a,b], [a])['status'] == 'REVIEW'
