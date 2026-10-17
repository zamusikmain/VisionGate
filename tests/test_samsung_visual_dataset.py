import hashlib
import json
import pytest
from tools.samsung_visual_dataset import CLASSES,export_yolo,split_groups,validate


def test_case_groups_cannot_leak_across_split():
    images=[dict(sha256=str(i),case_group=str(i//2)) for i in range(12)]
    split=split_groups(images)
    for group in {p['case_group'] for p in images}:
        assert len({split[p['sha256']] for p in images if p['case_group']==group})==1
    assert set(split.values())=={'train','val'}


def test_unreviewed_images_are_not_exported_as_negative_labels(tmp_path):
    images=[]
    for i in range(4):
        source=tmp_path/f'{i}.jpg';source.write_bytes(bytes([i]))
        images.append(dict(sha256=hashlib.sha256(source.read_bytes()).hexdigest(),image=str(source),case_group=str(i),objects=[],reviewed_classes=['phone_screen'] if i<3 else []))
    manifest=tmp_path/'annotations.json';manifest.write_text(json.dumps(dict(classes=list(CLASSES),images=images)))
    result=export_yolo(manifest,tmp_path/'export',classes=['phone_screen'])
    assert len(result['splits'])==3 and images[3]['sha256'] not in result['splits']
    assert len(list((tmp_path/'export/labels').rglob('*.txt')))==3


def test_degenerate_or_outside_boxes_rejected():
    p=dict(sha256='a'*64,case_group='group',objects=[dict(**{'class':'box'},bbox=[0,.2,1.1,.9])])
    with pytest.raises(ValueError,match='INVALID_BBOX'):validate(dict(classes=list(CLASSES),images=[p]))
