from threading import Lock

from docparse.domain.models import Job, JobStatus, ParseJobResult


class MemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()

    def create(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job.model_copy(deep=True)
            return self._jobs[job.id].model_copy(deep=True)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        result: ParseJobResult | None = None,
        error: str | None = None,
        source_file_id: str | None = None,
    ) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            if status is not None:
                job.status = status
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error
            if source_file_id is not None:
                job.source_file_id = source_file_id
            job.touch()
            return job.model_copy(deep=True)

    def list(self, limit: int = 50) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            return [job.model_copy(deep=True) for job in jobs[:limit]]
