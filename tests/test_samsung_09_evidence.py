from backend.gate.samsung_auto import summarize_fields,classify_case
from backend.gate.samsung_policy import apply_role_policy
import numpy as np
A='490154203237518'
B='356938035643809'
def records(values,decoded):
 return [dict(key='imei1',value=v,format_valid=ok,source='ocr',variant='original') for v,ok in values]+[dict(key='imei',value=v,format_valid=True,source='barcode',variant='native') for v in decoded]
def photo(role,values,decoded):
 return apply_role_policy(dict(role=role,sha256=role,fields=summarize_fields(records(values,decoded)),barcodes=[dict(value=v,type='Code 128',checksum_valid=True) for v in decoded],checks={},problems=[],extraction={}),np.arange(300,dtype=np.uint8).reshape(10,10,3))
def test_invalid_ocr_is_retained_but_cannot_contradict_exact_valid_decode():
 p=photo('scan',[(A,True),(A[:-1]+'9',False)],[A])
 assert len(p['fields'])==3
 assert p['checks']['identifier_readable']['state']=='PASS'
 r=classify_case([photo('device',[(A,True)],[A]),p])
 assert r['evidence_decision']=='REVIEW' and r['final_decision']=='REJECTED'
 assert 'imei1' in r['photos'][1]['raw_conflicting_fields']
 assert 'imei1' not in r['photos'][1]['conflicting_fields']
 assert any(x['code']=='INVALID_IMEI1_OCR_ALTERNATIVES' for x in r['advisories'])
def test_valid_alternative_still_blocks_even_without_its_barcode():
 p=photo('scan',[(A,True),(B,True)],[A])
 assert p['checks']['identifier_readable']['state']=='UNKNOWN'
 assert all(not f['confirmed'] for f in p['fields'] if f['key']=='imei1')
def test_invalid_alternative_without_corroboration_remains_unresolved():
 p=photo('scan',[(A,True),(A[:-1]+'9',False)],[])
 assert p['checks']['identifier_readable']['state']=='UNKNOWN'
def test_swapped_valid_values_remain_confirmed_defect():
 r=classify_case([photo('device',[(A,True),(A[:-1]+'9',False)],[A]),photo('scan',[(B,True)],[B])])
 assert r['evidence_decision']=='REJECTED' and r['rejection_status']=='REJECTED_CONFIRMED'
def test_no_repair_from_bad_digits_or_repeated_variants():
 fields=summarize_fields(records([(A[:-1]+'9',False)],[])*4)
 assert not any(f['confirmed'] for f in fields)
 assert {f['value'] for f in fields}=={A[:-1]+'9'}
def test_unconfirmed_legacy_failure_is_review_not_decisive_coverage():
 p=dict(role='device',sha256='a',fields=[],checks={'physical_object':dict(state='FAIL',reason='heuristic')},mandatory_checks=['physical_object'],extraction={})
 s=dict(p,role='scan',sha256='b')
 r=classify_case([p,s])
 assert r['evidence_decision']=='REVIEW' and not r['decisive_coverage']
