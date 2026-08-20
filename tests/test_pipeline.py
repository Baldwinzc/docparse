import io
import zipfile

from docparse.adapters.files.memory import MemoryFileStore
from docparse.adapters.jobs.memory import MemoryJobStore
from docparse.config import Settings
from docparse.domain.models import JobStatus
from docparse.pipeline.runner import Pipeline


def _pipeline() -> Pipeline:
    settings = Settings(job_store="memory", file_store="memory", llm_api_key="")
    return Pipeline(
        settings=settings,
        jobs=MemoryJobStore(),
        files=MemoryFileStore(),
    )


def test_parse_text_declaration_number() -> None:
    content = "中华人民共和国海关出口货物报关单\n海关编号：ABCD1234567890\n"
    job = _pipeline().process("declaration.txt", content.encode("utf-8"))
    assert job.status in {JobStatus.SUCCEEDED, JobStatus.NEEDS_REVIEW}
    assert job.result is not None
    fields = job.result.package.fields
    field = next(item for item in fields if item.name == "entryId")
    assert field.value == "ABCD1234567890"
    assert field.evidence
    docs = job.result.package.documents
    assert docs[0].document_type == "customs_declaration"


def test_parse_zip_with_text_member() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("docs/报关单.txt", "报关单\n海关编号：XYZ9876543210\n")
    job = _pipeline().process("pack.zip", buffer.getvalue())
    assert job.result is not None
    fields = job.result.package.fields
    field = next(item for item in fields if item.name == "entryId")
    assert field.value == "XYZ9876543210"


def test_reject_zip_path_traversal() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../evil.txt", "nope")
    job = _pipeline().process("bad.zip", buffer.getvalue())
    assert job.status == JobStatus.FAILED
    assert job.error is not None
    assert "路径穿越" in job.error
