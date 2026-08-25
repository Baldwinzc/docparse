from enum import StrEnum


class SourceKind(StrEnum):
    ZIP = "zip"
    PDF = "pdf"
    EXCEL = "excel"
    IMAGE = "image"
    TEXT = "text"
    UNKNOWN = "unknown"


_ZIP_EXTS = {".zip"}
_PDF_EXTS = {".pdf"}
_EXCEL_EXTS = {".xlsx", ".xls", ".csv"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}
_TEXT_EXTS = {".txt", ".md", ".csv"}
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0"


def detect_kind(filename: str, data: bytes) -> SourceKind:
    name = filename.lower()
    if data.startswith(b"PK") and name.endswith(".xlsx"):
        return SourceKind.EXCEL
    if data.startswith(_OLE2_MAGIC) and name.endswith(".xls"):
        return SourceKind.EXCEL
    if data.startswith(b"PK"):
        return SourceKind.ZIP
    if data.startswith(b"%PDF"):
        return SourceKind.PDF
    if data[:3] in {b"\xff\xd8\xff"} or data.startswith(b"\x89PNG"):
        return SourceKind.IMAGE
    suffix = _suffix(name)
    if suffix in _ZIP_EXTS:
        return SourceKind.ZIP
    if suffix in _PDF_EXTS:
        return SourceKind.PDF
    if suffix in _EXCEL_EXTS:
        return SourceKind.EXCEL
    if suffix in _IMAGE_EXTS:
        return SourceKind.IMAGE
    if suffix in _TEXT_EXTS:
        return SourceKind.TEXT
    if _looks_like_text(data):
        return SourceKind.TEXT
    return SourceKind.UNKNOWN


def _suffix(name: str) -> str:
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1]


def _looks_like_text(data: bytes) -> bool:
    sample = data[:2048]
    if not sample:
        return True
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False
