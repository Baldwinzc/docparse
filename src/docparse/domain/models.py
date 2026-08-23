from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from docparse.domain.fields import ExtractedField
from docparse.domain.ir import DocumentIR


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class DocumentType(StrEnum):
    CUSTOMS_DECLARATION = "customs_declaration"
    INVOICE = "invoice"
    PACKING_LIST = "packing_list"
    BILL_OF_LADING = "bill_of_lading"
    CONTRACT = "contract"
    UNKNOWN = "unknown"


class FileKind(StrEnum):
    RAW = "raw"
    DERIVED = "derived"


class FileRef(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    job_id: str
    filename: str
    content_type: str = "application/octet-stream"
    kind: FileKind = FileKind.RAW
    uri: str
    byte_size: int = 0
    parent_id: str | None = None
    archive_path: str | None = None


class PackageResult(BaseModel):
    documents: list[DocumentIR] = Field(default_factory=list)
    fields: list[ExtractedField] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)


class ReviewEvidence(BaseModel):
    """字段级证据。xlsx 用 sheet/cell；PDF 以后补 page。"""

    sheet: str | None = None
    cell: str | None = None
    page: int | None = None
    quote: str = ""
    filename: str | None = None


class FieldReview(BaseModel):
    """一个报关单字段（或货行字段）的复核项。path 跟目录走，不手写字段表。"""

    path: str
    status: str
    reasons: list[str] = Field(default_factory=list)
    evidence: list[ReviewEvidence] = Field(default_factory=list)


class ParseJobResult(BaseModel):
    status: JobStatus
    package: PackageResult = Field(default_factory=PackageResult)
    declaration: dict[str, Any] | None = None
    reviews: list[FieldReview] = Field(default_factory=list)
    error: str | None = None


class Job(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_filename: str
    source_file_id: str | None = None
    request_id: str | None = None
    caller: dict[str, str] = Field(default_factory=dict)
    result: ParseJobResult | None = None
    error: str | None = None

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)
