"""Synthetic checks of fallback gating, provenance and ambiguity policy."""
import copy
import numpy as np
import pytest

from backend.gate.samsung_preprocessing import normalize_illumination,scale2_bounded,variant_to_original,roi_variant_matrix
from backend.gate.samsung_pretrained import needs_illumination,read_pretrained,extract_records
from backend.gate.samsung_auto import summarize_fields,classify_case,REQUIRED


def record(key,value,variant='native',source='PP-OCRv5_ONNX_CPU',valid=True):
    return dict(key=key,value=value,variant=variant,source=source,format_valid=valid)


def test_same_photo_repeats_do_not_confirm_and_conflicts_disable_slot_matching():
    repeated=[record('imei1','490154203237518'),record('imei1','490154203237518','illumination')]
    f=summarize_fields(repeated)[0]
    assert f['repeat_consistent'] and not f['confirmed'] and not f['independent_evidence']
    repeated+=[record('imei','490154203237518',source='barcode'),record('imei1','356938035643809','illumination')]
    fields=summarize_fields(repeated)
    slots=[f for f in fields if f['key']=='imei1']
    assert len(slots)==2 and all(f['conflicted'] and not f['mismatch_eligible'] for f in slots)
    photos=[dict(role=role,sha256=role,fields=copy.deepcopy(fields),checks={k:dict(state='PASS',reason='synthetic') for k in REQUIRED}) for role in ('device','scan')]
    result=classify_case(photos)
    assert result['diagnostic_state']=='UNKNOWN' and result['rejection_status']=='REJECTED_UNVERIFIED'
    assert any(f['code']=='CONFLICTING_IMEI1_READINGS' for f in result['findings'])


def test_invalid_alternative_is_retained_without_overriding_exact_decode():
    records=[record('imei1','490154203237518'),record('imei1','490154203237519','illumination',valid=False),
             record('imei','490154203237518',source='barcode')]
    slots=[f for f in summarize_fields(records) if f['key']=='imei1']
    assert len(slots)==2 and all(f['raw_conflicted'] for f in slots)
    assert {f['value'] for f in slots}=={'490154203237518','490154203237519'}
    assert slots[0]['confirmed'] and not slots[0]['independent_evidence']
    assert not slots[1]['confirmed'] and not slots[1]['format_valid']


def test_illumination_gate_is_field_based_not_expected_value_or_watermark():
    records=[record('imei1','490154203237518'),record('imei2','356938035643809'),record('model','SM-A000X'),record('sku','SM-A000XTEST')]
    assert not needs_illumination(records)
    assert needs_illumination(records[:-1])
    assert needs_illumination(records+[record('imei1','356938035643809','illumination')])


def test_adaptive_pass_preserves_original_and_each_pass_provenance(monkeypatch):
    from backend.gate import samsung_pretrained as module
    calls=[]
    def fake(image,cache_dir=None,variant='ppocr-full',processing='identity'):
        calls.append(variant)
        return dict(lines=[dict(text='IMEI1: 490154203237518',polygon=[[0,0],[30,0],[30,10],[0,10]],score=.9,detection_score=.8)],
                    variant=variant,processing=processing,seconds=.1,models={},cache_hit=False)
    monkeypatch.setattr(module,'_read_one',fake)
    image=np.full((40,70,3),100,np.uint8);before=image.copy()
    r=read_pretrained(image,enhance=True)
    assert calls==['ppocr-full','ppocr-illumination'] and np.array_equal(image,before)
    records=extract_records(r)
    assert {v['variant'] for v in records}==set(calls)
    assert all(v['coordinate_space']=='original' and not v['independent_evidence'] for v in records)
    calls.clear();read_pretrained(image,enhance=False);assert calls==['ppocr-full']
    monkeypatch.setattr(module,'needs_illumination',lambda records:False)
    calls.clear();r=read_pretrained(image,enhance=True)
    assert calls==['ppocr-full'] and not r['illumination']['performed']


def test_normalization_matches_frozen_experiment_and_does_not_modify_source():
    from tools.samsung_watermark_experiment import illumination
    image=np.random.default_rng(7).integers(0,256,(96,171,3),dtype=np.uint8);before=image.copy()
    assert np.array_equal(normalize_illumination(image),illumination(image))
    assert np.array_equal(image,before)


@pytest.mark.parametrize('turns',range(4))
def test_rescaled_rotated_roi_points_round_trip_to_original(turns):
    matrix=roi_variant_matrix(np.eye(3),turns,100,60,320,200)
    q=np.float32([[0,0],[99,0],[99,59],[0,59]])
    import cv2
    transformed=cv2.perspectiveTransform(q[None],np.float64(matrix))[0]
    assert np.allclose(variant_to_original(transformed,matrix),q,atol=.001)


def test_scale_fallback_is_bounded_and_records_actual_scale():
    image=np.zeros((80,121,3),np.uint8)
    pixels,matrix=scale2_bounded(image,max_side=200)
    assert max(pixels.shape[:2])==200 and matrix[0][0]==200/121
    assert variant_to_original([[200,0]],matrix)==[[121.,0.]]
    assert scale2_bounded(image,max_side=121)==(None,None)


def test_cache_fingerprint_separates_recognition_profiles(monkeypatch):
    from tools.samsung_run import fingerprint
    monkeypatch.setenv('SAMSUNG_RECOGNITION_PROFILE','original');a=fingerprint()
    monkeypatch.setenv('SAMSUNG_RECOGNITION_PROFILE','enhanced');assert a!=fingerprint()


def test_corrupt_and_empty_zip_are_explicit_cli_input_errors(tmp_path,monkeypatch,capsys):
    import zipfile
    from tools.samsung_run import main
    broken=tmp_path/'broken.zip';broken.write_bytes(b'not a zip')
    empty=tmp_path/'empty.zip'
    with zipfile.ZipFile(empty,'w'):pass
    for archive in (broken,empty):
        monkeypatch.setattr('sys.argv',['samsung_run','--archives',str(archive),'--output-dir',str(tmp_path/'out'),'--no-ocr'])
        with pytest.raises(SystemExit) as exc:main()
        assert exc.value.code==2
        assert 'Samsung batch input error:' in capsys.readouterr().err


@pytest.mark.parametrize('existing_found',[False,True])
def test_scale_fallback_waits_for_existing_search(existing_found,monkeypatch):
    from backend.gate import samsung_auto as module
    monkeypatch.setenv('SAMSUNG_RECOGNITION_PROFILE','enhanced')
    monkeypatch.setattr(module.ZXingDecoder,'decode',lambda self,image:[])
    monkeypatch.setattr(module,'locate_labels',lambda *a,**k:[])
    code=dict(value='490154203237518',type='Code 128',variant='native-tile',bbox=[1,1,10,10],
              polygon=[[1,1],[10,1],[10,10],[1,10]],quality='native_pixels')
    monkeypatch.setattr(module,'enhanced_barcodes',lambda *a:[code] if existing_found else [])
    calls=[]
    monkeypatch.setattr(module,'scaled_barcodes',lambda image:calls.append(image.shape) or [])
    p=module.analyze_photo(np.zeros((40,60,3),np.uint8),b'synthetic','device',False)
    assert bool(calls)==(not existing_found)
    assert p['extra_passes']['zxing_scale2']['performed']==(not existing_found)


def test_field_evaluation_counts_wrong_candidates_but_excludes_unknown_truth():
    from tools.samsung_field_evaluation import evaluate
    def field(value):return dict(key='imei1',value=value,format_valid=True,confirmed=False)
    annotations=dict(annotations=[dict(photo_id='synthetic',sha256='a',fields=[dict(key='imei1',value='490154203237518')]),
        dict(photo_id='unreadable',sha256='b',fields=[dict(key='imei1',value=None)])])
    report=dict(cases=[dict(photos=[dict(sha256='a',fields=[field('490154203237518'),field('356938035643809')]),
        dict(sha256='b',fields=[field('356938035643809')])])])
    m=evaluate(report,annotations)['fields']['imei1']
    assert (m['references'],m['tp'],m['fp'],m['fn'],m['conflicting_photo_fields'])==(1,1,1,0,1)
    assert m['precision']==.5 and m['recall']==1 and m['exact_only']==0
