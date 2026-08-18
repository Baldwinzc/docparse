from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile

from docparse.config import get_settings
from docparse.domain.models import Job
from docparse.pipeline.runner import Pipeline


@lru_cache(maxsize=1)
def get_pipeline() -> Pipeline:
    return Pipeline()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/jobs", response_model=Job)
    async def create_job(
        file: UploadFile = File(...),
        run: bool = True,
        pipeline: Pipeline = Depends(get_pipeline),
    ) -> Job:
        data = await file.read()
        filename = file.filename or "upload.bin"
        try:
            job = pipeline.submit(filename, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if run:
            job = pipeline.run_job(job.id)
        return job

    @app.get("/v1/jobs/{job_id}", response_model=Job)
    def get_job(job_id: str, pipeline: Pipeline = Depends(get_pipeline)) -> Job:
        job = pipeline.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.get("/v1/jobs", response_model=list[Job])
    def list_jobs(pipeline: Pipeline = Depends(get_pipeline)) -> list[Job]:
        return pipeline.jobs.list()

    return app


app = create_app()
