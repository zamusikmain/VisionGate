import hashlib
import numpy as np
import pytest
from pydantic import ValidationError

from backend.gate.models import Barcode
from backend.gate.samsung import (PHOTO_CHECKS, CaseEvidence, Check, Identifier,
                                 PhotoEvidence, Policy, evaluate_case, inspect_photo)


def photo(role='device', content=b'one'):
    return PhotoEvidence(file_id=role, role=role, sha256=hashlib.sha256(content).hexdigest(),
        checks=[Check(name=k, state='PASS', source='manual_review') for k in PHOTO_CHECKS],
        identifiers=[Identifier(key='imei_set', values=['490154203237518'], complete=True, verified=True, source='manual_review'),
                     Identifier(key='serial', values=['SYNTHETIC-SN'], complete=True, verified=True, source='manual_review'),
                     Identifier(key='model', values=['SYNTHETIC-MODEL'], complete=True, verified=True, source='manual_review')])


def case(): return CaseEvidence(case_id='synthetic-case', photos=[photo(), photo('scan', b'two')])


def policy(): return Policy(contract_confirmed=True, orientation_required=False)


def test_only_complete_reviewed_evidence_passes_specified_contract():
    assert evaluate_case(case(), policy())['decision'] == 'PASS_SPECIFIED_CHECKS'
    assert evaluate_case(case())['decision'] == 'REVIEW'


@pytest.mark.parametrize('checks', [
    ['no_occlusion'], ['no_crop'], ['label_complete'], ['required_information_visible'],
    ['no_critical_glare', 'no_crop', 'no_occlusion'], ['box_present', 'factory_label_present']])
def test_decoded_barcode_cannot_override_label_failures(checks):
    c = case()
    c.photos[0].decoded_barcodes = [{'decoded': True, 'value': 'SYNTHETIC'}]
    for check in c.photos[0].checks:
        if check.name in checks: check.state = 'FAIL'
    result = evaluate_case(c, policy())
    assert result['decision'] == 'RETAKE'
    assert set(checks) <= {f['code'].lower() for f in result['findings'] if f['state'] == 'FAIL'}


@pytest.mark.parametrize('key,value', [('imei_set', '356938035643809'), ('serial', 'OTHER-SN'), ('model', 'OTHER-MODEL')])
def test_cross_file_verified_identifier_mismatch(key, value):
    c = case()
    next(f for f in c.photos[1].identifiers if f.key == key).values = [value]
    r = evaluate_case(c, policy())
    assert r['decision'] == 'REJECT'
    assert any(f['code'] == 'IDENTIFIER_MISMATCH' and f['detail'] == key for f in r['findings'])


def test_multiple_mismatches_and_photo_defects_are_all_returned():
    c = case()
    c.photos[0].checks.append(Check(name='no_occlusion', state='FAIL', source='manual_review'))
    for field in c.photos[1].identifiers:
        if field.key != 'imei_set': field.values = ['DIFFERENT']
    r = evaluate_case(c, policy())
    assert r['decision'] == 'REJECT'
    assert sum(f['code'] == 'IDENTIFIER_MISMATCH' for f in r['findings']) == 2
    assert any(f['code'] == 'NO_OCCLUSION' for f in r['findings'])


def test_incomplete_imei_set_is_not_false_mismatch():
    c = case()
    c.photos[0].identifiers[0].values += ['356938035643809']
    c.photos[1].identifiers[0].complete = False
    r = evaluate_case(c, policy())
    assert r['decision'] == 'REVIEW'
    assert next(x for x in r['comparisons'] if x['key'] == 'imei_set')['status'] == 'UNKNOWN'


def test_complete_imei_sets_compare_without_order():
    c = case()
    c.photos[0].identifiers[0].values = ['490154203237518', '356938035643809']
    c.photos[1].identifiers[0].values = list(reversed(c.photos[0].identifiers[0].values))
    assert evaluate_case(c, policy())['decision'] == 'PASS_SPECIFIED_CHECKS'


@pytest.mark.parametrize('values', [[], ['bad-imei'], ['000000000000000'], ['490154203237519']])
def test_invalid_imei_always_requires_review(values):
    c = case(); c.photos[0].identifiers[0].values = values
    assert evaluate_case(c, policy())['decision'] == 'REVIEW'


def test_unverified_ocr_and_heuristic_pass_are_not_trusted():
    c = case()
    c.photos[0].identifiers[1].verified = False
    c.photos[0].checks[0].source = 'heuristic'
    r = evaluate_case(c, policy())
    assert r['decision'] == 'REVIEW'
    assert any(f['code'] == 'BOX_PRESENT' for f in r['findings'])


def test_missing_role_duplicate_photo_and_other_file_are_checked():
    c = case(); c.photos.pop()
    assert evaluate_case(c, policy())['decision'] == 'RETAKE'
    c = case(); c.photos[1].sha256 = c.photos[0].sha256
    assert evaluate_case(c, policy())['decision'] == 'REVIEW'
    c = case(); other = photo('other', b'three'); other.identifiers[1].values = ['OTHER-SN']
    c.photos.append(other)
    assert evaluate_case(c, policy())['decision'] == 'REJECT'


def test_orientation_only_enforced_when_explicitly_required():
    c = case()
    c.photos[0].checks.append(Check(name='orientation_correct', state='FAIL', source='manual_review'))
    assert evaluate_case(c, policy())['decision'] == 'PASS_SPECIFIED_CHECKS'
    assert evaluate_case(c, Policy(contract_confirmed=True, orientation_required=True))['decision'] == 'RETAKE'


def test_all_barcodes_retained_and_no_fabricated_semantic_checks():
    class Decoder:
        def decode(self, image):
            return [Barcode(decoded=True, value=v, type='Code128') for v in ['SYNTHETIC-A', 'SYNTHETIC-B']]
    image = np.full((100,200,3), 255, np.uint8)
    p = inspect_photo(image, b'synthetic', 'synthetic', decoder=Decoder())
    assert len(p.decoded_barcodes) == 2
    assert not p.identifiers
    assert all(c.state == 'UNKNOWN' for c in p.checks)
    assert evaluate_case(CaseEvidence(case_id='new', photos=[p]))['decision'] != 'PASS_SPECIFIED_CHECKS'


def test_barcode_semantic_slots_not_confused():
    c = case()
    for p, value in zip(c.photos, ['ABC', 'XYZ']):
        p.identifiers.append(Identifier(key='barcode:product:Code128', values=[value], complete=True, verified=True, source='manual_review'))
    r = evaluate_case(c, policy())
    assert r['decision'] == 'REJECT'
    assert any(f['detail'] == 'barcode:product:Code128' for f in r['findings'])


def test_schema_rejects_unknown_fields_and_invalid_hash():
    with pytest.raises(ValidationError): PhotoEvidence(file_id='x', role='scan', sha256='bad', approved=True)


def test_source_case_names_never_change_decision():
    c = case(); expected = evaluate_case(c, policy())['decision']
    c.case_id = 'Rejected_arbitrary'
    for i, p in enumerate(c.photos): p.file_id = f'Approved_cases/arbitrary-{i}.jpg'
    assert evaluate_case(c, policy())['decision'] == expected


def test_photo_worker_releases_capacity_after_invalid_image(monkeypatch):
    from backend import main
    from backend.gate.image_input import InvalidImage
    class Permit:
        released = False
        def acquire(self, blocking): return True
        def release(self): self.released = True
    permit = Permit(); monkeypatch.setattr(main, 'analysis_slots', permit)
    with pytest.raises(InvalidImage): main.process_samsung_photo(b'broken', 'image/jpeg', 'test')
    assert permit.released


def test_photo_worker_busy_and_valid_upload(monkeypatch):
    from backend import main
    from fastapi import HTTPException
    from tools.demo import clean_image
    import cv2
    class Busy:
        def acquire(self, blocking): return False
    original = main.analysis_slots
    monkeypatch.setattr(main, 'analysis_slots', Busy())
    with pytest.raises(HTTPException) as exc: main.process_samsung_photo(b'x', None, 'test')
    assert exc.value.status_code == 503
    monkeypatch.setattr(main, 'analysis_slots', original)
    ok, buf = cv2.imencode('.png', clean_image()); assert ok
    result = main.process_samsung_photo(buf.tobytes(), 'image/png', 'synthetic')
    assert result.file_id == 'synthetic'
    assert not any(c.state == 'PASS' for c in result.checks)
