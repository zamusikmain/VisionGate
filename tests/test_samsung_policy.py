import io
import zipfile
import numpy as np
from backend.gate.samsung_policy import apply_role_policy,REQUIRED
from backend.gate.samsung_screen import gallery_evidence
from backend.gate.samsung_reference import final_status_labels
from backend.gate.samsung_auto import classify_case
from backend.gate.samsung_vision import diagnostic


def photo(role):
    return dict(role=role,sha256=role,fields=[],barcodes=[],checks={},problems=[],extraction={})


def test_role_requirements_do_not_demand_box_top_on_scan_or_optional_fields():
    image=np.arange(240*320*3,dtype=np.uint8).reshape(240,320,3)
    device=apply_role_policy(photo('device'),image);scan=apply_role_policy(photo('scan'),image)
    assert 'device_top_visible' in device['mandatory_checks'] and 'device_top_visible' not in scan['checks']
    assert not set(('model_readable','serial_readable','label_complete','box_evidence')) & set(scan['checks'])
    assert classify_case([device,scan])['rejection_status']=='REJECTED_UNVERIFIED'


def test_constant_image_proves_no_information_without_claiming_generic_blur():
    d=apply_role_policy(photo('device'),np.zeros((240,320,3),np.uint8))
    s=apply_role_policy(photo('scan'),np.zeros((240,320,3),np.uint8))
    assert classify_case([d,s])['rejection_status']=='REJECTED_CONFIRMED'


def test_optional_conflict_does_not_change_identity_on_policy_reapplication():
    image=np.arange(240*320*3,dtype=np.uint8).reshape(240,320,3)
    p=photo('scan')
    p['fields']=[dict(key='imei1',format_valid=True,conflicted=False)]
    p['barcodes']=[dict(type='Code 128',checksum_valid=True)]
    p['conflicting_fields']=['sku','model']
    assert apply_role_policy(p,image)['checks']['identifier_readable']['state']=='PASS'
    p['conflicting_fields'].append('imei1')
    assert apply_role_policy(p,image)['checks']['identifier_readable']['state']=='UNKNOWN'


def line(text,x,y,width=100):
    return dict(text=text,words=[dict(x=x,y=y,width=width,height=15,text=text)])


def test_gallery_requires_two_aligned_controls_and_target_not_background_phone():
    symbol=[dict(type='Code 128',checksum_valid=True,bbox=[80,400,500,450])]
    ocr=dict(reads=[dict(lines=[line('+123 456 789',100,40),line('3 photos',110,80)])])
    assert gallery_evidence(ocr,symbol,1000)
    evidence=gallery_evidence(ocr,symbol,1000)
    assert diagnostic(np.zeros((1000,1000,3),np.uint8),[],[dict(code=evidence['code'],bbox=[100.2,40.7,200.8,55.5])]).any()
    assert not gallery_evidence(dict(reads=[dict(lines=[line('3 photos',110,80)])]),symbol,1000)
    assert not gallery_evidence(ocr,[dict(type='Code 128',checksum_valid=True,bbox=[700,400,950,450])],1000)
    assert not gallery_evidence(ocr,[],1000)
    assert not gallery_evidence(dict(reads=[dict(lines=[line('+123 456 789',100,40),line('watermark token',110,80)])]),symbol,1000)


def test_reference_uses_final_status_not_registration(tmp_path):
    p=tmp_path/'reference.xlsx'
    xml='''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
    <row r="1"><c r="B1" t="inlineStr"><is><t>SN/IMEI</t></is></c><c r="D1" t="inlineStr"><is><t>Registration Status</t></is></c><c r="G1" t="inlineStr"><is><t>Final_Status</t></is></c></row>
    <row r="2"><c r="B2" t="inlineStr"><is><t>synthetic-case</t></is></c><c r="D2" t="inlineStr"><is><t>Approved</t></is></c><c r="G2" t="inlineStr"><is><t>Rejected</t></is></c></row>
    </sheetData></worksheet>'''
    with zipfile.ZipFile(p,'w') as z:z.writestr('xl/worksheets/sheet1.xml',xml)
    assert final_status_labels(p)=={'synthetic-case':'REJECTED'}
