import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


def _fold_label(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()


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


class VocabAlias(BaseModel):
    text: str
    source: str = ""


class VocabValue(BaseModel):
    """挂在词表 id 上的值域形状。无此字段 = 不过滤。"""

    type: str
    pattern: str | None = None

    @model_validator(mode="after")
    def check_type(self) -> "VocabValue":
        allowed = {"date", "datetime", "number", "text", "pattern"}
        if self.type not in allowed:
            raise ValueError(f"unknown value type: {self.type}")
        if self.type == "pattern":
            if not self.pattern:
                raise ValueError("pattern type requires pattern")
            re.compile(self.pattern)
        return self


class VocabGroup(BaseModel):
    id: str
    value: VocabValue | None = None
    aliases: list[VocabAlias] = Field(default_factory=list)


class LayoutVocab(BaseModel):
    version: int = 1
    box: list[VocabGroup] = Field(default_factory=list)
    kv: list[VocabGroup] = Field(default_factory=list)
    table: list[VocabGroup] = Field(default_factory=list)

    def box_labels(self) -> frozenset[str]:
        return frozenset(alias.text for group in self.box for alias in group.aliases)

    def kv_labels(self) -> frozenset[str]:
        return frozenset(alias.text for group in self.kv for alias in group.aliases)

    def table_tokens(self) -> tuple[str, ...]:
        seen: list[str] = []
        for group in self.table:
            for alias in group.aliases:
                if alias.text not in seen:
                    seen.append(alias.text)
        return tuple(seen)

    def group_for_key(self, text: str) -> VocabGroup | None:
        """规范化 key → box ∪ kv 的分组。0 或 >1 个 id 都算没对上。"""
        needle = _fold_label(text)
        if not needle:
            return None
        hits = [
            group
            for group in (*self.box, *self.kv)
            if any(_fold_label(alias.text) == needle for alias in group.aliases)
        ]
        ids = {group.id for group in hits}
        if len(ids) != 1:
            return None
        return hits[0]

    def value_for_key(self, text: str) -> VocabValue | None:
        group = self.group_for_key(text)
        if group is None:
            return None
        return group.value


_ROLE_IDS = frozenset({"draft", "packing", "invoice", "contract", "auxiliary", "unknown"})
_CONSUME_IDS = frozenset({"primary", "supplement", "exclude"})


class RoleSignal(BaseModel):
    text: str
    source: str = ""
    weight: int = 2
    match: str = "contains"

    @model_validator(mode="after")
    def check_match(self) -> "RoleSignal":
        if self.match not in {"contains", "exact"}:
            raise ValueError(f"unknown signal match: {self.match}")
        return self


class RoleSignals(BaseModel):
    titles: list[RoleSignal] = Field(default_factory=list)
    keys: list[RoleSignal] = Field(default_factory=list)
    headers: list[RoleSignal] = Field(default_factory=list)
    filename: list[RoleSignal] = Field(default_factory=list)


class SheetRole(BaseModel):
    id: str
    consume: str
    lookup_pairs: bool = False
    signals: RoleSignals = Field(default_factory=RoleSignals)

    @model_validator(mode="after")
    def check_ids(self) -> "SheetRole":
        if self.id not in _ROLE_IDS:
            raise ValueError(f"unknown sheet role: {self.id}")
        if self.consume not in _CONSUME_IDS:
            raise ValueError(f"unknown consume: {self.consume}")
        return self


class SheetRoles(BaseModel):
    """sheet 角色信号。新叫法加 YAML，不写公司分支。"""

    version: int = 1
    min_score: int = 3
    filename_weight: int = 1
    unknown_consume: str = "exclude"
    roles: list[SheetRole] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_unknown_consume(self) -> "SheetRoles":
        if self.unknown_consume not in _CONSUME_IDS:
            raise ValueError(f"unknown consume: {self.unknown_consume}")
        return self

    def role(self, role_id: str) -> SheetRole | None:
        return next((item for item in self.roles if item.id == role_id), None)


class CodeEntry(BaseModel):
    code: str
    name: str

    @model_validator(mode="after")
    def normalize(self) -> "CodeEntry":
        self.code = str(self.code).strip()
        self.name = self.name.strip()
        return self


class CodeTable(BaseModel):
    source_sheet: str = ""
    notes: str = ""
    entries: list[CodeEntry] = Field(default_factory=list)


class PendingTable(BaseModel):
    name: str
    used_by: list[str] = Field(default_factory=list)
    notes: str = ""


class CodeTables(BaseModel):
    """名称 ↔ code。默认精确匹配；未知名称返回 None，不瞎填。"""

    version: int = 1
    match: str = "exact"
    pending: list[PendingTable] = Field(default_factory=list)
    tables: dict[str, CodeTable] = Field(default_factory=dict)

    def _require_table(self, table: str) -> CodeTable:
        hit = self.tables.get(table)
        if hit is None:
            raise ValueError(f"unknown code table: {table}")
        return hit

    def lookup(self, table: str, name: str | None) -> str | None:
        """中文名称 → code。strip 后整词相等；0 或 >1 个命中都返回 None。"""
        entries = self._require_table(table).entries
        key = (name or "").strip()
        if not key:
            return None
        codes = [item.code for item in entries if item.name == key]
        if len(set(codes)) != 1:
            return None
        return codes[0]

    def reverse(self, table: str, code: str | None) -> str | None:
        """code → 中文名称。0 或 >1 个命中都返回 None。"""
        entries = self._require_table(table).entries
        key = str(code or "").strip()
        if not key:
            return None
        names = [item.name for item in entries if item.code == key]
        if len(set(names)) != 1:
            return None
        return names[0]


@lru_cache(maxsize=1)
def load_schema() -> Schema:
    path = Path(__file__).with_name("fields.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Schema.model_validate(data)


@lru_cache(maxsize=1)
def load_layout_vocab() -> LayoutVocab:
    path = Path(__file__).with_name("layout_vocab.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return LayoutVocab.model_validate(data)


@lru_cache(maxsize=1)
def load_sheet_roles() -> SheetRoles:
    path = Path(__file__).with_name("sheet_roles.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SheetRoles.model_validate(data)


@lru_cache(maxsize=1)
def load_code_tables() -> CodeTables:
    path = Path(__file__).with_name("code_tables.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return CodeTables.model_validate(data)
