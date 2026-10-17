"""All-candidate proof never chooses a convenient conflicting IMEI."""
from backend.gate.samsung_auto import indexed_candidate_mismatches,summarize_fields

A='490154203237518'
B='356938035643809'
C='352099001761481'

def photo(role,values,decoded):
    return dict(role=role,sha256=role,fields=[dict(key='imei1',value=v,format_valid=True,confirmed=False,conflicted=True) for v in values],
                barcodes=[dict(type='Code 128',value=v,checksum_valid=True) for v in decoded])

def test_disjoint_corroborated_sets_prove_mismatch_without_selecting_fields():
    d=photo('device',[A],[A]);s=photo('scan',[B],[B]);d['fields'].append(dict(key='imei1',value=A[:-1]+'9',format_valid=False,confirmed=False,conflicted=True))
    findings,comparisons=indexed_candidate_mismatches([d,s])
    assert any(f['category']=='identifier_mismatch' for f in findings)
    assert all(c['selected_value'] is None for c in comparisons)
    assert len(d['fields'])==2 and all(not f['confirmed'] for f in d['fields'])

def test_an_uncorroborated_valid_alternative_blocks_universal_proof():
    from backend.gate.samsung import valid_imei
    assert valid_imei(C)
    assert not indexed_candidate_mismatches([photo('device',[A,C],[A]),photo('scan',[B],[B])])[0]

def test_overlapping_sets_and_single_unindexed_sim_subsets_do_not_reject():
    assert not indexed_candidate_mismatches([photo('device',[A,B],[A,B]),photo('scan',[B],[B])])[0]
    d=photo('device',[A],[A]);s=photo('scan',[B],[B])
    for p in (d,s):p['fields'][0]['key']='imei'
    assert not indexed_candidate_mismatches([d,s])[0]
    for p in (d,s):p['fields'][0]['key']='imei1'
    s['sha256']=d['sha256']
    assert not indexed_candidate_mismatches([d,s])[0]

def test_two_valid_conflicts_remain_conflicts_even_if_both_are_decoded():
    fields=summarize_fields([dict(key=k,value=v,source=source,variant='native',format_valid=True)
        for k,v,source in [('imei1',A,'ocr'),('imei1',B,'ocr'),('imei',A,'barcode'),('imei',B,'barcode')]])
    assert all(f['conflicted'] and not f['confirmed'] for f in fields if f['key']=='imei1')

def test_shared_decoded_identity_prevents_slot_swap_becoming_new_proof():
    # A photographed dual-SIM code pair can be bound to a wrong slot by OCR.
    # Shared decoded identity requires further review rather than this new rule.
    assert not indexed_candidate_mismatches([photo('device',[A],[A,B]),photo('scan',[B],[A,B])])[0]
