from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4
import cv2
from .config import ALGORITHM_VERSION, MAX_ANALYSIS_SIDE, load_config
from .models import Analysis, Metrics
from .decoder import ZXingDecoder, decode_attempts, detect_candidate
from .decision_engine import decide
from .metrics import sharpness, brightness, contrast, barcode_size, barcode_position, glare, perspective

def analyze(image, config=None, decoder=None, request_id=None):
    start = perf_counter()
    c = config or load_config()
    original_h, original_w = image.shape[:2]
    # Decode original resolution; metric processing is bounded and uses original pixels.
    barcode = decode_attempts(image, decoder or ZXingDecoder())
    scale = min(1., MAX_ANALYSIS_SIDE/max(original_h,original_w))
    bounded = cv2.resize(image, (max(1,round(original_w*scale)),max(1,round(original_h*scale)))) if scale < 1 else image
    gray = cv2.cvtColor(bounded, cv2.COLOR_BGR2GRAY)
    if not barcode.detected:
        barcode = detect_candidate(gray)
        if barcode.bounding_box:
            barcode.bounding_box = [round(v/scale) for v in barcode.bounding_box]
    roi = gray
    m = Metrics(global_contrast=contrast.measure(gray))
    if barcode.bounding_box:
        x1,y1,x2,y2 = [round(v*scale) for v in barcode.bounding_box]
        roi = gray[max(0,y1):min(gray.shape[0],y2+1),max(0,x1):min(gray.shape[1],x2+1)]
        if roi.size == 0: roi = gray
        m.barcode_area,m.barcode_area_ratio,m.barcode_width_ratio,m.barcode_height_ratio = barcode_size.measure(barcode.bounding_box,image.shape)
        m.edge_margin,m.possible_crop,m.critical_crop = barcode_position.measure(barcode.bounding_box,image.shape,c.edge_margin_min)
    m.sharpness = sharpness.measure(roi)
    m.brightness,m.dark_pixel_ratio,m.overexposed_pixel_ratio = brightness.measure(roi)
    m.contrast = contrast.measure(roi)
    m.glare = glare.measure(roi)
    m.angle,m.perspective = perspective.measure(barcode.polygon)
    m.blur_detected = m.sharpness < c.sharpness_min
    m.too_dark = m.brightness < c.brightness_min or m.dark_pixel_ratio > c.dark_pixel_max
    m.too_bright = m.brightness > c.brightness_max
    m.overexposed = m.overexposed_pixel_ratio > c.overexposure_max
    m.low_contrast = m.contrast < c.contrast_min
    m.excessive_perspective = m.perspective > c.perspective_max
    decision, score, issues, recommendations = decide(barcode,m,c)
    return Analysis(request_id=request_id or str(uuid4()), timestamp=datetime.now(timezone.utc).isoformat(),decision=decision,quality_score=score,barcode=barcode,metrics=m,issues=issues,recommendations=recommendations,processing_time_ms=round((perf_counter()-start)*1000,2),algorithm_version=ALGORITHM_VERSION,config_version=c.version)
