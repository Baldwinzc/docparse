from functools import lru_cache

from docparse.adapters.files.base import FileStore
from docparse.adapters.files.memory import MemoryFileStore
from docparse.config import Settings, get_settings


@lru_cache(maxsize=1)
def get_file_store(settings: Settings | None = None) -> FileStore:
    cfg = settings or get_settings()
    name = cfg.file_store.lower()
    if name == "memory":
        return MemoryFileStore()
    if name == "s3":
        from docparse.adapters.files.s3 import S3FileStore

        if not cfg.s3_bucket:
            raise RuntimeError("DOCPARSE_FILE_STORE=s3 需要 DOCPARSE_S3_BUCKET")
        return S3FileStore(cfg.s3_bucket, cfg.s3_endpoint)
    raise ValueError(f"未知 file_store: {cfg.file_store}")
