from pathlib import Path

import pytest

from docparse.adapters.files.memory import MemoryFileStore
from docparse.adapters.jobs.memory import MemoryJobStore
from docparse.config import Settings
from docparse.pipeline.runner import Pipeline

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def settings() -> Settings:
    return Settings(job_store="memory", file_store="memory", llm_api_key="")


@pytest.fixture
def pipeline(settings: Settings) -> Pipeline:
    return Pipeline(settings=settings, jobs=MemoryJobStore(), files=MemoryFileStore())
