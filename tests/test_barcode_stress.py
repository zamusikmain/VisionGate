"""Stress infrastructure correctness, independent of desired quality outcomes."""
from pathlib import Path
import hashlib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend import main
from backend.gate.models import Analysis, Barcode, Metrics
from tools import barcode_stress as stress


def test_generator_is_deterministic_and_has_all_families():
    first=list(stress.generate());second=list(stress.generate())
    assert len(first)==164
    assert len({case.name for case in first})==164
    assert {case.family for case in first}=={'control','blur','lighting','glare','crop','perspective','occlusion'}
    for a,b in zip(first,second):
        assert a.name==b.name and a.parameters==b.parameters
        assert a.image.dtype==np.uint8 and a.image.ndim==3
        assert np.array_equal(a.image,b.image)
        if a.family=='occlusion':
            x1,y1,x2,y2=a.parameters['mask_box']
            sx1,sy1,sx2,sy2=a.parameters['source_box']
            assert sx1<=x1<x2<=sx2 and sy1<=y1<y2<=sy2
            assert a.parameters['occluded_symbol_area_fraction']==pytest.approx((x2-x1)*(y2-y1)/((sx2-sx1)*(sy2-sy1)))
            original,_,_=stress.source(a.symbol)
            outside=np.ones(a.image.shape[:2],bool);outside[y1:y2,x1:x2]=False
            assert np.array_equal(a.image[outside],original[outside])


def test_real_api_report_redacts_values_and_preserves_sources(tmp_path,monkeypatch):
    cases=list(stress.generate())
    selected=[c for c in cases if c.family=='control']+[next(c for c in cases if c.family=='occlusion')]
    before=hashlib.sha256(Path('config/thresholds.json').read_bytes()).hexdigest()
    monkeypatch.setenv('HISTORY_DB',str(tmp_path/'history.db'))
    monkeypatch.setenv('STORE_ANALYSIS_IMAGES','false')
    monkeypatch.setattr(stress,'generate',lambda:iter(selected))
    monkeypatch.chdir(tmp_path)
    with TestClient(main.app) as client:
        report=stress.run(client,'reports/stress')
    assert report['counts'].get('TECHNICAL_ERROR',0)==0
    assert all(row['decision']=='ACCEPT' and row['payload_matches'] is True for row in report['cases'][:2])
    assert all('value' not in row['barcode'] for row in report['cases'])
    assert all((tmp_path/'reports/stress'/row['image']).is_file() for row in report['cases'])
    assert selected[0].payload not in (tmp_path/'reports/stress/results.json').read_text()
    assert (tmp_path/'reports/stress/results.csv').is_file()
    assert (tmp_path/'reports/stress/report.md').is_file()
    monkeypatch.undo()
    assert hashlib.sha256(Path('config/thresholds.json').read_bytes()).hexdigest()==before


@pytest.mark.parametrize('path',['dataset/good','holdout/bad','reports','config','../outside'])
def test_output_never_enters_dataset(path,tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):stress.safe_output(path)


def test_http_failure_is_never_counted_as_retake(tmp_path,monkeypatch):
    import httpx
    from backend.gate.config import Thresholds
    monkeypatch.chdir(tmp_path)
    image,_,payload=stress.source('code128')
    monkeypatch.setattr(stress,'generate',lambda:iter([stress.Case('control','control','code128',image,payload)]))
    def transport(request):
        if request.method=='GET':
            return httpx.Response(200,json={'config_version':Thresholds().version,'thresholds':Thresholds().model_dump()})
        return httpx.Response(503,json={'error':'BUSY'})
    with httpx.Client(base_url='http://test',transport=httpx.MockTransport(transport)) as client:
        report=stress.run(client,'reports/stress')
    assert report['counts']=={'TECHNICAL_ERROR':1}
    assert 'decision' not in report['cases'][0]


def test_occluded_accept_is_review_candidate_not_assumed_wrong_decode():
    case=next(c for c in stress.generate() if c.family=='occlusion')
    result=Analysis(request_id='synthetic',timestamp='synthetic',decision='ACCEPT',quality_score=100,
                    barcode=Barcode(decoded=True,value=case.payload),metrics=Metrics(),issues=[],recommendations=[],
                    processing_time_ms=1,algorithm_version='test',config_version='test')
    row=stress.review(case,result)
    assert row['payload_matches'] is True
    assert row['review_flags']==['OCCLUDED_ACCEPT_COMPLETENESS_REVIEW']


def test_configuration_drift_aborts_study(tmp_path,monkeypatch):
    import httpx
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stress,'generate',lambda:iter([]))
    calls=[]
    def transport(request):
        calls.append(request)
        return httpx.Response(200,json={'config_version':str(len(calls))})
    with httpx.Client(base_url='http://test',transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(RuntimeError,match='configuration changed'):
            stress.run(client,'reports/stress')


def test_output_symlink_cannot_redirect_into_dataset(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path/'dataset').mkdir()
    try:
        (tmp_path/'reports').symlink_to(tmp_path/'dataset',target_is_directory=True)
    except OSError:
        pytest.skip('Symlink creation unavailable')
    with pytest.raises(ValueError):stress.safe_output('reports/stress')
