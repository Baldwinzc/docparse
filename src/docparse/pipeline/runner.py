from __future__ import annotations

from collections.abc import Callable

from docparse.adapters.files.base import FileStore
from docparse.adapters.files.factory import get_file_store
from docparse.adapters.jobs.base import JobStore
from docparse.adapters.jobs.factory import get_job_store
from docparse.adapters.llm.openai_compat import OpenAICompatClient
from docparse.config import Settings, get_settings
from docparse.domain.fields import FieldStatus
from docparse.domain.models import Job, JobStatus, ParseJobResult
from docparse.pipeline.context import PipelineContext
from docparse.pipeline.steps.classify import classify_step
from docparse.pipeline.steps.extract_content import extract_content_step
from docparse.pipeline.steps.extract_fields import extract_fields_step
from docparse.pipeline.steps.ingest import ingest_step
from docparse.pipeline.steps.reconcile import reconcile_step
from docparse.pipeline.steps.route_review import route_review_step
from docparse.pipeline.steps.unpack import unpack_step
from docparse.pipeline.steps.validate import validate_step
from docparse.schema.loader import load_schema

Step = Callable[[PipelineContext], None]

DEFAULT_STEPS: list[tuple[str, Step]] = [
    ("ingest", ingest_step),
    ("unpack", unpack_step),
    ("extract", extract_content_step),
    ("classify", classify_step),
    ("extract_fields", extract_fields_step),
    ("validate", validate_step),
    ("reconcile", reconcile_step),
    ("route_review", route_review_step),
]


class Pipeline:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        jobs: JobStore | None = None,
        files: FileStore | None = None,
        llm: OpenAICompatClient | None = None,
        steps: list[tuple[str, Step]] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.jobs = jobs or get_job_store(self.settings)
        self.files = files or get_file_store(self.settings)
        self.llm = llm or OpenAICompatClient(self.settings)
        self.steps = steps or DEFAULT_STEPS

    def submit(self, filename: str, data: bytes) -> Job:
        if len(data) > self.settings.max_upload_mb * 1024 * 1024:
            raise ValueError(f"文件超过 {self.settings.max_upload_mb} MB")
        job = self.jobs.create(Job(source_filename=filename))
        raw = self.files.put(
            data,
            job_id=job.id,
            filename=filename,
            content_type="application/octet-stream",
            kind="raw",
        )
        job = self.jobs.update(job.id, source_file_id=raw.id, status=JobStatus.QUEUED)
        return job

    def run_job(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None or job.source_file_id is None:
            raise KeyError(job_id)
        self.jobs.update(job_id, status=JobStatus.RUNNING)
        raw = self.files.stat(job.source_file_id)
        ctx = PipelineContext(
            job=job,
            settings=self.settings,
            jobs=self.jobs,
            files=self.files,
            llm=self.llm,
            schema=load_schema(),
            raw=raw,
        )
        try:
            for _name, step in self.steps:
                step(ctx)
            status = _status_from_package(ctx)
            result = ParseJobResult(status=status, package=ctx.package)
            return self.jobs.update(job_id, status=status, result=result)
        except Exception as exc:
            result = ParseJobResult(status=JobStatus.FAILED, error=str(exc))
            return self.jobs.update(job_id, status=JobStatus.FAILED, result=result, error=str(exc))

    def process(self, filename: str, data: bytes) -> Job:
        job = self.submit(filename, data)
        return self.run_job(job.id)


def _status_from_package(ctx: PipelineContext) -> JobStatus:
    if ctx.package.review_reasons:
        return JobStatus.NEEDS_REVIEW
    blocking = {FieldStatus.INVALID, FieldStatus.CONFLICT, FieldStatus.NEEDS_REVIEW}
    if any(field.status in blocking for field in ctx.package.fields):
        return JobStatus.NEEDS_REVIEW
    required_missing = [
        field
        for field in ctx.package.fields
        if field.status == FieldStatus.MISSING and field.validation_errors
    ]
    if required_missing:
        return JobStatus.NEEDS_REVIEW
    return JobStatus.SUCCEEDED
