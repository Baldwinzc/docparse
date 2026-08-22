from enum import StrEnum

from pydantic import BaseModel, Field


class FieldStatus(StrEnum):
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    MISSING = "missing"
    CONFLICT = "conflict"
    INVALID = "invalid"


class ExtractedField(BaseModel):
    name: str
    display_name: str | None = None
    value: str | None = None
    normalized_value: str | None = None
    confidence: float = 0.0
    status: FieldStatus = FieldStatus.MISSING
    extraction_method: str | None = None
    evidence: list = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    source_document_id: str | None = None


class GoodsItem(BaseModel):
    """一张货表里的一行。跨表补空后仍是这一行，不另开报关单。"""

    fields: dict[str, ExtractedField] = Field(default_factory=dict)
    source_role: str = "unknown"
    source_sheet: str = ""
    source_kind: str = "primary"
    master_score: int = 0
    review_reasons: list[str] = Field(default_factory=list)

    def value_of(self, name: str) -> str | None:
        field = self.fields.get(name)
        if field is None:
            return None
        text = (field.value or "").strip()
        return text or None
