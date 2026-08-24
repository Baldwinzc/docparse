"""把引擎识别框画回原图，供人工验收。"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

from benchmarks.ocr.engines import OcrBox


def draw_boxes(image_bytes: bytes, boxes: list[OcrBox], out_path: Path) -> None:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    for box in boxes:
        draw.rectangle((box.x0, box.y0, box.x1, box.y1), outline="red", width=3)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, format="PNG")
