"""Local observational experiment: generic preprocessing, never watermark removal.

Ground truth is read only in evaluate(), after inference. Geometry variants use
explicit manual visible-plane annotations and are NOT automatic detections.
All identifiers/results stay in the ignored reports directory. No networking.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import zipfile

import cv2
import numpy as np
import zxingcpp

from backend.gate.image_input import read_image
from backend.gate.pretrained_ocr import PaddleONNX
from backend.gate.samsung_pretrained import extract_records

VERSION = 'watermark-observation-1'
FIELDS = ('imei1', 'imei2', 'serial', 'model', 'sku')
FULL = ('original', 'scale2', 'clahe', 'illumination')
ROI = ('manual_crop', 'manual_perspective', 'manual_perspective_clahe')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def contrast(image):
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=2., tileGridSize=(8, 8)).apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def illumination(image):
    # Generic low-frequency illumination estimate, independent of text/color.
    # No watermark masks, stroke suppression, inpainting or hidden-pixel filling.
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    light = lab[:, :, 0].astype(np.float32)
    h, w = light.shape
    small = cv2.resize(light, (max(8, round(w * 256 / max(h, w))),
                               max(8, round(h * 256 / max(h, w)))))
    background = cv2.resize(cv2.GaussianBlur(small, (0, 0), 8), (w, h))
    lab[:, :, 0] = np.uint8(np.clip(light * np.median(background) / np.maximum(background, 16), 0, 255))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def variants(image, quad):
    yield 'original', image
    h, w = image.shape[:2]
    scale = min(2., 6000 / max(h, w))
    yield 'scale2', cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    yield 'clahe', contrast(image)
    yield 'illumination', illumination(image)
    if quad is None:
        return
    q = np.float32(quad) * np.float32([w, h])
    x, y, bw, bh = cv2.boundingRect(q)
    crop = np.ascontiguousarray(image[max(0, y):min(h, y + bh), max(0, x):min(w, x + bw)])
    yield 'manual_crop', crop
    rw = max(np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[3]))
    rh = max(np.linalg.norm(q[3] - q[0]), np.linalg.norm(q[2] - q[1]))
    factor = min(1., 2400 / max(rw, rh))
    rw, rh = max(4, round(rw * factor)), max(4, round(rh * factor))
    matrix = cv2.getPerspectiveTransform(q, np.float32([[0, 0], [rw - 1, 0], [rw - 1, rh - 1], [0, rh - 1]]))
    # All quadrilateral vertices lie inside the frame. No reconstruction of
    # unseen sticker corners; black border instead of replicated/extrapolated data.
    rect = cv2.warpPerspective(image, matrix, (rw, rh), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    yield 'manual_perspective', rect
    yield 'manual_perspective_clahe', contrast(rect)


def decode(image):
    start = time.perf_counter()
    codes = []
    seen = set()
    for downscale in (False, True):
        for code in zxingcpp.read_barcodes(image, try_rotate=True, try_downscale=downscale,
                                          try_invert=True, return_errors=False):
            points = [[getattr(code.position, n).x, getattr(code.position, n).y]
                      for n in ('top_left', 'top_right', 'bottom_right', 'bottom_left')]
            key = (str(code.format), code.text, str(points))
            if key in seen:
                continue
            seen.add(key)
            codes.append(dict(format=str(code.format), text=code.text, polygon=points,
                              downscale=downscale, valid=code.valid))
    return dict(codes=codes, seconds=round(time.perf_counter() - start, 4))


def infer(root):
    root = Path(root)
    inventory = json.loads((root / 'inventory.json').read_text(encoding='utf-8'))
    annotation_bytes = (root / 'annotations.json').read_bytes()
    expected = (root / 'annotations.sha256').read_text().strip()
    if digest(annotation_bytes) != expected:
        raise ValueError('Annotations changed since visual review was frozen')
    # Only visible geometry reaches preprocessing/inference. No expected fields,
    # classes, watermark content, filename tokens or case IDs are input features.
    geometry = {r['sha256']: r['visible_plane_quad'] for r in json.loads(annotation_bytes)['annotations']}
    before = []
    for archive in inventory['archives']:
        data = Path(archive['path']).read_bytes()
        if digest(data) != archive['sha256']:
            raise ValueError('Original archive hash changed')
        with zipfile.ZipFile(archive['path']) as z:
            if z.testzip() is not None:
                raise ValueError('Unreadable original ZIP')
        before.append(dict(path=archive['path'], sha256=digest(data), bytes=len(data)))
    cache = root / 'variant-cache'
    cache.mkdir(exist_ok=True)
    load_start = time.perf_counter()
    engine = PaddleONNX(threads=4, long_side=1600, detector='mobile', recognizer='latin')
    load_seconds = time.perf_counter() - load_start
    implementation = digest(Path(__file__).read_bytes() + Path('backend/gate/pretrained_ocr.py').read_bytes()
                            + Path('backend/gate/samsung_pretrained.py').read_bytes())
    signature = digest(json.dumps([VERSION, implementation, engine.model_hashes, expected], sort_keys=True).encode())
    rows = []
    wall_start = time.perf_counter()
    for photo in inventory['photos']:
        archive = Path('data/Samsung/original') / photo['source_archive']
        with zipfile.ZipFile(archive) as z:
            source = z.read(photo['source_entry'])
        if digest(source) != photo['sha256']:
            raise ValueError('Original photo hash changed')
        image = read_image(source)
        for name, pixels in variants(image, geometry[photo['sha256']]):
            key = digest(signature.encode() + photo['sha256'].encode() + name.encode()
                         + str(pixels.shape).encode() + pixels.tobytes())
            target = cache / (key + '.json')
            if target.exists():
                result = json.loads(target.read_text(encoding='utf-8'))
            else:
                start = time.perf_counter()
                ocr = engine.read(pixels)
                ocr['records'] = extract_records(ocr)
                result = dict(variant=name, source_sha256=photo['sha256'], pixels_sha256=digest(pixels.tobytes()),
                              shape=list(pixels.shape), ppocr=ocr, zxing=decode(pixels),
                              inference_seconds=round(time.perf_counter() - start, 4))
                save(target, result)
            # Anonymized handle is attached only after inference.
            rows.append(dict(photo_id=photo['photo_id'], **result))
        print(f"{photo['photo_id']} complete: {len(rows)} image/variant pairs", flush=True)
    after = []
    for archive in before:
        data = Path(archive['path']).read_bytes()
        if digest(data) != archive['sha256']:
            raise ValueError('Original archive was modified')
        after.append(dict(path=archive['path'], sha256=digest(data), bytes=len(data)))
    # Recheck every original member after processing, not only container hashes.
    for photo in inventory['photos']:
        with zipfile.ZipFile(Path('data/Samsung/original') / photo['source_archive']) as z:
            if digest(z.read(photo['source_entry'])) != photo['sha256']:
                raise ValueError('Original member changed')
    report = dict(version=VERSION, signature=signature, annotations_sha256=expected,
                  implementation_sha256=implementation, models=engine.model_hashes,
                  load_seconds=round(load_seconds, 3), wall_seconds=round(time.perf_counter() - wall_start, 3),
                  original_archives_before=before, original_archives_after=after,
                  all_28_members_unchanged=True, photos=28, rows=rows,
                  geometry_notice='Manual visible-plane geometry only; never automatic detection or hidden-label reconstruction.')
    save(root / 'results.json', report)
    return report


def exact_raw(text, value, key):
    # Only literal matching, case normalization for the printed uppercase codes.
    if key == 'model':
        return bool(re.search(r'(?<![A-Z0-9])' + re.escape(value) + r'(?:/DS)?(?![A-Z0-9])', text.upper()))
    return bool(re.search(r'(?<![A-Z0-9])' + re.escape(value) + r'(?![A-Z0-9])', text.upper()))


def evaluate(root):
    root = Path(root)
    result = json.loads((root / 'results.json').read_text(encoding='utf-8'))
    ann = {r['photo_id']: r for r in json.loads((root / 'annotations.json').read_text(encoding='utf-8'))['annotations']}
    assert digest((root / 'annotations.json').read_bytes()) == result['annotations_sha256']
    details = []
    for row in result['rows']:
        text = '\n'.join(l['text'] for l in row['ppocr']['lines'])
        for field in ann[row['photo_id']]['fields']:
            value, key = field['value'], field['key']
            if value is None:
                continue
            records = [r for r in row['ppocr']['records'] if r['key'] == key]
            values = {r['value'].removesuffix('/DS') if key == 'model' else r['value'] for r in records}
            # ZXing payloads carry values, not IMEI slot names. Slot attribution
            # here is an evaluation association using manually transcribed truth.
            payloads = {b['text'] for b in row['zxing']['codes'] if b['valid']}
            details.append(dict(photo_id=row['photo_id'], variant=row['variant'], key=key,
                                ppocr_extracted=value in values, ppocr_literal=exact_raw(text, value, key),
                                ppocr_other_candidate=bool(values - {value}), zxing_payload=value in payloads,
                                overlap=field['watermark_overlap'], confounders=ann[row['photo_id']]['confounders']))
    counts = []
    for variant in FULL + ROI:
        rows = [r for r in result['rows'] if r['variant'] == variant]
        scores = [d for d in details if d['variant'] == variant]
        counts.append(dict(variant=variant, images=len(rows),
                           ppocr_seconds=round(sum(r['ppocr']['seconds'] for r in rows), 3),
                           zxing_seconds=round(sum(r['zxing']['seconds'] for r in rows), 3),
                           fields={k: dict(denominator=sum(d['key'] == k for d in scores),
                                   **{metric: sum(d['key'] == k and d[metric] for d in scores)
                                      for metric in ('ppocr_extracted', 'ppocr_literal', 'ppocr_other_candidate', 'zxing_payload')})
                                   for k in FIELDS}))
    summary = dict(counts=counts, details=details,
                   caution='Source-visible single-review references; ambiguous fields excluded, not independent Samsung registry. No unwatermarked paired controls; no causal percentage or classification accuracy inferred.',
                   serial='No source-visible serial ground truth; N/A, not a demonstrated extraction failure.',
                   barcode='Exact payload match only. IMEI slot association is post-inference evaluation, not decoder slot extraction. SN/model/SKU need not be encoded.')
    save(root / 'evaluation.json', summary)
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report-dir', type=Path, default=Path('reports/samsung-watermark'))
    p.add_argument('--evaluate-only', action='store_true')
    args = p.parse_args()
    if not args.evaluate_only:
        infer(args.report_dir)
    evaluate(args.report_dir)
