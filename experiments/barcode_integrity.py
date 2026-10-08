"""Exploratory 1D bar continuity; NOT a calibrated completeness detector."""
import cv2
import numpy as np

VERSION='integrity-research-0.1'
# Research constants only; they do not touch production Thresholds.
RELATIVE_SUPPORT=.30
ROW_VARIATION=.25
MIN_GAP_FRACTION=.10


def longest_run(mask):
    best=current=0
    for value in mask:
        current=current+1 if value else 0
        best=max(best,current)
    return best


def inspect(image, barcode, expected_box=None):
    """Only pixels + decoder geometry. Optional expected_box is external prior.

    The intrinsic result NEVER reads the external box. An external box must come
    from an independently located label/template in a future system; generator
    ground truth used by the runner is an oracle experiment, not such a system.
    """
    result={'version':VERSION,'supported':False,'intrinsic_flags':[],
            'prior_flags':[],'prior_available':expected_box is not None}
    if barcode.get('type') not in ('Code 128','Code128'):
        result['limitation']='Only Code128 is evaluated; QR continuity differs'
        return result
    polygon=barcode.get('polygon',[])
    if len(polygon)!=4:
        result['limitation']='No four-point decoder polygon; integrity unknown'
        return result
    points=np.asarray(polygon,np.float32)
    if points.shape!=(4,2) or not np.isfinite(points).all():
        result['limitation']='Invalid geometry; integrity unknown'
        return result
    width=max(2,round(max(np.linalg.norm(points[1]-points[0]),np.linalg.norm(points[2]-points[3])))+1)
    height=max(2,round(max(np.linalg.norm(points[3]-points[0]),np.linalg.norm(points[2]-points[1])))+1)
    if width>10000 or height>10000 or width*height>4_000_000:
        result['limitation']='Geometry exceeds research bounds'
        return result
    target=np.float32([[0,0],[width-1,0],[width-1,height-1],[0,height-1]])
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    roi=cv2.warpPerspective(gray,cv2.getPerspectiveTransform(points,target),(width,height))
    # Average horizontal edge energy on each rectified scanline.
    profile=np.mean(np.abs(np.diff(roi.astype(np.float32),axis=1)),axis=1)
    reference=float(np.percentile(profile,90))
    if reference<1:
        result['limitation']='Insufficient edge signal; integrity unknown'
        return result
    result['supported']=True
    normalized=profile/reference
    support=normalized>=RELATIVE_SUPPORT
    gap=longest_run(~support)/height
    variation=max(0.,1-float(np.percentile(normalized,10)))
    result.update({'row_gap_fraction':gap,'row_energy_drop':variation,
                   'rectified_width':width,'rectified_height':height})
    if gap>=MIN_GAP_FRACTION:result['intrinsic_flags'].append('SCANLINE_GAP')
    if variation>=ROW_VARIATION:result['intrinsic_flags'].append('ROW_PATTERN_INCONSISTENCY')
    h,w=gray.shape
    if any(x<=1 or y<=1 or x>=w-2 or y>=h-2 for x,y in polygon):
        result['intrinsic_flags'].append('SYMBOL_TOUCHES_FRAME')
    if expected_box is not None:
        x1,y1,x2,y2=map(int,expected_box)
        if not (0<=x1<x2<=w and 0<=y1<y2<=h):
            result['prior_flags'].append('EXPECTED_REGION_OUTSIDE_FRAME')
        else:
            # Axis-aligned prior evaluation: no claim for rotated/warped priors.
            expected=gray[y1:y2,x1:x2].astype(np.float32)
            prior_profile=np.mean(np.abs(np.diff(expected,axis=1)),axis=1)
            prior_reference=float(np.percentile(prior_profile,95))
            if prior_reference>=1:
                coverage=float(np.mean(prior_profile>=RELATIVE_SUPPORT*prior_reference))
                result['prior_row_support_fraction']=coverage
                if coverage<.90:result['prior_flags'].append('EXPECTED_REGION_MISSING_BARS')
    return result
