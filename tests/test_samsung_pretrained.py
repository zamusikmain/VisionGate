import hashlib
import numpy as np

from backend.gate.pretrained_ocr import ctc_decode
from backend.gate.samsung_pretrained import extract_records
from backend.gate.samsung_auto import summarize_fields,classify_case,REQUIRED
from tools.samsung_run import fingerprint


def read(text):
    return dict(lines=[dict(text=text,score=.99,detection_score=.95,polygon=[[0,0],[400,0],[400,30],[0,30]])])


def test_ctc_duplicate_blank_and_score():
    pred=np.eye(4,dtype=np.float32)[[1,1,0,1,2,2,0,3]]
    assert ctc_decode(pred,['blank','A','B','C'])==('AABC',1.)


def test_field_marker_normalization_never_repairs_identifier_digits():
    records=extract_records(read('IME11: 490154203237518'))
    assert records[0]['key']=='imei1' and records[0]['value']=='490154203237518'
    assert records[0]['field_label_normalized'] and records[0]['raw_text']=='IME11: 490154203237518'
    wrong=extract_records(read('IME11: 490154203237519'))[0]
    assert wrong['value']=='490154203237519' and not wrong['format_valid']
    assert extract_records(read('token 490154203237518'))==[]
    assert extract_records(read('IMEI1: 49O154203237518'))==[]


def test_ocr_score_alone_does_not_prove_identity_or_photo_quality():
    fields=summarize_fields(extract_records(read('IMEI1: 490154203237518')))
    assert not fields[0]['confirmed'] and not fields[0]['mismatch_eligible']
    result=classify_case([dict(role=r,sha256=r,fields=fields,checks={}) for r in ('device','scan')])
    assert result['final_decision']=='REJECTED' and result['rejection_status']=='REJECTED_UNVERIFIED'


def test_model_ocr_plus_independent_barcode_can_compare_same_slot():
    photos=[]
    for role,value in [('device','490154203237518'),('scan','356938035643809')]:
        records=extract_records(read('IMEI1: '+value))
        records.append(dict(key='imei',value=value,format_valid=True,source='barcode',variant='native'))
        photos.append(dict(role=role,sha256=role,checks={k:dict(state='UNKNOWN',reason='not measured') for k in REQUIRED},fields=summarize_fields(records)))
    assert classify_case(photos)['rejection_status']=='REJECTED_CONFIRMED'


def test_profile_cache_separation(monkeypatch):
    monkeypatch.setenv('SAMSUNG_OCR_ENGINE','legacy');a=fingerprint()
    monkeypatch.setenv('SAMSUNG_OCR_ENGINE','ppocrv5');b=fingerprint()
    monkeypatch.setenv('SAMSUNG_OCR_DETECTOR','server');c=fingerprint()
    assert len({a,b,c})==3
