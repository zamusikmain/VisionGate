from typing import Literal
from pydantic import BaseModel, Field


class Barcode(BaseModel):
    detected: bool = False
    decoded: bool = False
    type: str | None = None
    value: str | None = None
    bounding_box: list[int] | None = None
    polygon: list[list[int]] = Field(default_factory=list)
    decode_method: str | None = None
    count: int = 0


class Metrics(BaseModel):
    model_config = {'allow_inf_nan': False}
    sharpness: float = 0
    brightness: float = 0
    dark_pixel_ratio: float = 0
    overexposed_pixel_ratio: float = 0
    contrast: float = 0
    global_contrast: float = 0
    barcode_area: float = 0
    barcode_area_ratio: float = 0
    barcode_width_ratio: float = 0
    barcode_height_ratio: float = 0
    edge_margin: float = 0
    possible_crop: bool = False
    critical_crop: bool = False
    glare: float = 0
    angle: float = 0
    perspective: float = 0
    blur_detected: bool = False
    too_dark: bool = False
    too_bright: bool = False
    overexposed: bool = False
    low_contrast: bool = False
    excessive_perspective: bool = False


class Analysis(BaseModel):
    request_id: str
    timestamp: str
    decision: Literal['ACCEPT', 'RETAKE']
    quality_score: float
    barcode: Barcode
    metrics: Metrics
    issues: list[str]
    recommendations: list[str]
    processing_time_ms: float
    algorithm_version: str
    config_version: str
