from typing import Protocol
import cv2
import zxingcpp
from .models import Barcode


class BarcodeDecoder(Protocol):
    def decode(self, image) -> list[Barcode]: ...


class ZXingDecoder:
    def decode(self, image):
        result = []
        for b in zxingcpp.read_barcodes(image, try_rotate=True, try_downscale=True, return_errors=True):
            points = [[p.x, p.y] for p in (b.position.top_left, b.position.top_right, b.position.bottom_right, b.position.bottom_left)]
            xs, ys = zip(*points)
            result.append(Barcode(detected=True, decoded=b.valid, type=str(b.format), value=b.text if b.valid else None,
                                  polygon=points, bounding_box=[min(xs), min(ys), max(xs), max(ys)]))
        return result


def decode_attempts(image, decoder: BarcodeDecoder):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variants = [('original', lambda: image), ('grayscale', lambda: gray),
                ('clahe', lambda: cv2.createCLAHE(2, (8, 8)).apply(gray)),
                ('threshold', lambda: cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7)),
                ('sharpened', lambda: cv2.addWeighted(gray, 1.5, cv2.GaussianBlur(gray, (0, 0), 1), -.5, 0))]
    best = []
    for method, make in variants:
        found = decoder.decode(make())
        for b in found:
            b.decode_method = method
        valid = [b for b in found if b.decoded]
        if valid:
            chosen = max(valid, key=lambda b: (b.bounding_box[2]-b.bounding_box[0])*(b.bounding_box[3]-b.bounding_box[1]))
            chosen.count = len(valid)
            return chosen
        if found:
            best = found
    if best:
        best[0].count = len(best)
        return best[0]
    return Barcode()


def detect_candidate(gray):
    # Localization fallback is only a candidate; it cannot satisfy decode requirements.
    grad = cv2.Sobel(gray, cv2.CV_32F, 1, 0) - cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    grad = cv2.convertScaleAbs(grad)
    _, mask = cv2.threshold(cv2.blur(grad, (9, 9)), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (21, 7)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        x, y, w, h = cv2.boundingRect(c)
        if w > 2*h and w*h > gray.size*.002:
            return Barcode(detected=True, bounding_box=[x,y,x+w,y+h], count=1)
    return Barcode()
