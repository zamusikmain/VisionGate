import copy
import hashlib
import json
import zipfile
import xml.etree.ElementTree as E
import numpy as np
import pytest
from tools.samsung_prepare_examples import official_rows,docx_photos,propose_regions,learning_rows
from tools.samsung_region_annotations import initialize,validate,editor


def workbook(path,final='Rejected',device='Photo without serial number',scan='blurry/dark/unreadable'):
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    root=E.Element('worksheet',xmlns=ns);body=E.SubElement(root,'sheetData')
    for i,values in enumerate([
        ['No','SN/IMEI','Date','Registration Status','Description','Scan (not a photo)','Final_Status'],
        ['1','EXAMPLE-PRIVATE-ID','date','Approved',device,scan,final]],1):
        row=E.SubElement(body,'row',r=str(i))
        for j,text in enumerate(values):
            c=E.SubElement(row,'c',r=f'{chr(65+j)}{i}',t='inlineStr');E.SubElement(E.SubElement(c,'is'),'t').text=text
    with zipfile.ZipFile(path,'w') as z:z.writestr('xl/worksheets/sheet1.xml',E.tostring(root))


def test_final_status_and_role_reasons_override_registration(tmp_path):
    p=tmp_path/'x.xlsx';workbook(p);rows=official_rows(p);r=rows['EXAMPLE-PRIVATE-ID']
    assert r['category']=='REJECTED' and r['registration_conflict']
    assert r['reason_codes']=={'device':'IDENTIFICATION_MISSING','scan':'INFORMATION_QUALITY'}
    assert r['cells']=={'status':'G2','device':'E2','scan':'F2'}
    workbook(p,final='Approved')
    with pytest.raises(ValueError,match='FINAL_REASON_CONFLICT'):official_rows(p)


def test_docx_uses_drawing_relationship_order_and_raw_bytes(tmp_path):
    p=tmp_path/'x.docx'
    with zipfile.ZipFile(p,'w') as z:
        z.writestr('word/document.xml','<w:document xmlns:w="w" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><a:blip r:embed="second"/><a:blip r:embed="first"/></w:document>')
        z.writestr('word/_rels/document.xml.rels','<Relationships><Relationship Id="first" Target="media/a.jpg"/><Relationship Id="second" Target="media/b.jpg"/></Relationships>')
        z.writestr('word/media/a.jpg',b'scan');z.writestr('word/media/b.jpg',b'device')
    r=docx_photos(p,'REJECTED')
    assert r[hashlib.sha256(b'device').hexdigest()]['role']=='device'
    assert r[hashlib.sha256(b'scan').hexdigest()]['example']==2


def test_proposals_do_not_use_official_answers_ids_or_identifier_values(monkeypatch):
    image=np.full((100,200,3),180,np.uint8)
    r=dict(proposals=[dict(polygon=[[20,20],[180,20],[180,80],[20,80]],method='test',score=2)],
           box_candidates=[],pretrained_ocr=dict(lines=[]),barcodes=[dict(polygon=[[40,40],[100,40],[100,50],[40,50]],
           coordinate_space='original',checksum_valid=True,value='SYNTHETIC-A',variant='original')])
    monkeypatch.setattr('tools.samsung_prepare_examples.box_geometry_candidates',lambda *a:[])
    a=propose_regions(image,r);other=copy.deepcopy(r)
    other.update(case_id='UNRELATED',official={'category':'APPROVED','reason':'OK'},watermark='not-a-feature')
    other['barcodes'][0]['value']='OTHER-IDENTIFIER'
    assert propose_regions(image,other)==a
    assert all(not o['reviewed'] and not o['semantic_verified'] for o in a)
    assert 'SYNTHETIC-A' not in json.dumps(a)


def annotation():
    d=initialize(dict(images=[dict(photo_id='P1',sha256='a'*64,image='private.jpg',width=100,height=100,case_group='GROUP',role='device',objects=[])]))
    p=d['images'][0];p['official']=dict(category='APPROVED',case_id='PRIVATE-ID',case_alias='S01',role='device',
                                     reason='OK',reason_code='OK',category_source='Final_Status')
    p['objects']=[dict(**{'class':'required_region'},polygon=[[.1,.1],[.9,.1],[.9,.9],[.1,.9]],reviewed=True)]
    p['reviews']['required_region']='PRESENT'
    return d


def test_training_targets_keep_negative_criteria_specific_and_exclude_unverified():
    d=annotation();r=learning_rows(d);assert r['rows'][0]['target']=='positive_region' and not r['trained_model']
    assert 'PRIVATE-ID' not in json.dumps(r) and 'APPROVED' not in json.dumps(r)
    p=d['images'][0];p['official'].update(category='REJECTED',reason='Cutted photo',reason_code='CRITICAL_CROP')
    assert not learning_rows(d)['rows']  # A label region on Rejected is not a good capture example.
    p['objects'][0]['class']='crop';p['reviews']['required_region']='UNKNOWN';p['reviews']['crop']='PRESENT'
    assert learning_rows(d)['rows'][0]['criterion']=='CRITICAL_CROP'
    p['objects'][0]['reviewed']=False;p['reviews']['crop']='UNKNOWN';assert not learning_rows(d)['rows']


def test_quality_reason_cannot_be_invented_as_a_specific_blur_label():
    d=annotation();p=d['images'][0];p['official'].update(category='REJECTED',reason='blurry/dark/unreadable',reason_code='INFORMATION_QUALITY')
    assert not learning_rows(d)['rows']
    p['objects'][0].update(defect_kind='INFORMATION_QUALITY',official_quality_region=True)
    assert learning_rows(d)['rows'][0]['criterion']=='INFORMATION_QUALITY'
    assert learning_rows(d)['rows'][0]['region_class']=='required_region'


def test_official_role_and_category_provenance_are_checked():
    d=annotation();d['images'][0]['official']['category_source']='Registration Status'
    with pytest.raises(ValueError,match='INVALID_OFFICIAL_CATEGORY'):validate(d)
    d=annotation();d['images'][0]['role']='scan'
    with pytest.raises(ValueError,match='INVALID_OFFICIAL_CONTEXT'):validate(d)


def test_editor_preserves_official_context_and_escapes_script_text(tmp_path):
    d=annotation();raw=b'fake-jpg';p=d['images'][0];source=tmp_path/'image.jpg';source.write_bytes(raw)
    p.update(image=str(source),sha256=hashlib.sha256(raw).hexdigest());p['official']['reason']='</script><script>bad()</script>'
    target=tmp_path/'data.json';target.write_text(json.dumps(d));output=tmp_path/'editor.html';editor(target,output)
    html=output.read_text(encoding='utf-8')
    assert '</script><script>bad()' not in html
    embedded=html.split('let data=',1)[1].split(',index=0',1)[0]
    assert json.loads(embedded)['images'][0]['official']['reason']==p['official']['reason']
