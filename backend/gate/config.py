import hashlib
import json
import os
from pathlib import Path
from pydantic import BaseModel, Field, model_validator


class Thresholds(BaseModel):
    model_config = {'extra': 'forbid'}
    sharpness_min: float = Field(60, ge=1, le=2000)
    sharpness_critical: float = Field(15, ge=0, le=1000)
    brightness_min: float = Field(45, ge=0, le=254)
    brightness_max: float = Field(240, ge=1, le=255)
    dark_pixel_max: float = Field(.75, ge=0, le=1)
    overexposure_max: float = Field(.85, ge=0, le=1)
    contrast_min: float = Field(30, ge=1, le=128)
    barcode_area_min: float = Field(.015, gt=0, le=.8)
    barcode_width_min: float = Field(.15, gt=0, le=.9)
    edge_margin_min: float = Field(.02, ge=0, le=.2)
    glare_max: float = Field(.15, gt=0, le=1)
    perspective_max: float = Field(.45, gt=0, le=1)
    quality_score_min: float = Field(75, ge=0, le=100)
    decode_weight: float = Field(.35, gt=0, le=1)

    @model_validator(mode='after')
    def coherent(self):
        if self.brightness_min >= self.brightness_max or self.sharpness_critical > self.sharpness_min:
            raise ValueError('Threshold ranges are inconsistent')
        return self

    @property
    def version(self):
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:12]


def load_config():
    path = Path(os.getenv('GATE_CONFIG', 'config/thresholds.json'))
    return Thresholds.model_validate_json(path.read_text()) if path.exists() else Thresholds()


MAX_UPLOAD_BYTES = int(os.getenv('MAX_UPLOAD_BYTES', 12 * 1024 * 1024))
MAX_IMAGE_PIXELS = int(os.getenv('MAX_IMAGE_PIXELS', 24_000_000))
MAX_ANALYSIS_SIDE = int(os.getenv('MAX_ANALYSIS_SIDE', 2400))
ALGORITHM_VERSION = '1.0.1'
