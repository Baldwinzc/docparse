from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
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


class ParseJobResult(BaseModel):
    status: JobStatus
    package: PackageResult = Field(default_factory=PackageResult)
    error: str | None = None


class Job(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_filename: str
    source_file_id: str | None = None
    result: ParseJobResult | None = None
    error: str | None = None

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)
