"""Role-specific photo requirements. No corpus labels/expected values at inference."""
import cv2
import numpy as np

VERSION='role-policy-1'
COMMON=('identification_visible','identifier_readable','barcode_readable',
        'identification_not_cropped','information_image_quality','screen_recapture_absent')
REQUIRED={'device':('device_top_visible',)+COMMON,'scan':COMMON}


def apply_role_policy(photo,image):
    checks={k:dict(state='UNKNOWN',reason='Required evidence not established.',source='role_policy',preliminary=True)
            for k in REQUIRED[photo['role']]}
    def put(k,state,reason,source='recognition',confirmed_failure=False):
        checks[k]=dict(state=state,reason=reason,source=source,preliminary=not confirmed_failure,
                       confirmed_failure=confirmed_failure)
    # IMEI / serial are alternatives; model, SKU and a second IMEI are not
    # compulsory just because they can be recognized. Keep all diagnostic fields.
    identity=[f for f in photo['fields'] if f['key'] in {'imei','imei1','imei2','serial'} and f['format_valid']]
    readable=[f for f in identity if f['key']!='imei' and not f.get('conflicted')]
    codes=[b for b in photo['barcodes'] if b.get('checksum_valid')]
    linear=[b for b in codes if b['type'] in {'Code 128','Code 39','ITF'}]
    h,w=image.shape[:2]
    if linear:put('barcode_readable','PASS','At least one identification-format linear symbol decoded. This does not approve the photograph.')
    if readable and linear:
        put('identification_visible','PASS','Context-tagged IMEI/serial text and a linear code are observed; no requirement for a complete outer label border.')
        put('identifier_readable','PASS','A complete format-valid printed identification candidate is readable; conflicting candidates remain unresolved.')
        # A readable region is not proof that other necessary information is
        # visible. Without verified target coverage, retain UNKNOWN rather than
        # treat every frame-edge contact as either PASS or a confirmed crop.
        put('identification_not_cropped','UNKNOWN','Readable content exists, but complete critical-region coverage has not been established. Optional label edges are not compulsory.')
    if photo.get('conflicting_fields') or any(f.get('conflicted') for f in identity):
        put('identifier_readable','UNKNOWN','Variants disagree; no convenient identifier was selected.')
    old=photo['checks']
    from .samsung_screen import gallery_evidence
    gallery=gallery_evidence(photo.get('screen_ui_ocr',{}),photo['barcodes'],h)
    if gallery:
        put('screen_recapture_absent','FAIL',gallery['reason'],source=gallery['source'],confirmed_failure=True)
        photo.setdefault('problems',[]).append(dict(code=gallery['code'],bbox=gallery['regions'][0],evidence=gallery))
    if not gallery and old.get('physical_object',{}).get('state')=='FAIL':
        put('screen_recapture_absent','UNKNOWN','Legacy screen heuristic fired; a validated localized recapture finding is still required.')
    # Exact empty/constant extremes can be verified independently of a dataset.
    # These do not stand in for an unvalidated blur/glare detector on real photos.
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    if float(gray.max())-float(gray.min())<=1:
        for k in ('identifier_readable','information_image_quality'):
            put(k,'FAIL','The entire supplied image is constant and contains no readable identification information.',
                source='pixel_constant_image',confirmed_failure=True)
    else:
        put('information_image_quality','UNKNOWN','Functional readings do not by themselves verify all critical information against blur, darkness, glare or occlusion.')
    if photo['role']=='device':
        put('device_top_visible','UNKNOWN','Two box faces including the identification side and box top have no verified automatic detector; generic rectangles are only candidates.')
    photo.update(legacy_checks=old,checks=checks,mandatory_checks=list(REQUIRED[photo['role']]),
                 policy_profile='role-v1',role_policy_version=VERSION,
                 policy_notice='Identification-region requirements differ by role. No universal whole-label, model/SKU, dual-IMEI or separate-SN requirement is assumed.')
    return photo
