"""云 OCR / VLM 预留。本阶段不调用；扫描件 Issue 再实现。"""

from typing import Protocol


class OcrClient(Protocol):
    def read_image(self, data: bytes, *, filename: str) -> str: ...


class UnimplementedOcrClient:
    def read_image(self, data: bytes, *, filename: str) -> str:
        raise NotImplementedError("云 OCR 尚未接入，见 docs/modules.md")
