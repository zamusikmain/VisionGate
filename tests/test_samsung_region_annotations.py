import copy
import hashlib
import json
import pytest
from tools.samsung_region_annotations import CLASSES,initialize,validate,editor

def manifest(tmp_path):
    source=tmp_path/'x.jpg';source.write_bytes(b'synthetic')
    return initialize(dict(images=[dict(photo_id='P1',sha256=hashlib.sha256(b'synthetic').hexdigest(),image=str(source),width=100,height=100,case_group='g',objects=[])]))
def test_pending_is_not_a_negative_and_old_boxes_are_unreviewed(tmp_path):
    m=manifest(tmp_path);assert set(m['images'][0]['reviews'].values())=={'UNKNOWN'}
    m['images'][0]['reviews']['barcode']='PRESENT'
    with pytest.raises(ValueError,match='PRESENT_WITHOUT'):validate(m)
def test_polygon_bounds_degeneracy_and_review_consistency(tmp_path):
    m=manifest(tmp_path);p=m['images'][0]
    p['objects']=[dict(**{'class':'required_region'},polygon=[[.1,.1],[.9,.1],[.9,.8],[.1,.8]],reviewed=True)]
    p['reviews']['required_region']='PRESENT';validate(m)
    for polygon in [[[0,0],[1.1,0],[1,1]],[[0,0],[.5,.5],[1,1]]]:
        bad=copy.deepcopy(m);bad['images'][0]['objects'][0]['polygon']=polygon
        with pytest.raises(ValueError):validate(bad)
    p['reviews']['required_region']='ABSENT'
    with pytest.raises(ValueError,match='CONTRADICTS'):validate(m)
def test_editor_is_offline_versioned_and_hash_bound(tmp_path):
    m=manifest(tmp_path);source=tmp_path/'manifest.json';source.write_text(json.dumps(m));target=tmp_path/'editor.html'
    editor(source,target);html=target.read_text(encoding='utf-8')
    assert "connect-src 'none'" in html and 'fetch(' not in html
    assert all(c in html for c in CLASSES)
    with pytest.raises(ValueError,match='OUTPUT_EXISTS'):editor(source,target)
    (tmp_path/'x.jpg').write_bytes(b'changed')
    with pytest.raises(ValueError,match='SOURCE_CHANGED'):editor(source,tmp_path/'other.html')
