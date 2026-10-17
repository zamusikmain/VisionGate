import numpy as np
from backend.gate.local_ocr import field_candidates, read_local_text


def test_context_ocr_does_not_treat_watermark_or_filename_as_imei():
    ocr = {'lines': [{'text': 'a1c13v32lkmd2 490154203237518'},
                     {'text': 'IMEI1: 490154203237518 IMEI2: 356938035643809'},
                     {'text': 'S/N: SYNTHETIC12 Model SM-A000X'}]}
    fields = {f.key: f for f in field_candidates(ocr)}
    assert set(fields['imei_set'].values) == {'490154203237518', '356938035643809'}
    assert fields['serial'].values == ['SYNTHETIC12']
    assert fields['model'].values == ['SM-A000X']
    assert all(not f.verified and not f.complete for f in fields.values())
    assert field_candidates({'lines': [{'text': 'a1c13v32lkmd2 490154203237518'}]}) == []


def test_ocr_failure_explicit_and_temporary_image_removed(tmp_path, monkeypatch):
    monkeypatch.setenv('SAMSUNG_OCR_TEMP_DIR', str(tmp_path))
    def fail(*a, **kw): raise OSError('no executable')
    monkeypatch.setattr('backend.gate.local_ocr.subprocess.run', fail)
    result = read_local_text(np.zeros((60,100,3), dtype='uint8'))
    assert result['status'] == 'LOCAL_OCR_UNAVAILABLE'
    assert list(tmp_path.iterdir()) == []


def test_ocr_candidates_cannot_produce_automatic_reject():
    from backend.gate.samsung import CaseEvidence, PhotoEvidence, evaluate_case
    import hashlib
    photos=[]
    for role, value in [('device', '490154203237518'), ('scan', '356938035643809')]:
        photos.append(PhotoEvidence(file_id=role, role=role, sha256=hashlib.sha256(role.encode()).hexdigest(),
            identifiers=field_candidates({'lines': [{'text': 'IMEI: '+value}]})))
    result = evaluate_case(CaseEvidence(case_id='synthetic', photos=photos))
    assert result['decision'] == 'REVIEW'
    assert any(f['code'] == 'POSSIBLE_IDENTIFIER_MISMATCH' for f in result['findings'])
