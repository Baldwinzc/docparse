from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from docparse.config import Settings, get_settings


class ArchiveError(ValueError):
    pass


@dataclass(frozen=True)
class UnpackedMember:
    archive_path: str
    data: bytes


def unpack_zip(data: bytes, settings: Settings | None = None) -> list[UnpackedMember]:
    cfg = settings or get_settings()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveError("不是有效的 zip") from exc

    members: list[UnpackedMember] = []
    total = 0
    for info in archive.infolist():
        path = info.filename.replace("\\", "/")
        if info.is_dir():
            continue
        _assert_safe_path(path)
        depth = path.count("/")
        if depth >= cfg.max_archive_depth:
            raise ArchiveError(f"压缩包层级超过限制: {path}")
        if info.file_size > cfg.max_uncompressed_mb * 1024 * 1024:
            raise ArchiveError(f"单文件解压后过大: {path}")
        ratio = info.file_size / max(info.compress_size, 1)
        if info.compress_size and ratio > cfg.max_archive_ratio:
            raise ArchiveError(f"压缩比异常，拒绝解压: {path}")
        payload = archive.read(info)
        total += len(payload)
        if total > cfg.max_uncompressed_mb * 1024 * 1024:
            raise ArchiveError("解压后总体积超过限制")
        if len(members) + 1 > cfg.max_archive_files:
            raise ArchiveError("压缩包内文件数超过限制")
        members.append(UnpackedMember(archive_path=path, data=payload))
    return members


def _assert_safe_path(path: str) -> None:
    if path.startswith("/") or path.startswith("\\"):
        raise ArchiveError(f"拒绝绝对路径: {path}")
    parts = [part for part in path.split("/") if part]
    if any(part == ".." for part in parts):
        raise ArchiveError(f"拒绝路径穿越: {path}")
