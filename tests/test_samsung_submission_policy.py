"""Synthetic policy fixtures: visual PASS is injected, never inferred from OCR."""
from backend.gate.samsung_auto import classify_case
from backend.gate.samsung_policy import REQUIRED

def photo(role, serial='TEST-SERIAL-A', model='SM-X123A'):
    return dict(role=role,sha256=role,policy_profile='role-v1',extraction={},barcodes=[],
        mandatory_checks=list(REQUIRED[role]),
        checks={k:dict(state='PASS',reason='Synthetic verified criterion') for k in REQUIRED[role]},
        fields=[dict(key=k,value=v,format_valid=True,confirmed=True,mismatch_eligible=True,conflicted=False)
                for k,v in [('serial',serial),('model',model)]])

def test_serial_alternative_does_not_require_an_absent_imei():
    r=classify_case([photo('device'),photo('scan')])
    assert r['final_decision']=='APPROVED'

def test_optional_model_mismatch_is_advisory_not_official_defect():
    r=classify_case([photo('device'),photo('scan',model='SM-X456B')])
    assert r['final_decision']=='APPROVED'
    assert any(f['code']=='MODEL_MISMATCH' for f in r['advisories'])

def test_serial_mismatch_remains_confirmed():
    r=classify_case([photo('device'),photo('scan',serial='TEST-SERIAL-B')])
    assert r['rejection_status']=='REJECTED_CONFIRMED'

def test_serial_match_never_proves_missing_visual_criterion():
    p=photo('device');p['checks']['device_top_visible']['state']='UNKNOWN'
    r=classify_case([p,photo('scan')])
    assert r['rejection_status']=='REJECTED_UNVERIFIED'

def test_uncorroborated_serial_is_not_a_pair_match():
    p=photo('scan');p['fields'][0]['confirmed']=False
    assert classify_case([photo('device'),p])['final_decision']=='REJECTED'
