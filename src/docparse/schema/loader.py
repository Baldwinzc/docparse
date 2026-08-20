from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class FieldSpec(BaseModel):
    name: str
    display_name: str
    required: bool = False  # 本期不区分必填/选填，一律 False；后期再标
    value_type: str = "string"
    sources: list[str] = Field(default_factory=list)
    pattern: str | None = None
    anchors: list[str] = Field(default_factory=list)
    extractors: list[str] = Field(default_factory=lambda: ["rule"])
    group: str = "head"
    layout: str = "box_kv"
    parse: bool = True
    ignore: bool = False
    notes: str = ""
    code_table: str | None = None


class PortMapping(BaseModel):
    draft_label: str
    field: str
    code_table: str
    status: str
    notes: str = ""


class Schema(BaseModel):
    version: int = 2
    document_types: list[str] = Field(default_factory=list)
    goods_array: str = "tdecGoodsitemsVoArr"
    port_mapping: list[PortMapping] = Field(default_factory=list)
    caller_params: list[FieldSpec] = Field(default_factory=list)
    ignored: list[FieldSpec] = Field(default_factory=list)
    empty_arrays: list[FieldSpec] = Field(default_factory=list)
    head: list[FieldSpec] = Field(default_factory=list)
    goods: list[FieldSpec] = Field(default_factory=list)
    fields: list[FieldSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def fill_fields(self) -> "Schema":
        if not self.fields:
            self.fields = [*self.head, *self.goods]
        return self

    def field(self, name: str) -> FieldSpec | None:
        for collection in (
            self.fields,
            self.caller_params,
            self.ignored,
            self.empty_arrays,
        ):
            hit = next((item for item in collection if item.name == name), None)
            if hit is not None:
                return hit
        return None


@lru_cache(maxsize=1)
def load_schema() -> Schema:
    path = Path(__file__).with_name("fields.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Schema.model_validate(data)
