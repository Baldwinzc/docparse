from docparse.adapters.parsers.detect import detect_kind
from docparse.adapters.parsers.local_ocr import LocalOcrClient, get_local_ocr_client
from docparse.adapters.parsers.ocr import (
    OcrClient,
    OcrLine,
    OcrOutcome,
    TextinOcrClient,
    get_ocr_client,
)
from docparse.adapters.parsers.ocr_layout import reconstruct_document, reconstruct_page
from docparse.adapters.parsers.registry import parse_bytes

__all__ = [
    "LocalOcrClient",
    "OcrClient",
    "OcrLine",
    "OcrOutcome",
    "TextinOcrClient",
    "detect_kind",
    "get_local_ocr_client",
    "get_ocr_client",
    "parse_bytes",
    "reconstruct_document",
    "reconstruct_page",
]
