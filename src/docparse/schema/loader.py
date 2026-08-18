from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class FieldSpec(BaseModel):
    name: str
    display_name: str
    required: bool = False
    value_type: str = "string"
    sources: list[str] = Field(default_factory=list)
    pattern: str | None = None
    anchors: list[str] = Field(default_factory=list)
    extractors: list[str] = Field(default_factory=lambda: ["rule"])


class Schema(BaseModel):
    version: int = 1
    document_types: list[str] = Field(default_factory=list)
    fields: list[FieldSpec] = Field(default_factory=list)

    def field(self, name: str) -> FieldSpec | None:
        return next((item for item in self.fields if item.name == name), None)


@lru_cache(maxsize=1)
def load_schema() -> Schema:
    path = Path(__file__).with_name("fields.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Schema.model_validate(data)
