from dataclasses import dataclass, field

from docparse.adapters.files.base import FileStore
from docparse.adapters.jobs.base import JobStore
from docparse.adapters.llm.openai_compat import OpenAICompatClient
from docparse.config import Settings
from docparse.domain.ir import DocumentIR
from docparse.domain.models import FileRef, Job, PackageResult
from docparse.schema.loader import Schema


@dataclass
class PipelineContext:
    job: Job
    settings: Settings
    jobs: JobStore
    files: FileStore
    llm: OpenAICompatClient
    schema: Schema
    raw: FileRef
    members: list[FileRef] = field(default_factory=list)
    documents: list[DocumentIR] = field(default_factory=list)
    package: PackageResult = field(default_factory=PackageResult)
