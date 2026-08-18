from typing import Protocol

from docparse.domain.models import Job, JobStatus, ParseJobResult


class JobStore(Protocol):
    """任务持久化。当前 memory，后期 postgres 实现同一接口。"""

    def create(self, job: Job) -> Job: ...

    def get(self, job_id: str) -> Job | None: ...

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        result: ParseJobResult | None = None,
        error: str | None = None,
        source_file_id: str | None = None,
    ) -> Job: ...

    def list(self, limit: int = 50) -> list[Job]: ...
