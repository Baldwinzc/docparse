from typing import Protocol

from docparse.domain.models import FileRef


class FileStore(Protocol):
    """原始文件与派生文件存储。当前 memory，后期 s3/minio。"""

    def put(
        self,
        data: bytes,
        *,
        job_id: str,
        filename: str,
        content_type: str = "application/octet-stream",
        kind: str = "raw",
        parent_id: str | None = None,
        archive_path: str | None = None,
    ) -> FileRef: ...

    def get(self, file_id: str) -> bytes: ...

    def stat(self, file_id: str) -> FileRef: ...

    def exists(self, file_id: str) -> bool: ...
