from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, Request

from docparse.api.caller import RESERVED_FORM_KEYS, collect_caller
from docparse.api.errors import bad_request, not_found
from docparse.api.schemas import JOB_EXAMPLE, multipart_openapi
from docparse.domain.models import Job
from docparse.pipeline.runner import Pipeline

REQUEST_ID_HEADER = "X-Request-Id"

router = APIRouter()


@lru_cache(maxsize=1)
def get_pipeline() -> Pipeline:
    return Pipeline()


def _request_id(request: Request) -> str:
    header = request.headers.get(REQUEST_ID_HEADER)
    if header:
        return header
    return getattr(request.state, "request_id", "")


def _truthy(value: object) -> bool:
    return str(value).strip().lower() not in {"0", "false", "no", ""}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise bad_request("missing file")
    data = await upload.read()
    filename = getattr(upload, "filename", None) or "upload.bin"
    fields = {
        key: str(value)
        for key, value in form.items()
        if key not in RESERVED_FORM_KEYS and not hasattr(value, "filename")
    }
    caller = collect_caller(fields)
    run_value = form.get("run", "true")
    try:
        job = pipeline.submit(
            filename,
            data,
            caller=caller,
            request_id=_request_id(request) or None,
        )
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    if _truthy(run_value):
        job = pipeline.run_job(job.id)
    return job


@router.get("/v1/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, pipeline: Pipeline = Depends(get_pipeline)) -> Job:
    job = pipeline.jobs.get(job_id)
    if job is None:
        raise not_found("job not found")
    return job


@router.get("/v1/jobs", response_model=list[Job])
def list_jobs(pipeline: Pipeline = Depends(get_pipeline)) -> list[Job]:
    return pipeline.jobs.list()
