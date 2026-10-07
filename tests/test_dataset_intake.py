import json
from pathlib import Path
import subprocess
import sys
import cv2
import pytest
from tools.dataset_audit import audit_dataset, dataset_files
from tools.calibrate import evaluate
from tools.demo import clean_image
from backend.gate.config import Thresholds

def image_bytes():
    success,png=cv2.imencode('.png',clean_image());assert success;return png.tobytes()

@pytest.fixture
def dataset(tmp_path):
    root=tmp_path/'dataset';(root/'good').mkdir(parents=True);(root/'bad').mkdir()
    (root/'good'/'фото.dat').write_bytes(image_bytes())
    success,png=cv2.imencode('.png',cv2.GaussianBlur(clean_image(),(41,41),12));assert success
    (root/'bad'/'blur.png').write_bytes(png.tobytes())
    return root

def test_intake_validates_content_and_keeps_private_manifest(dataset):
    report=audit_dataset(dataset)
    assert report['ready_for_baseline'] and report['class_counts']=={'GOOD':1,'BAD':1}
    assert len(report['manifest_sha256'])==64
    assert 'ABC123456' not in json.dumps(report)
    assert 'quality_score' not in json.dumps(report)
    assert audit_dataset(dataset)['manifest_sha256']==report['manifest_sha256']

def test_intake_identifies_heif_and_corruption_without_silently_skipping(dataset):
    (dataset/'bad'/'phone.HEIC').write_bytes(b'\0\0\0\x18ftypheic\0\0\0\0heicmif1')
    (dataset/'bad'/'broken.png').write_bytes(b'bad')
    report=audit_dataset(dataset)
    assert not report['ready_for_baseline']
    assert {e['error'] for e in report['errors']}=={'UNSUPPORTED_HEIF','CORRUPTED_IMAGE'}

def test_conflicting_duplicate_labels_block_baseline(dataset):
    (dataset/'bad'/'same.png').write_bytes(image_bytes())
    report=audit_dataset(dataset)
    assert not report['ready_for_baseline']
    assert any(e['error']=='CONFLICTING_DUPLICATE_LABELS' for e in report['errors'])

def test_same_class_duplicates_are_reported(dataset):
    (dataset/'good'/'same.png').write_bytes(image_bytes())
    report=audit_dataset(dataset)
    assert report['ready_for_baseline'] and len(report['duplicates'])==1
    assert not report['duplicates'][0]['conflicting_labels']

def test_debug_copies_unicode_and_basename_collisions(dataset,tmp_path):
    (dataset/'good'/'фото.png').write_bytes(image_bytes())
    originals={p:p.read_bytes() for _,p in dataset_files(dataset)}
    rows,_=evaluate(dataset,Thresholds(),tmp_path/'debug')
    assert len(rows)==3
    assert len(list((tmp_path/'debug').rglob('*.debug.png')))==3
    assert all(p.read_bytes()==content for p,content in originals.items())
    assert all('sha256' in row for row in rows)

def test_symlink_escape_is_rejected(dataset,tmp_path):
    outside=tmp_path/'outside.png';outside.write_bytes(image_bytes())
    try:(dataset/'good'/'link.png').symlink_to(outside)
    except OSError as exc:pytest.skip(f'Host does not permit creating symlinks: {exc}')
    with pytest.raises(ValueError):list(dataset_files(dataset))

def test_cli_baseline_does_not_write_or_suggest_thresholds(dataset,tmp_path):
    before=Path('config/thresholds.json').read_bytes()
    output=tmp_path/'baseline'
    result=subprocess.run([sys.executable,'-m','tools.calibrate',str(dataset),'--output',str(output),'--debug'],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    report=json.loads((output/'report.json').read_text())
    assert report['current_config']==Thresholds().model_dump()
    assert 'suggested' not in report and not (output/'suggested-config.json').exists()
    assert Path('config/thresholds.json').read_bytes()==before
    assert all((output/name).exists() for name in ['report.json','report.csv','report.html'])
    assert all(row['config_version']==Thresholds().version for row in report['rows'])

def test_cli_rejects_output_inside_labelled_input(dataset):
    result=subprocess.run([sys.executable,'-m','tools.calibrate',str(dataset),'--output',str(dataset/'good'/'reports')],capture_output=True,text=True,timeout=30)
    assert result.returncode!=0 and 'outside the dataset' in result.stderr

def test_empty_dataset_has_no_invented_quality_or_accuracy(tmp_path):
    report=audit_dataset(tmp_path)
    assert not report['ready_for_baseline'] and report['class_counts']=={'GOOD':0,'BAD':0}
    assert {e['error'] for e in report['errors']}=={'EMPTY_CLASS'}
