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


class CellBorder(BaseModel):
    left: bool = False
    right: bool = False
    top: bool = False
    bottom: bool = False


class Cell(BaseModel):
    address: str
    value: str
    raw_value: str | None = None
    row: int | None = None
    column: int | None = None
    merge_range: str | None = None
    formula: str | None = None
    border: CellBorder | None = None


class KeyValue(BaseModel):
    """版面拆出的键值，还不是报关单字段。"""

    key: str
    value: str
    key_cell: str
    value_cell: str
    strategy: str


class Table(BaseModel):
    header_row: int
    headers: list[str] = Field(default_factory=list)
    header_cells: list[str] = Field(default_factory=list)
    rows: list[dict[str, str]] = Field(default_factory=list)


class Sheet(BaseModel):
    name: str
    cells: list[Cell] = Field(default_factory=list)
    key_values: list[KeyValue] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)


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
