from functools import lru_cache

from docparse.adapters.jobs.base import JobStore
from docparse.adapters.jobs.memory import MemoryJobStore
from docparse.config import Settings, get_settings


def get_job_store(settings: Settings | None = None) -> JobStore:
    cfg = settings or get_settings()
    return _job_store(cfg.job_store.lower(), cfg.database_url)


@lru_cache(maxsize=4)
def _job_store(name: str, database_url: str | None) -> JobStore:
    if name == "memory":
        return MemoryJobStore()
    if name == "postgres":
        from docparse.adapters.jobs.postgres import PostgresJobStore

        if not database_url:
            raise RuntimeError("DOCPARSE_JOB_STORE=postgres 需要 DOCPARSE_DATABASE_URL")
        return PostgresJobStore(database_url)
    raise ValueError(f"未知 job_store: {name}")
