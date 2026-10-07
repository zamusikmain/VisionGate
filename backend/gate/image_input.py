from io import BytesIO
import warnings
import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from .config import MAX_IMAGE_PIXELS, MAX_UPLOAD_BYTES


class InvalidImage(ValueError):
    pass

def is_heif(data: bytes):
    # ISO BMFF HEIF brands. This recognizes an unsupported container, not a decoder.
    return len(data) >= 12 and data[4:8] == b'ftyp' and any(
        data[i:i+4] in {b'heic', b'heix', b'hevc', b'hevx', b'mif1', b'msf1'}
        for i in range(8, min(len(data), 64), 4)
    )

def read_image(data: bytes, mime: str | None = None):
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidImage('FILE_TOO_LARGE')
    if is_heif(data):
        raise InvalidImage('UNSUPPORTED_HEIF')
    allowed = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as im:
                if im.format not in allowed or (mime not in {None, '', 'application/octet-stream', allowed.get(im.format)}):
                    raise InvalidImage('INVALID_IMAGE_TYPE')
                if getattr(im, 'n_frames', 1) != 1:
                    raise InvalidImage('UNSUPPORTED_ANIMATION')
                if im.width * im.height > MAX_IMAGE_PIXELS or min(im.size) < 32:
                    raise InvalidImage('INVALID_IMAGE_DIMENSIONS')
                im.verify()
            with Image.open(BytesIO(data)) as im:
                im = ImageOps.exif_transpose(im)
                if 'A' in im.getbands() or 'transparency' in im.info:
                    rgba = im.convert('RGBA')
                    background = Image.new('RGBA', rgba.size, 'white')
                    im = Image.alpha_composite(background, rgba).convert('RGB')
                else:
                    im = im.convert('RGB')
                return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    except InvalidImage:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InvalidImage('CORRUPTED_IMAGE') from exc
