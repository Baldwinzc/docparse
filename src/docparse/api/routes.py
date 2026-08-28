from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from docparse.api.catalog import schema_catalog
from docparse.api.errors import not_found
from docparse.api.export_dec import to_dec_envelope
from docparse.api.schemas import DECLARE_EXAMPLE, JOB_EXAMPLE, multipart_openapi
from docparse.api.submit import submit_upload
from docparse.domain.models import Job
from docparse.pipeline.runner import Pipeline

_REVIEW_PAGE = Path(__file__).with_name("static") / "review.html"

router = APIRouter()


@lru_cache(maxsize=1)
def get_pipeline() -> Pipeline:
    return Pipeline()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
@router.get("/review")
def review_page() -> FileResponse:
    return FileResponse(_REVIEW_PAGE, media_type="text/html; charset=utf-8")


@router.get("/v1/schema")
def get_schema() -> dict:
    return schema_catalog()


@router.post(
    "/v1/jobs",
    response_model=Job,
    openapi_extra=multipart_openapi(),
    responses={200: {"content": {"application/json": {"example": JOB_EXAMPLE}}}},
)
async def create_job(
    request: Request,
    pipeline: Pipeline = Depends(get_pipeline),
) -> Job:
    return await submit_upload(request, pipeline)


@router.post(
    "/v1/declare",
    openapi_extra=multipart_openapi(),
    responses={200: {"content": {"application/json": {"example": DECLARE_EXAMPLE}}}},
)
async def create_declaration(
    request: Request,
    pipeline: Pipeline = Depends(get_pipeline),
) -> dict:
    job = await submit_upload(request, pipeline, run=True)
    return to_dec_envelope(job)


@router.get("/v1/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, pipeline: Pipeline = Depends(get_pipeline)) -> Job:
    job = pipeline.jobs.get(job_id)
    if job is None:
        raise not_found("job not found")
    return job


@router.get("/v1/jobs", response_model=list[Job])
def list_jobs(pipeline: Pipeline = Depends(get_pipeline)) -> list[Job]:
    return pipeline.jobs.list()
