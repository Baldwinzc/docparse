from __future__ import annotations

from uuid import uuid4

from docparse.adapters.parsers.ocr import (
    OcrClient,
    angle_note,
    get_ocr_client,
    ocr_blocks,
)
from docparse.domain.ir import BoundingBox, DocumentIR, Page, TextBlock

RENDER_ZOOM = 2.0
JPEG_QUALITY = 90


def parse_pdf(
    data: bytes,
    *,
    file_id: str,
    filename: str,
    ocr: OcrClient | None = None,
) -> DocumentIR:
    """PDF → IR：逐页有文字层抽字块（带 bbox）；无文字层渲染出图走云 OCR。

    渲染时应用页面 rotation（横页竖图自动转正）；OCR 返回的整页 angle 留档进
    warnings，bbox 统一为正立图参照系（给 #62 版面重建）。
    """
    try:
        import pymupdf  # type: ignore
    except ImportError:
        return DocumentIR(
            document_id=uuid4().hex,
            file_id=file_id,
            filename=filename,
            media_type="application/pdf",
            warnings=["未安装 pymupdf，PDF 仅登记未抽文本。pip install 'docparse[pdf]'"],
            raw_text="",
        )

    client = ocr if ocr is not None else get_ocr_client()
    matrix = pymupdf.Matrix(RENDER_ZOOM, RENDER_ZOOM)
    pages: list[Page] = []
    warnings: list[str] = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for index, page in enumerate(doc, start=1):
            blocks = _text_blocks(page, index)
            if blocks:
                pages.append(
                    Page(
                        page_number=index,
                        width=float(page.rect.width),
                        height=float(page.rect.height),
                        blocks=blocks,
                    )
                )
                continue
            pages.append(
                _ocr_page(
                    page,
                    index,
                    client=client,
                    filename=filename,
                    warnings=warnings,
                    matrix=matrix,
                )
            )
    texts = ["\n".join(block.text for block in page.blocks) for page in pages]
    return DocumentIR(
        document_id=uuid4().hex,
        file_id=file_id,
        filename=filename,
        media_type="application/pdf",
        pages=pages,
        raw_text="\n".join(texts),
        warnings=warnings,
    )


def _text_blocks(page, index: int) -> list[TextBlock]:
    """文字层字块，bbox 用 fitz 显示坐标系（pt，已应用页面 rotation）。"""
    blocks: list[TextBlock] = []
    for i, item in enumerate(page.get_text("blocks"), start=1):
        snippet = (item[4] or "").strip()
        if not snippet:
            continue
        if len(item) >= 7 and item[6] != 0:
            continue  # 0=文本块，1=图片块
        blocks.append(
            TextBlock(
                block_id=f"p{index}-b{i}",
                text=snippet,
                bbox=BoundingBox(
                    x0=float(item[0]),
                    y0=float(item[1]),
                    x1=float(item[2]),
                    y1=float(item[3]),
                ),
            )
        )
    return blocks


def _ocr_page(
    page,
    index: int,
    *,
    client: OcrClient,
    filename: str,
    warnings: list[str],
    matrix,
) -> Page:
    """无文字层的页：渲染出图（应用 rotation）→ JPEG → OCR → 行级字块。"""
    pixmap = page.get_pixmap(matrix=matrix)
    image = pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
    outcome = client.read_image(image, filename=f"{filename}#p{index}")
    for warning in outcome.warnings:
        warnings.append(f"第{index}页：{warning}")
    note = angle_note(outcome)
    if note:
        warnings.append(f"第{index}页：{note}")
    width = float(page.rect.width)
    height = float(page.rect.height)
    if outcome.angle % 90 == 0 and outcome.angle % 180 != 0:
        # 内容旋转（无 rotation 元数据）：正立参照系下宽高对调
        width, height = height, width
    return Page(
        page_number=index,
        width=width,
        height=height,
        blocks=ocr_blocks(outcome, prefix=f"p{index}-o", scale=1.0 / RENDER_ZOOM),
    )
