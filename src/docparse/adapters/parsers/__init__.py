from docparse.adapters.parsers.detect import detect_kind
from docparse.adapters.parsers.ocr import OcrClient, UnimplementedOcrClient
from docparse.adapters.parsers.registry import parse_bytes

__all__ = ["OcrClient", "UnimplementedOcrClient", "detect_kind", "parse_bytes"]
