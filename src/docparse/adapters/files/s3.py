"""对象存储预留。实现时只负责字节进出，路径约定见 docs/persistence.md。"""

from docparse.domain.models import FileRef


class S3FileStore:
    def __init__(self, bucket: str, endpoint: str | None = None) -> None:
        self.bucket = bucket
        self.endpoint = endpoint

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
    ) -> FileRef:
        raise NotImplementedError("S3FileStore 尚未实现，见 docs/persistence.md")

    def get(self, file_id: str) -> bytes:
        raise NotImplementedError("S3FileStore 尚未实现，见 docs/persistence.md")

    def stat(self, file_id: str) -> FileRef:
        raise NotImplementedError("S3FileStore 尚未实现，见 docs/persistence.md")

    def exists(self, file_id: str) -> bool:
        raise NotImplementedError("S3FileStore 尚未实现，见 docs/persistence.md")
