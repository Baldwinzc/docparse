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
