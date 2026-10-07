from .models import Barcode, Metrics
from .config import Thresholds

RECOMMENDATIONS = {'BARCODE_NOT_FOUND':'FIND_BARCODE', 'MULTIPLE_BARCODES':'ONE_BARCODE', 'BARCODE_TOO_SMALL':'MOVE_CLOSER', 'BARCODE_CROPPED':'SHOW_ENTIRE_BARCODE', 'BLUR':'HOLD_STEADY', 'TOO_DARK':'ADD_LIGHT', 'OVEREXPOSED':'REDUCE_LIGHT', 'LOW_CONTRAST':'IMPROVE_CONTRAST', 'GLARE':'REDUCE_GLARE', 'PERSPECTIVE':'ALIGN_CAMERA', 'DECODE_FAILED':'MAKE_READABLE', 'LOW_QUALITY':'RETAKE'}

def decide(barcode: Barcode, m: Metrics, c: Thresholds):
    issues = []
    hard = False
    def add(code, critical=False):
        nonlocal hard
        issues.append(code)
        hard = hard or critical
    if not barcode.detected: add('BARCODE_NOT_FOUND', True)
    if barcode.count > 1: add('MULTIPLE_BARCODES', True)
    if barcode.detected:
        if m.barcode_area_ratio < c.barcode_area_min or m.barcode_width_ratio < c.barcode_width_min: add('BARCODE_TOO_SMALL', True)
        if m.critical_crop: add('BARCODE_CROPPED', True)
        elif m.possible_crop and not barcode.decoded: add('BARCODE_CROPPED')
    if m.sharpness < c.sharpness_min: add('BLUR', m.sharpness < c.sharpness_critical)
    if m.brightness < c.brightness_min or m.dark_pixel_ratio > c.dark_pixel_max: add('TOO_DARK', True)
    if m.brightness > c.brightness_max or m.overexposed_pixel_ratio > c.overexposure_max: add('OVEREXPOSED', True)
    if m.contrast < c.contrast_min: add('LOW_CONTRAST')
    if m.glare > c.glare_max: add('GLARE')
    if m.perspective > c.perspective_max: add('PERSPECTIVE')
    if barcode.detected and not barcode.decoded: add('DECODE_FAILED', True)
    clamp = lambda v: max(0., min(1., v))
    signals = [clamp(m.sharpness/c.sharpness_min), clamp(m.barcode_area_ratio/c.barcode_area_min), clamp(m.contrast/c.contrast_min), clamp(min(m.brightness/max(c.brightness_min,1), (255-m.brightness)/max(255-c.brightness_max,1))), 1-clamp(m.glare), 0 if m.critical_crop else 1, 1-clamp(m.perspective)]
    score = round(100*(c.decode_weight*int(barcode.decoded)+(1-c.decode_weight)*sum(signals)/len(signals)),2)
    accepted = not hard and score >= c.quality_score_min
    if not accepted and not issues: add('LOW_QUALITY')
    return ('ACCEPT' if accepted else 'RETAKE'), score, issues, [RECOMMENDATIONS[i] for i in issues]
