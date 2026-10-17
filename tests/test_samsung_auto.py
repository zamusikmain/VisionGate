import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from backend.gate.samsung_auto import REQUIRED,analyze_photo,classify_case,parse_fields,summarize_fields
from backend.gate.samsung_vision import rectify,variants,locate_labels
from backend.gate.local_ocr import read_local_variants
from tools.samsung_run import evaluate,swaps


def photo(role,value='490154203237518'):
    return dict(role=role,sha256=hashlib.sha256(role.encode()).hexdigest(),
        label_index=0,extraction={'confirmed_imeis':[value],'confirmed_models':['SM-A000X']},
        checks={k:dict(state='PASS',reason='synthetic verified evidence') for k in REQUIRED},
        fields=[dict(key='imei1',value=value,confirmed=True,format_valid=True,mismatch_eligible=True),
                dict(key='model',value='SM-A000X',confirmed=True,format_valid=True,mismatch_eligible=True)])


def test_not_an_unconditional_rejection_policy():
    result=classify_case([photo('device'),photo('scan')])
    assert result['final_decision']=='APPROVED'
    assert result['diagnostic_state']=='PASS'
    assert result['decisive_coverage']


@pytest.mark.parametrize('criterion',REQUIRED)
def test_every_unknown_mandatory_criterion_blocks_approval(criterion):
    photos=[photo('device'),photo('scan')];photos[0]['checks'][criterion]['state']='UNKNOWN'
    result=classify_case(photos)
    assert result['final_decision']=='REJECTED'
    assert result['rejection_basis']=='insufficient_evidence'
    assert result['diagnostic_state']=='UNKNOWN'
    assert not result['decisive_coverage']


def test_missing_check_not_treated_as_pass():
    photos=[photo('device'),photo('scan')];del photos[0]['checks']['label_complete']
    assert classify_case(photos)['final_decision']=='REJECTED'


def test_barcode_success_cannot_override_multiple_label_defects():
    photos=[photo('device'),photo('scan')]
    for key in ('no_field_glare','no_field_occlusion','no_crop'):photos[0]['checks'][key]['state']='FAIL'
    r=classify_case(photos)
    assert r['final_decision']=='REJECTED'
    assert len([f for f in r['findings'] if f['state']=='FAIL'])==3
    assert r['rejection_basis']=='detected_defect'


def test_slot_confirmed_mismatch_and_partial_unindexed_sets():
    photos=[photo('device'),photo('scan','356938035643809')]
    assert classify_case(photos)['rejection_basis']=='identifier_mismatch'
    for p in photos:p['fields'][0]['key']='imei'
    r=classify_case(photos)
    assert r['diagnostic_state']=='UNKNOWN'
    assert not any(f['category']=='identifier_mismatch' for f in r['findings'])


def test_repeat_only_ocr_model_conflict_not_a_proven_mismatch():
    photos=[photo('device'),photo('scan')]
    photos[0]['fields'][1].update(value='SM-A000I',mismatch_eligible=False)
    photos[1]['fields'][1]['mismatch_eligible']=False
    r=classify_case(photos)
    assert r['rejection_basis']=='insufficient_evidence'
    assert any(f['code']=='POSSIBLE_MODEL_MISMATCH' for f in r['findings'])


def test_model_sku_slots_formats_and_no_digit_correction():
    fields=parse_fields('IMEI1: 490154203237518 IMEI2: 356938035643809 Model SM-A000X/DS SM-A000XZTEST S/N: SYNTHETIC12')
    assert ('model','SM-A000X/DS',True) in fields
    assert ('sku','SM-A000XZTEST',True) in fields
    assert ('imei1','490154203237518',True) in fields
    assert ('imei2','356938035643809',True) in fields
    assert ('serial','SYNTHETIC12',True) in fields
    assert not any(k=='model' for k,v,f in parse_fields('SM-AS76B'))
    assert parse_fields('watermark 490154203237518')==[]
    assert ('imei1','490154203237519',False) in parse_fields('IMEI1: 490154203237519')


def test_confirmation_keeps_sources_and_does_not_fake_independence():
    records=[dict(key='model',value='SM-A000X/DS',format_valid=True,source='windows_local_ocr',variant='gray'),
             dict(key='model',value='SM-A000X',format_valid=True,source='windows_local_ocr',variant='clahe')]
    f=summarize_fields(records)[0]
    assert f['value']=='SM-A000X' and not f['confirmed'] and f['repeat_consistent']
    assert not f['mismatch_eligible']
    assert f['evidence'][0]['value']=='SM-A000X/DS'


def test_rectification_is_bounded_and_preserves_corner_colors():
    image=np.zeros((400,600,3),np.uint8)
    cv2.rectangle(image,(100,100),(500,300),(255,255,255),-1)
    crop,matrix=rectify(image,[[100,100],[500,100],[500,300],[100,300]])
    assert crop.shape[:2]==(200,400)
    assert crop.mean()>250
    huge,_=rectify(image,[[-10000,-10000],[10000,-10000],[10000,10000],[-10000,10000]])
    assert max(huge.shape)<=2400
    assert len(list(variants(crop,(0,1,2,3))))==12


def test_synthetic_label_proposals_and_blank_image():
    blank=np.full((600,900,3),60,np.uint8)
    assert locate_labels(blank)==[]
    cv2.rectangle(blank,(180,230),(720,390),(240,240,240),-1)
    for y in (260,290,320,350):cv2.putText(blank,'MODEL IMEI 123456789',(205,y),cv2.FONT_HERSHEY_SIMPLEX,.7,(15,15,15),2)
    found=locate_labels(blank,[[220,310,600,350]])
    assert any(p['bbox'][0]<220 and p['bbox'][2]>600 for p in found)


def test_batch_ocr_cache_is_pixel_based_and_multi_result(tmp_path,monkeypatch):
    monkeypatch.setenv('SAMSUNG_OCR_TEMP_DIR',str(tmp_path/'temp'))
    calls=[]
    def run(args,**kwargs):
        paths=json.loads(Path(args[-1]).read_text(encoding='utf-8'));calls.append(paths)
        return SimpleNamespace(returncode=0,stdout=json.dumps([{'lines':[{'text':str(i)}]} for i,_ in enumerate(paths)]).encode())
    monkeypatch.setattr('backend.gate.local_ocr.subprocess.run',run)
    images=[np.full((40,80),x,np.uint8) for x in (0,255)]
    r=read_local_variants(images,tmp_path/'cache')
    assert len(r)==2 and r[1]['lines'][0]['text']=='1'
    assert read_local_variants(images,tmp_path/'cache')==r
    assert len(calls)==1 and list((tmp_path/'temp').iterdir())==[]


def test_no_ocr_no_name_or_label_inputs_and_diagnostic_files(tmp_path):
    from tools.demo import clean_image
    image=clean_image();ok,data=cv2.imencode('.png',image);assert ok
    result=analyze_photo(image,data.tobytes(),'device',False,diagnostic_dir=tmp_path)
    assert result['role']=='device'
    assert result['checks']['device_top_visible']['state']=='UNKNOWN'
    assert (tmp_path/(result['sha256']+'.jpg')).exists()
    assert not any(f['key']=='imei' for f in result['fields'])


def test_known_case_metrics_and_scan_permutation_do_not_credit_unknown_rejection():
    a=classify_case([photo('device'),photo('scan')]);a['case_id']='synthetic-A'
    b=classify_case([photo('device','356938035643809'),photo('scan','356938035643809')]);b['case_id']='synthetic-B'
    report=evaluate([a,b],{'synthetic-A':'APPROVED','synthetic-B':'REJECTED'})
    assert report['false_approved']==1 and report['false_rejected']==0
    s=swaps([a,b]);assert s['total']==2 and s['confirmed_mismatches']==2 and s['unsafe_approvals']==0


def test_corrupted_batch_members_not_silently_skipped(tmp_path):
    from tools.samsung_run import run
    archive=tmp_path/'synthetic.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for role in ('device','scan'):z.writestr(f'Approved_490154203237518/{role}_490154203237518.jpg',b'bad-image')
    r=run([archive],tmp_path/'out',ocr=False)
    assert len(r['cases'])==1 and r['cases'][0]['final_decision']=='REJECTED'
    assert len(r['cases'][0]['photos'])==2
