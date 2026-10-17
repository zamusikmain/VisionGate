"""Box/label evidence gate, separate from the legacy single-barcode gate.

Unvalidated CV hints are never proof of absence, completeness, or authenticity.
Manual observations and future validated local detectors use the same contract.
"""
import hashlib
import re
from typing import Literal

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .config import load_config
from .decoder import ZXingDecoder

VERSION = 'samsung-evidence-0.1'
PHOTO_CHECKS = ('box_present', 'factory_label_present', 'label_complete',
                'required_information_visible', 'barcode_readable', 'text_readable',
                'no_critical_blur', 'no_critical_glare', 'no_occlusion', 'no_crop')
State = Literal['PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Check(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    state: State = 'UNKNOWN'
    source: Literal['manual_review', 'validated_detector', 'heuristic', 'unavailable', 'policy'] = 'unavailable'
    detail: str = Field(default='', max_length=1000)


class Identifier(StrictModel):
    # Key distinguishes semantic fields: imei_set, serial, model, barcode:product.
    key: str = Field(min_length=1, max_length=100)
    values: list[str] = Field(default_factory=list, max_length=20)
    complete: bool = False
    verified: bool = False
    source: Literal['manual_review', 'local_ocr', 'barcode']
    region: list[int] | None = Field(default=None, min_length=4, max_length=4)


class PhotoEvidence(StrictModel):
    file_id: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    role: Literal['device', 'scan', 'other']
    checks: list[Check] = Field(default_factory=list, max_length=50)
    identifiers: list[Identifier] = Field(default_factory=list, max_length=30)
    decoded_barcodes: list[dict] = Field(default_factory=list, max_length=100)
    label_candidates: list[list[int]] = Field(default_factory=list, max_length=10)
    metrics: dict[str, float] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list, max_length=20)
    ocr: dict = Field(default_factory=lambda: {'status': 'NOT_RUN', 'lines': []})


class CaseEvidence(StrictModel):
    case_id: str = Field(min_length=1, max_length=200)
    photos: list[PhotoEvidence] = Field(default_factory=list, max_length=100)


class Policy(StrictModel):
    # Caller must configure these from an agreed contract, not infer from labels.
    required_fields: list[str] = Field(default_factory=lambda: ['imei_set', 'serial', 'model'])
    required_roles: list[Literal['device', 'scan', 'other']] = Field(default_factory=lambda: ['device', 'scan'])
    contract_confirmed: bool = False
    orientation_required: bool | None = None
    version: str = 'user-addendum-2026-10-16-preliminary-fields'


def valid_imei(value):
    if not re.fullmatch(r'[0-9]{15}', value) or len(set(value)) == 1:
        return False
    digits = list(map(int, value))
    return sum((d*2//10+d*2%10) if i % 2 else d for i, d in enumerate(digits)) % 10 == 0


def _field_values(field):
    values = {s.strip() for s in field.values}
    if not values or '' in values or not field.verified or not field.complete:
        return None
    if field.key == 'imei_set' and not all(valid_imei(v) for v in values):
        return None
    return values


def evaluate_case(case: CaseEvidence, policy: Policy | None = None):
    policy = policy or Policy()
    findings = []
    def add(code, state='UNKNOWN', file_id=None, detail='', authority='user_requirement'):
        findings.append(dict(code=code, state=state, file_id=file_id, detail=detail, authority=authority))
    if not policy.contract_confirmed:
        add('SAMSUNG_CONTRACT_UNCONFIRMED', authority='preliminary')
    for role in set(policy.required_roles):
        if not any(p.role == role for p in case.photos): add('MISSING_ROLE', 'FAIL', detail=role)
    file_ids = [p.file_id for p in case.photos]
    if len(file_ids) != len(set(file_ids)): add('DUPLICATE_FILE_ID', 'FAIL')
    if not case.photos: add('EMPTY_CASE', 'FAIL')
    for photo in case.photos:
        for error in photo.errors: add(error, 'FAIL', photo.file_id)
        grouped = {}
        for check in photo.checks: grouped.setdefault(check.name, []).append(check)
        required = list(PHOTO_CHECKS)
        if policy.orientation_required is True: required.append('orientation_correct')
        elif policy.orientation_required is None:
            add('ORIENTATION_RULE_UNCONFIRMED', file_id=photo.file_id, authority='preliminary')
        # Known FAIL dominates; conflicting observations never silently overwrite it.
        for name in required:
            checks = grouped.get(name, [])
            trusted = [c for c in checks if c.source in {'manual_review', 'validated_detector'}]
            if any(c.state == 'FAIL' for c in trusted):
                add(name.upper(), 'FAIL', photo.file_id)
            elif not trusted or any(c.state != 'PASS' for c in trusted):
                add(name.upper(), file_id=photo.file_id)
            for check in checks:
                if check.source == 'heuristic' and check.state != 'PASS':
                    add(name.upper()+'_HINT', file_id=photo.file_id, detail=check.detail, authority='preliminary')
        # These are separate fields; a decoded QR/IMEI cannot prove a serial is visible.
        for key in policy.required_fields:
            fields = [f for f in photo.identifiers if f.key == key]
            if len(fields) != 1 or _field_values(fields[0]) is None:
                add('FIELD_UNREADABLE_OR_UNVERIFIED', file_id=photo.file_id, detail=key)

    # Compare each semantic field across every provided photo, including other files.
    # Unknown/incomplete extraction never becomes a mismatch or a match.
    keys = set(policy.required_fields) | {f.key for p in case.photos for f in p.identifiers}
    comparisons = []
    for key in sorted(keys):
        values = []
        for photo in case.photos:
            fields = [f for f in photo.identifiers if f.key == key]
            if len(fields) == 1 and (v := _field_values(fields[0])) is not None:
                values.append((photo, v))
        unique = {frozenset(v) for _, v in values}
        if len(unique) > 1:
            # Two full, verified sets must agree, including IMEI1/IMEI2 coverage.
            status = 'MISMATCH'
            add('IDENTIFIER_MISMATCH', 'FAIL', detail=key)
        elif len({p.sha256 for p, _ in values}) >= 2 and len(values) == len(case.photos):
            status = 'MATCH'
        else:
            status = 'UNKNOWN'
            add('CONSISTENCY_UNVERIFIED', detail=key)
        candidates = []
        for photo in case.photos:
            fields = [f for f in photo.identifiers if f.key == key]
            if len(fields) == 1:
                candidate = {s.strip() for s in fields[0].values if s.strip()}
                if key == 'imei_set': candidate = {s for s in candidate if valid_imei(s)}
                if candidate: candidates.append(candidate)
        possible_mismatch = len(candidates) > 1 and any(
            not a.intersection(b) for i, a in enumerate(candidates) for b in candidates[i+1:])
        if possible_mismatch and status == 'UNKNOWN':
            add('POSSIBLE_IDENTIFIER_MISMATCH', detail=key, authority='preliminary')
        comparisons.append({'key': key, 'status': status, 'possible_mismatch': possible_mismatch,
                            'files': [p.file_id for p, _ in values]})
    if len({p.sha256 for p in case.photos}) < len(case.photos):
        add('REUSED_PHOTO', detail='Duplicate bytes are not independent device/scan evidence.')
    failures = [f for f in findings if f['state'] == 'FAIL']
    decision = ('REJECT' if any(f['code'] == 'IDENTIFIER_MISMATCH' for f in failures)
                else 'RETAKE' if failures else 'REVIEW' if findings else 'PASS_SPECIFIED_CHECKS')
    return dict(case_id=case.case_id, decision=decision, findings=findings, comparisons=comparisons,
                photos=[p.model_dump() for p in case.photos], algorithm_version=VERSION,
                policy=policy.model_dump(),
                notice='No Samsung approval or accuracy claim. Heuristics cannot establish label completeness. Manual review must be performed on the bound original SHA-256.')


def label_candidates(image):
    """Unvalidated rectangular light-region candidates, never a box detector."""
    h, w = image.shape[:2]
    scale = min(1., 1600/max(h, w))
    small = cv2.resize(image, (max(1, round(w*scale)), max(1, round(h*scale))))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    mask = cv2.inRange(gray, 160, 255)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        x, y, cw, ch = cv2.boundingRect(contour)
        ratio = cw*ch/gray.size
        if .003 <= ratio <= .6 and .8 <= cw/ch <= 12:
            candidates.append([round(v/scale) for v in (x, y, x+cw, y+ch)])
        if len(candidates) == 10: break
    return candidates


def inspect_photo(image, data: bytes, file_id: str, role='device', decoder=None, use_local_ocr=False):
    """Local measurements only. No OCR/semantic detector is fabricated when absent."""
    checks = [Check(name=name) for name in PHOTO_CHECKS]
    photo = PhotoEvidence(file_id=file_id, sha256=hashlib.sha256(data).hexdigest(), role=role,
                          checks=checks, label_candidates=label_candidates(image))
    if use_local_ocr:
        from .local_ocr import read_local_text, field_candidates
        photo.ocr = read_local_text(image)
        photo.identifiers = field_candidates(photo.ocr)
    found = (decoder or ZXingDecoder()).decode(image)
    for code in found[:100]:
        photo.decoded_barcodes.append({'decoded': code.decoded, 'type': code.type,
                                      'value': code.value, 'bounding_box': code.bounding_box})
    if any(b.decoded for b in found):
        # Deliberately does not turn barcode_readable/text_readable/label_complete into PASS.
        checks[4].detail = 'At least one code decoded; required codes and full label remain unverified.'
    if photo.label_candidates:
        x1, y1, x2, y2 = photo.label_candidates[0]
        gray = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        c = load_config()
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        bright_ratio = float(np.mean(gray >= 250))
        photo.metrics = {'candidate_sharpness': sharpness, 'candidate_bright_pixel_ratio': bright_ratio}
        if sharpness < c.sharpness_critical:
            photo.checks.append(Check(name='no_critical_blur', state='UNKNOWN', source='heuristic',
                                      detail='Low candidate sharpness; label identity/threshold are unvalidated.'))
        if bright_ratio > c.overexposure_max:
            photo.checks.append(Check(name='no_critical_glare', state='UNKNOWN', source='heuristic',
                                      detail='Bright candidate region; white paper is not proof of glare.'))
        h, w = image.shape[:2]
        if x1 <= 1 or y1 <= 1 or x2 >= w-1 or y2 >= h-1:
            photo.checks.append(Check(name='no_crop', state='UNKNOWN', source='heuristic',
                                      detail='Candidate touches image border; verify the whole label.'))
    return photo
