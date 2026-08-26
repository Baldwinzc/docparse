from __future__ import annotations

from uuid import uuid4

from docparse.adapters.parsers.ocr import OcrClient, angle_note, get_ocr_client, ocr_blocks
from docparse.domain.ir import DocumentIR, Page


def parse_image(
    data: bytes,
    *,
    file_id: str,
    filename: str,
    ocr: OcrClient | None = None,
) -> DocumentIR:
    """jpg / png 与扫描 PDF 页走同一云 OCR 入口（#22）。

    页面宽高取自 OCR 返回（正立参照系）；识别失败时只有告警、无字块。
    """
    client = ocr if ocr is not None else get_ocr_client()
    outcome = client.read_image(data, filename=filename)
    warnings = list(outcome.warnings)
    note = angle_note(outcome)
    if note:
        warnings.append(note)
    width = outcome.width or None
    height = outcome.height or None
    return DocumentIR(
        document_id=uuid4().hex,
        file_id=file_id,
        filename=filename,
        media_type="image/*",
        pages=[
            Page(
                page_number=1,
                width=width,
                height=height,
                blocks=ocr_blocks(outcome, prefix="p1-o"),
            )
        ],
        raw_text="\n".join(line.text for line in outcome.lines),
        warnings=warnings,
    )
