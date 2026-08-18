"""PostgreSQL JobStore 预留。

实现时建议表结构见 docs/persistence.md。
不要在本模块里偷偷改 pipeline 行为，只负责 Job 的读写。
"""

from docparse.domain.models import Job, JobStatus, ParseJobResult


class PostgresJobStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def create(self, job: Job) -> Job:
        raise NotImplementedError("PostgresJobStore 尚未实现，见 docs/persistence.md")

    def get(self, job_id: str) -> Job | None:
        raise NotImplementedError("PostgresJobStore 尚未实现，见 docs/persistence.md")

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        result: ParseJobResult | None = None,
        error: str | None = None,
        source_file_id: str | None = None,
    ) -> Job:
        raise NotImplementedError("PostgresJobStore 尚未实现，见 docs/persistence.md")

    def list(self, limit: int = 50) -> list[Job]:
        raise NotImplementedError("PostgresJobStore 尚未实现，见 docs/persistence.md")
