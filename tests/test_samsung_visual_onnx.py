from types import SimpleNamespace
import numpy as np
import pytest
from tools.samsung_visual_onnx import VisualONNX


def test_fixed_letterbox_predictions_return_original_pixel_coordinates():
    model=VisualONNX.__new__(VisualONNX);model.classes=('identification_region',)
    model.input=SimpleNamespace(name='images')
    model.session=SimpleNamespace(run=lambda *a: [np.float32([[[160],[280],[160],[80],[.9]]])])
    result=model.predict(np.zeros((600,800,3),np.uint8))
    assert len(result)==1 and np.allclose(result[0]['bbox'],[100,200,300,300])
    assert result[0]['calibrated'] is False
    assert set(result[0])=={'bbox','class_id','class_name','confidence','calibrated'}


def test_wrong_weight_hash_fails_before_model_execution(tmp_path):
    p=tmp_path/'weights.onnx';p.write_bytes(b'not-a-model')
    with pytest.raises(ValueError,match='MODEL_HASH_MISMATCH'):VisualONNX(p,'0'*64,['identification_region'])
