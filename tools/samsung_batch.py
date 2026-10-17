"""Private offline box-label batch. No tuning, external services or DRM decryption."""
import argparse
import json
import zipfile
from pathlib import Path

from backend.gate.image_input import read_image, InvalidImage
from backend.gate.samsung import CaseEvidence, PhotoEvidence, Policy, evaluate_case, inspect_photo
from tools.samsung_intake import inspect_archives, MAX_ENTRY
from backend.gate.samsung_paths import input_archives


def run_batch(paths, policy=None, use_local_ocr=False):
    paths = [Path(p) for p in paths]
    # Basename collisions would make archive provenance ambiguous.
    if len({p.name for p in paths}) != len(paths): raise ValueError('DUPLICATE_ARCHIVE_NAME')
    intake = inspect_archives(paths)
    source = {p.name: p for p in paths}
    grouped, seen, failures = {}, set(), []
    for row in intake['files']:
        if row['status'] != 'OK':
            failures.append(row)
            if 'case_id' in row:
                grouped.setdefault(row['case_id'], []).append(PhotoEvidence(
                    file_id=row['path'], role=row['role'], sha256=row['sha256'], errors=[row['status']]))
            continue
        key = (row['case_id'], row['role'], row['sha256'])
        if key in seen: continue
        seen.add(key)
        with zipfile.ZipFile(source[row['archive']]) as z:
            with z.open(row['path']) as stream:
                data = stream.read(MAX_ENTRY+1)
        import hashlib
        if len(data) > MAX_ENTRY or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('SOURCE_CHANGED_AFTER_INTAKE')
        try:
            photo = inspect_photo(read_image(data), data, row['path'], row['role'], use_local_ocr=use_local_ocr)
        except InvalidImage as exc:
            photo = PhotoEvidence(file_id=row['path'], role=row['role'], sha256=row['sha256'], errors=[str(exc)])
        grouped.setdefault(row['case_id'], []).append(photo)
    cases = []
    for cid, photos in sorted(grouped.items()):
        result = evaluate_case(CaseEvidence(case_id=cid, photos=photos), policy)
        structural = next((c['issues'] for c in intake['cases'] if c['case_id'] == cid), [])
        if structural:
            result['findings'].extend(dict(code=x, state='FAIL', file_id=None, detail='', authority='intake') for x in structural)
            result['decision'] = 'REVIEW'
        cases.append(result)
    return {'intake': intake, 'cases': cases, 'unprocessed_entries': failures,
            'notice': 'All local. Folder labels are reported only in intake, never passed to the decision engine. This is a preliminary evidence report, not Samsung exam accuracy.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    inputs = p.add_mutually_exclusive_group()
    inputs.add_argument('--archives', nargs='+', type=Path)
    inputs.add_argument('--evidence', type=Path, help='One CaseEvidence JSON, reviewed on the exact original hashes')
    inputs.add_argument('--archive-dir',type=Path,help='Default: SAMSUNG_ARCHIVE_DIR or project data/Samsung/original')
    p.add_argument('--policy', type=Path)
    p.add_argument('--windows-ocr', action='store_true', help='Use only the installed local Windows OCR engine')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    archives=[] if args.evidence else args.archives or input_archives(args.archive_dir)
    sources = ([args.evidence] if args.evidence else archives) + ([args.policy] if args.policy else [])
    if args.output.resolve() in {x.resolve() for x in sources}: p.error('Output must not overwrite an input')
    policy = Policy.model_validate_json(args.policy.read_text(encoding='utf-8')) if args.policy else Policy()
    if args.evidence:
        report = evaluate_case(CaseEvidence.model_validate_json(args.evidence.read_text(encoding='utf-8')), policy)
    else:
        report = run_batch(archives, policy, args.windows_ocr)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    cases = report.get('cases', [report])
    print(json.dumps({'cases': len(cases), 'decisions': {s: sum(c['decision'] == s for c in cases)
                          for s in ('REVIEW', 'RETAKE', 'REJECT', 'PASS_SPECIFIED_CHECKS')}}))


if __name__ == '__main__': main()
