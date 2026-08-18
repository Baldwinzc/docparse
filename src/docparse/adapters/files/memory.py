from threading import Lock

from docparse.domain.models import FileKind, FileRef


class MemoryFileStore:
    def __init__(self) -> None:
        self._meta: dict[str, FileRef] = {}
        self._bytes: dict[str, bytes] = {}
        self._lock = Lock()

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
        ref = FileRef(
            job_id=job_id,
            filename=filename,
            content_type=content_type,
            kind=FileKind(kind),
            uri=f"memory://{job_id}/{filename}",
            byte_size=len(data),
            parent_id=parent_id,
            archive_path=archive_path,
        )
        ref.uri = f"memory://{job_id}/{ref.id}/{filename}"
        with self._lock:
            self._meta[ref.id] = ref
            self._bytes[ref.id] = data
        return ref.model_copy(deep=True)

    def get(self, file_id: str) -> bytes:
        with self._lock:
            return self._bytes[file_id]

    def stat(self, file_id: str) -> FileRef:
        with self._lock:
            return self._meta[file_id].model_copy(deep=True)

    def exists(self, file_id: str) -> bool:
        with self._lock:
            return file_id in self._bytes
