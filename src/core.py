"""Local OCR service. No network calls, disk history, or telemetry."""
from dataclasses import dataclass
from pathlib import Path
from io import BytesIO
import time
import numpy as np
from PIL import Image, ImageOps

SUPPORTED = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff', '.jfif'}
MAX_PIXELS = 40_000_000

@dataclass
class Recognition:
    text: str
    lines: int
    confidence: float
    seconds: float
    width: int
    height: int

def load_image(source):
    if isinstance(source, bytes):
        source = BytesIO(source)
    with Image.open(source) as original:
        if original.width * original.height > MAX_PIXELS:
            raise ValueError('图片过大，请裁剪到 4000 万像素以内后重试。')
        image = ImageOps.exif_transpose(original)
        if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
            rgba = image.convert('RGBA')
            background = Image.new('RGBA', rgba.size, 'white')
            image = Image.alpha_composite(background, rgba)
        image = image.convert('RGB')
        image.thumbnail((5000, 5000))
        return image.copy()

class OCRService:
    def __init__(self):
        self.engine = None

    def recognize(self, source):
        start = time.perf_counter()
        image = load_image(source)
        if self.engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self.engine = RapidOCR()
        bgr = np.asarray(image)[:, :, ::-1].copy()
        result, _ = self.engine(bgr)
        entries = result or []
        return Recognition('\n'.join(str(row[1]) for row in entries), len(entries),
                           sum(float(row[2]) for row in entries) / max(1, len(entries)),
                           time.perf_counter() - start, *image.size)

def write_text(path, text):
    Path(path).write_text(text, encoding='utf-8-sig')
