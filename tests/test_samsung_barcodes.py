"""Pixel-level identity tests; truth is used only for assertions, never decoding."""
import cv2
import numpy as np
import pytest
import zxingcpp

from backend.gate.samsung_barcodes import enhanced_barcodes
from backend.gate.samsung_auto import classify_case, summarize_fields, REQUIRED


def rendered(values, turns=0):
    image=np.full((600,1100,3),255,np.uint8)
    for index,value in enumerate(values):
        code=np.asarray(zxingcpp.write_barcode(zxingcpp.BarcodeFormat.Code128,value,width=900,height=130))
        code=cv2.resize(code,(code.shape[1],130),interpolation=cv2.INTER_NEAREST)
        y=70+index*250
        image[y:y+code.shape[0],50:50+code.shape[1]]=cv2.cvtColor(code,cv2.COLOR_GRAY2BGR)
        cv2.putText(image,'IMEI'+str(index+1)+': '+value,(60,y+180),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,0,0),2)
    return np.ascontiguousarray(np.rot90(image,turns))


@pytest.mark.parametrize('turns',[0,1,2,3])
def test_independent_different_identity_sets_from_pixels(turns):
    a=('490154203237518','356938035643809')
    b=('490154203237526','356938035643817')
    photos=[]
    for role,truth in [('device',a),('scan',b)]:
        reads=enhanced_barcodes(rendered(truth,turns))
        assert {r['value'] for r in reads}==set(truth)
        assert all(r['checksum_valid'] and r['imei_luhn_valid'] and r['polygon'] for r in reads)
        fields=summarize_fields([dict(key='imei',value=r['value'],format_valid=True,
                                     source='barcode',variant=r['variant'],bbox=r['bbox']) for r in reads])
        photos.append(dict(role=role,sha256=role,fields=fields,checks={k:dict(state='UNKNOWN',reason='not measured by identity test') for k in REQUIRED}))
    result=classify_case(photos)
    assert result['rejection_status']=='REJECTED_CONFIRMED'
    assert any(f['code']=='IMEI_MISMATCH' for f in result['findings'])
    assert result['review_required']  # Identity comparison does not measure photo quality.


def test_missing_evidence_not_confirmed_defect():
    result=classify_case([dict(role=r,sha256=r,fields=[],checks={}) for r in ('device','scan')])
    assert result['rejection_status']=='REJECTED_UNVERIFIED'
    assert not result['confirmed_decision']


def test_unestablished_model_and_serial_not_mandatory():
    photos=[]
    for role in ('device','scan'):
        checks={k:dict(state='PASS',reason='independently verified synthetic contract') for k in REQUIRED}
        checks.update({k:dict(state='UNKNOWN',reason='schema not established') for k in ('model_readable','serial_readable')})
        photos.append(dict(role=role,sha256=role,checks=checks,fields=[dict(key='imei1',value='490154203237518',confirmed=True,format_valid=True,mismatch_eligible=True)]))
    result=classify_case(photos)
    assert result['final_decision']=='APPROVED'
    assert len(result['advisories'])==4
