from functools import lru_cache

from docparse.adapters.files.base import FileStore
from docparse.adapters.files.memory import MemoryFileStore
from docparse.config import Settings, get_settings


def get_file_store(settings: Settings | None = None) -> FileStore:
    cfg = settings or get_settings()
    return _file_store(cfg.file_store.lower(), cfg.s3_bucket, cfg.s3_endpoint)


@lru_cache(maxsize=4)
def _file_store(name: str, s3_bucket: str | None, s3_endpoint: str | None) -> FileStore:
    if name == "memory":
        return MemoryFileStore()
    if name == "s3":
        from docparse.adapters.files.s3 import S3FileStore

        if not s3_bucket:
            raise RuntimeError("DOCPARSE_FILE_STORE=s3 需要 DOCPARSE_S3_BUCKET")
        return S3FileStore(s3_bucket, s3_endpoint)
    raise ValueError(f"未知 file_store: {name}")
