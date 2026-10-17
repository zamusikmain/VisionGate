import pytest
from tools.release_check import forbidden


@pytest.mark.parametrize('path',['pilot.pt','weights/model.pth','model.safetensors','runs/train/args.yaml','DATA/private.ONNX'])
def test_private_weights_and_training_outputs_cannot_enter_release_index(path):
    assert forbidden(path)
