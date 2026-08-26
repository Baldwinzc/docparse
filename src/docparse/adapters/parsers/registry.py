from collections.abc import Callable

from docparse.adapters.parsers.detect import SourceKind, detect_kind
from docparse.adapters.parsers.excel import parse_excel
from docparse.adapters.parsers.image import parse_image
from docparse.adapters.parsers.ocr import OcrClient
from docparse.adapters.parsers.pdf import parse_pdf
from docparse.adapters.parsers.text import parse_text
from docparse.domain.ir import DocumentIR

Parser = Callable[..., DocumentIR]

_PARSERS: dict[SourceKind, Parser] = {
    SourceKind.PDF: parse_pdf,
    SourceKind.EXCEL: parse_excel,
    SourceKind.IMAGE: parse_image,
    SourceKind.TEXT: parse_text,
}

_OCR_PARSERS = {SourceKind.PDF, SourceKind.IMAGE}


def parse_bytes(
    data: bytes,
    *,
    file_id: str,
    filename: str,
    ocr: OcrClient | None = None,
) -> DocumentIR:
    kind = detect_kind(filename, data)
    parser = _PARSERS.get(kind)
    if parser is None:
        return DocumentIR(
            document_id=file_id,
            file_id=file_id,
            filename=filename,
            media_type="application/octet-stream",
            warnings=[f"暂不支持的文件类型: {kind}"],
        )
    if kind in _OCR_PARSERS:
        return parser(data, file_id=file_id, filename=filename, ocr=ocr)
    return parser(data, file_id=file_id, filename=filename)
