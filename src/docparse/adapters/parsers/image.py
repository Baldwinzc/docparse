from uuid import uuid4

from docparse.domain.ir import DocumentIR, Page


def parse_image(data: bytes, *, file_id: str, filename: str) -> DocumentIR:
    """图片本阶段不跑本地 OCR，只登记，后续可接云 OCR / VLM。"""
    return DocumentIR(
        document_id=uuid4().hex,
        file_id=file_id,
        filename=filename,
        media_type="image/*",
        pages=[Page(page_number=1)],
        warnings=["图片解析未接 OCR。后续可在此调用云 OCR 或 VLM API。"],
    )
