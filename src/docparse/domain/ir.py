from __future__ import annotations

from pydantic import BaseModel, Field

from docparse.domain.fields import ExtractedField


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class TextBlock(BaseModel):
    block_id: str
    text: str
    bbox: BoundingBox | None = None
    ocr_confidence: float | None = None


class Page(BaseModel):
    page_number: int
    width: float | None = None
    height: float | None = None
    blocks: list[TextBlock] = Field(default_factory=list)


class Cell(BaseModel):
    address: str
    value: str
    raw_value: str | None = None
    row: int | None = None
    column: int | None = None


class Sheet(BaseModel):
    name: str
    cells: list[Cell] = Field(default_factory=list)


class Evidence(BaseModel):
    document_id: str
    file_id: str | None = None
    filename: str | None = None
    page: int | None = None
    block_id: str | None = None
    cell: str | None = None
    bbox: BoundingBox | None = None
    quote: str


class DocumentIR(BaseModel):
    """所有解析器的统一中间表示。后续换 OCR / PDF 库时只改 parser。"""

    document_id: str
    file_id: str
    filename: str
    media_type: str
    document_type: str = "unknown"
    document_type_confidence: float = 0.0
    pages: list[Page] = Field(default_factory=list)
    sheets: list[Sheet] = Field(default_factory=list)
    raw_text: str = ""
    warnings: list[str] = Field(default_factory=list)
    fields: list[ExtractedField] = Field(default_factory=list)

    def iter_text(self) -> str:
        if self.raw_text:
            return self.raw_text
        parts: list[str] = []
        for page in self.pages:
            parts.extend(block.text for block in page.blocks)
        for sheet in self.sheets:
            parts.extend(f"{cell.address}:{cell.value}" for cell in sheet.cells)
        return "\n".join(parts)
