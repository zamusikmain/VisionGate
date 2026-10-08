"""Offline prototype checks, never asserts production quality-rule changes."""
import cv2
import numpy as np
from backend.gate.decoder import ZXingDecoder
from experiments.barcode_integrity import inspect
from experiments.run_integrity import controls
from tools.barcode_stress import source


def decode(image):
    return next(b.model_dump() for b in ZXingDecoder().decode(image) if b.decoded)


def test_clean_and_rotated_short_barcodes_have_no_intrinsic_flags():
    for case in controls():
        result=inspect(case.image,decode(case.image))
        assert result['supported'],case.name
        assert not result['intrinsic_flags'],(case.name,result)


def test_middle_occlusion_is_detected_without_external_prior():
    image,(x1,y1,x2,y2),_=source('code128')
    image[y1+50:y1+150,x1:x2]=255
    result=inspect(image,decode(image))
    assert 'SCANLINE_GAP' in result['intrinsic_flags']
    assert not result['prior_available']


def test_severe_edge_occlusion_needs_external_extent_prior():
    image,box,_=source('code128');x1,y1,x2,y2=box
    image[y1:y1+180,x1:x2]=255
    barcode=decode(image)
    intrinsic=inspect(image,barcode)
    prior=inspect(image,barcode,box)
    assert intrinsic['intrinsic_flags']==[]
    assert prior['intrinsic_flags']==intrinsic['intrinsic_flags']
    assert prior['prior_flags']==['EXPECTED_REGION_MISSING_BARS']


def test_identical_pixels_cannot_distinguish_occluded_from_short_barcode():
    image,(x1,y1,x2,y2),_=source('code128')
    image[y1:y1+180,x1:x2]=255
    normal=next(c for c in controls() if c.name=='normal-short-on-tall-label')
    assert np.array_equal(image,normal.image)
    assert inspect(image,decode(image))==inspect(normal.image,decode(normal.image))


def test_qr_is_unknown_not_claimed_complete():
    image,_,_=source('qr')
    result=inspect(image,decode(image))
    assert not result['supported'] and 'QR' in result['limitation']


def test_missing_geometry_is_unknown():
    image,_,_=source('code128')
    result=inspect(image,{'type':'Code128','polygon':[]})
    assert not result['supported']


def test_expected_box_outside_frame_is_separate_prior_flag():
    image,_,_=source('code128')
    result=inspect(image,decode(image),[-1,0,100,100])
    assert result['prior_flags']==['EXPECTED_REGION_OUTSIDE_FRAME']
    assert result['intrinsic_flags']==[]


def test_invalid_or_unbounded_geometry_never_allocates_a_huge_roi():
    image,_,_=source('code128')
    for polygon in ([[0,0],[9000,0],[9000,9000],[0,9000]],
                    [[0,0],[float('nan'),0],[2,2],[0,2]]):
        result=inspect(image,{'type':'Code128','polygon':polygon})
        assert not result['supported']
