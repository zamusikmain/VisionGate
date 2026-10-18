"""Optional offline OCR evidence adapter. Model scores never prove photo quality."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time

import cv2

VERSION='ppocr-evidence-2'
_lock=threading.Lock()


def extract_records(result):
    if 'passes' in result:
        return [record for item in result['passes'] for record in extract_records(item)]
    from .samsung_auto import parse_fields
    records=[]
    for index,line in enumerate(result.get('lines',[])):
        # Normalize only I/1 in the *field label*, never any identifier digit.
        # Both raw text and this transformation are retained for inspection.
        normalized=re.sub(r'\b[I1]ME[I1]\s*([12])\s*[:：-]?\s*(?=[0-9]{15}\b)',
                          lambda m:'IMEI'+m.group(1)+': ',line['text'],flags=re.I)
        for key,value,valid in parse_fields(normalized):
            records.append(dict(key=key,value=value,format_valid=valid,source='PP-OCRv5_ONNX_CPU',
                variant=result.get('variant','ppocr-full'),region=line['polygon'],line_index=index,
                raw_text=line['text'],field_label_normalized=normalized!=line['text'],
                confidence=line['score'],confidence_calibrated=False,quality='uncalibrated_pretrained_ocr',
                coordinate_space='original',detection_score=line['detection_score'],
                processing=result.get('processing','identity'),independent_evidence=False,
                original_to_variant=[[1,0,0],[0,1,0],[0,0,1]]))
    return records


@lru_cache(maxsize=2)
def _engine(detector,memory_profile='default'):
    from .pretrained_ocr import PaddleONNX
    return PaddleONNX(detector=detector,memory_profile=memory_profile)


def _read_one(image,cache_dir=None,variant='ppocr-full',processing='identity'):
    detector=os.getenv('SAMSUNG_OCR_DETECTOR','mobile')
    memory_profile=os.getenv('SAMSUNG_OCR_MEMORY_PROFILE','default')
    with _lock:
        engine=_engine(detector,memory_profile)
        # Cache identity includes implementation, complete pixels and model hashes.
        implementation=hashlib.sha256((Path(__file__).with_name('pretrained_ocr.py')).read_bytes()).hexdigest()
        signature=json.dumps([VERSION,implementation,engine.model_hashes,engine.long_side,variant,processing,memory_profile],sort_keys=True)
        key=hashlib.sha256(signature.encode()+str(image.shape).encode()+image.tobytes()).hexdigest()
        target=Path(cache_dir)/(key+'.json') if cache_dir else None
        if target and target.exists():
            result=json.loads(target.read_text(encoding='utf-8'));result['cache_hit']=True
            return result
        result=engine.read(image);result.update(status='OK',cache_hit=False,adapter_version=VERSION,
                                               variant=variant,processing=processing)
        if target:
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result


def needs_illumination(records):
    # Recognition targets are not a statement that every field is mandatory.
    # Skip only if all targets have one unambiguous, format-valid reading.
    for key in ('imei1','imei2','model','sku'):
        values={r['value'].removesuffix('/DS') if key=='model' else r['value']
                for r in records if r['key']==key}
        if len(values)!=1 or not all(r['format_valid'] for r in records if r['key']==key):return True
    return False


def read_pretrained(image,cache_dir=None,enhance=False):
    start=time.perf_counter();original=_read_one(image,cache_dir)
    if not enhance:return original
    records=extract_records(original);passes=[original]
    needed=bool(original.get('lines')) and needs_illumination(records)
    reason='missing_or_ambiguous_recognition_target' if needed else 'complete_unambiguous_targets' if original.get('lines') else 'no_text_detected'
    error=None
    if needed:
        from .samsung_preprocessing import normalize_illumination
        try:passes.append(_read_one(normalize_illumination(image),cache_dir,'ppocr-illumination','luminance_low_frequency_normalization_v1'))
        except (ImportError,OSError,ValueError,RuntimeError) as exc:
            error=type(exc).__name__+': '+str(exc)
    return dict(status='PARTIAL' if error else 'OK',passes=passes,
                lines=[line for item in passes for line in item['lines']],models=original['models'],
                seconds=round(sum(item['seconds'] for item in passes),3),
                elapsed_seconds=round(time.perf_counter()-start,3),
                illumination=dict(needed=needed,performed=len(passes)>1,reason=reason,error=error),
                adapter_version=VERSION)
