from typing import Protocol
from pydantic import BaseModel, Field

class QualityPrediction(BaseModel):
    good_probability: float = Field(ge=0,le=1)
    model_version: str

class ImageQualityClassifier(Protocol):
    """Future additional signal. Never substitutes successful barcode decoding."""
    def predict(self, image) -> QualityPrediction: ...
