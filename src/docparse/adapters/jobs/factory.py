from functools import lru_cache

from docparse.adapters.jobs.base import JobStore
from docparse.adapters.jobs.memory import MemoryJobStore
from docparse.config import Settings, get_settings


@lru_cache(maxsize=1)
def get_job_store(settings: Settings | None = None) -> JobStore:
    cfg = settings or get_settings()
    name = cfg.job_store.lower()
    if name == "memory":
        return MemoryJobStore()
    if name == "postgres":
        from docparse.adapters.jobs.postgres import PostgresJobStore

        if not cfg.database_url:
            raise RuntimeError("DOCPARSE_JOB_STORE=postgres 需要 DOCPARSE_DATABASE_URL")
        return PostgresJobStore(cfg.database_url)
    raise ValueError(f"未知 job_store: {cfg.job_store}")
