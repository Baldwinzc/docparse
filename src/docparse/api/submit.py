"""上传 form → pipeline。/v1/jobs 与 /v1/declare 共用，不复制解析。"""

from __future__ import annotations

from fastapi import Request

from docparse.api.caller import RESERVED_FORM_KEYS, collect_caller
from docparse.api.errors import bad_request
from docparse.domain.models import Job
from docparse.pipeline.runner import Pipeline

REQUEST_ID_HEADER = "X-Request-Id"


def request_id(request: Request) -> str:
    header = request.headers.get(REQUEST_ID_HEADER)
    if header:
        return header
    return getattr(request.state, "request_id", "")


def truthy(value: object) -> bool:
    return str(value).strip().lower() not in {"0", "false", "no", ""}


async def submit_upload(request: Request, pipeline: Pipeline, *, run: bool | None = None) -> Job:
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
    if run is None:
        run = truthy(form.get("run", "true"))
    try:
        job = pipeline.submit(
            filename,
            data,
            caller=caller,
            request_id=request_id(request) or None,
        )
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    if run:
        job = pipeline.run_job(job.id)
    return job
