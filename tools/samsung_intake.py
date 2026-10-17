"""Offline ZIP manifest. Never extracts files, decrypts DRM, or makes network calls."""
import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from PIL import Image, ImageOps

MAX_ENTRY = 24 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
PATTERN = re.compile(r'(Approved|Rejected)_([0-9]{15})/(device|scan)_([0-9]{15})\.jpg', re.I)


def inspect_archives(paths):
    rows, pairs, seen, errors = [], {}, {}, []
    total = 0
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) > 10000:
                raise ValueError('TOO_MANY_ENTRIES')
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                name = entry.orig_filename
                parts = PurePosixPath(name).parts
                if '\x00' in name or '\\' in name or '..' in parts or name.startswith('/') or ':' in name:
                    raise ValueError('UNSAFE_ARCHIVE_PATH')
                if entry.file_size > MAX_ENTRY:
                    raise ValueError('ENTRY_TOO_LARGE')
                total += entry.file_size
                if total > MAX_TOTAL:
                    raise ValueError('ARCHIVES_TOO_LARGE')
                row = {'archive': Path(path).name, 'path': name}
                if entry.flag_bits & 1:
                    row['status'] = 'ENCRYPTED_STOP'
                    rows.append(row)
                    continue
                with archive.open(entry) as stream:
                    header = stream.read(64)
                    if header.startswith(b'<## NASCA'):
                        row['status'] = 'NASCA_DRM_STOP'
                        rows.append(row)
                        continue
                    data = header + stream.read(MAX_ENTRY + 1 - len(header))
                if len(data) > MAX_ENTRY:
                    raise ValueError('ENTRY_TOO_LARGE')
                digest = hashlib.sha256(data).hexdigest()
                row.update(bytes=len(data), sha256=digest)
                match = PATTERN.fullmatch('/'.join(parts[-2:]))
                if not match:
                    row['status'] = 'UNRECOGNIZED_ENTRY'
                    rows.append(row)
                    continue
                label, case_id, role, file_id = match.groups()
                label, role = label.upper(), role.lower()
                if case_id != file_id:
                    row['status'] = 'CASE_ID_MISMATCH'
                    errors.append(row.copy())
                    rows.append(row)
                    continue
                row.update(case_id=case_id, label=label, role=role)
                try:
                    with Image.open(io.BytesIO(data)) as image:
                        if image.format != 'JPEG' or image.width * image.height > 24_000_000:
                            raise ValueError('UNSUPPORTED_IMAGE')
                        image = ImageOps.exif_transpose(image)
                        image.load()
                        row.update(status='OK', width=image.width, height=image.height)
                except (OSError, ValueError, Image.DecompressionBombError):
                    row['status'] = 'INVALID_IMAGE'
                    errors.append(row.copy())
                pair = pairs.setdefault(case_id, {'case_id': case_id, 'labels': set(), 'roles': {}})
                pair['labels'].add(label)
                pair['roles'].setdefault(role, set()).add(digest)
                seen.setdefault(digest, []).append({'case_id': case_id, 'label': label, 'role': role})
                rows.append(row)
    cases = []
    for case in pairs.values():
        reasons = []
        if set(case['roles']) != {'device', 'scan'}: reasons.append('MISSING_PAIR_MEMBER')
        if len(case['labels']) != 1: reasons.append('CONFLICTING_CASE_LABELS')
        if any(len(v) > 1 for v in case['roles'].values()): reasons.append('CONFLICTING_ROLE_CONTENT')
        cases.append({'case_id': case['case_id'], 'labels': sorted(case['labels']),
                      'roles': {k: sorted(v) for k, v in case['roles'].items()}, 'issues': reasons})
    duplicates = [{'sha256': k, 'occurrences': v} for k, v in seen.items() if len(v) > 1]
    for d in duplicates:
        if len({x['label'] for x in d['occurrences']}) > 1:
            errors.append({'status': 'CONFLICTING_DUPLICATE_LABELS', 'sha256': d['sha256']})
    return {'files': rows, 'cases': cases, 'duplicates': duplicates, 'errors': errors,
            'ready_for_pair_baseline': bool(cases) and not errors and not any(c['issues'] for c in cases),
            'notice': 'Folder labels are case outcomes, not per-image quality or verified rejection reasons. DRM documents remain unread. No accuracy estimate.'}


def compare_identifiers(device_values, scan_values):
    """Compare only independently extracted, validated IMEIs, never filenames/watermarks.

    Equal sets show consistency only; they never establish photo authenticity.
    """
    def valid(value):
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]{15}', value): return False
        if len(set(value)) == 1: return False
        digits = list(map(int, value))
        return sum((d * 2 // 10 + d * 2 % 10) if i % 2 else d for i, d in enumerate(digits)) % 10 == 0
    a, b = set(device_values), set(scan_values)
    if not a or not b or not all(valid(x) for x in a | b):
        return {'status': 'REVIEW', 'reason': 'IDENTIFIER_UNREADABLE_OR_INVALID'}
    if a == b:
        return {'status': 'MATCH', 'reason': 'IDENTIFIER_SETS_EQUAL'}
    if a & b:
        return {'status': 'REVIEW', 'reason': 'PARTIAL_IDENTIFIER_OVERLAP'}
    return {'status': 'MISMATCH', 'reason': 'IDENTIFIER_SETS_DISJOINT'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archives', nargs='*', type=Path)
    parser.add_argument('--archive-dir',type=Path,help='Default: SAMSUNG_ARCHIVE_DIR or project data/Samsung/original')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    from backend.gate.samsung_paths import input_archives
    if args.archives and args.archive_dir:parser.error('Choose archives or --archive-dir')
    args.archives=args.archives or input_archives(args.archive_dir)
    if args.output.resolve() in {p.resolve() for p in args.archives}:
        parser.error('Output must not overwrite an input archive')
    result = inspect_archives(args.archives)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'cases': len(result['cases']), 'duplicate_groups': len(result['duplicates']),
                      'ready_for_pair_baseline': result['ready_for_pair_baseline']}))
    if not result['ready_for_pair_baseline']: raise SystemExit(2)


if __name__ == '__main__': main()
