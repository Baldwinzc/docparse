import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from docparse.schema.textnorm import fold_key


def _fold_label(text: str) -> str:
    # 键归一（#66）：去空白 + 全角括号统一 + 键尾剥码。「毛 重:」与「毛重」同键。
    return fold_key(text)


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
    # 单 sheet 表头映射（#17）。keep=原样；skip=本层不映射；
    # trailing_code=末尾海关代码拆给 split_target；
    # scc_target=值整体是 18 位信用代码时写入的字段（#66 纯代码值路由）。
    head_map: str = "keep"
    split_target: str | None = None
    scc_target: str | None = None
    # 商品列映射（#18）。keep=原样；skip=本层不映射；
    # leading_hs=取列值前缀税则号；raw_review=原文 + needs_review。
    goods_map: str = "keep"
    default: str | None = None

    @model_validator(mode="after")
    def check_maps(self) -> "FieldSpec":
        allowed_head = {"keep", "skip", "trailing_code"}
        if self.head_map not in allowed_head:
            raise ValueError(f"unknown head_map: {self.head_map}")
        if self.head_map == "trailing_code" and not self.split_target:
            raise ValueError(f"{self.name} trailing_code requires split_target")
        allowed_goods = {"keep", "skip", "leading_hs", "raw_review"}
        if self.goods_map not in allowed_goods:
            raise ValueError(f"unknown goods_map: {self.goods_map}")
        return self


class PortMapping(BaseModel):
    draft_label: str
    field: str
    code_table: str
    status: str
    notes: str = ""


class GoodsMasterSignal(BaseModel):
    field: str
    weight: int = 1


class GoodsMaster(BaseModel):
    """主货表计分。新信号加 YAML，不写公司分支。"""

    min_score: int = 1
    match_keys: list[str] = Field(default_factory=lambda: ["gno", "codeTs", "gname", "gqty"])
    role_bonus: dict[str, int] = Field(default_factory=dict)
    signals: list[GoodsMasterSignal] = Field(default_factory=list)
    merge_supplement: bool = True
    qty_rel_tol: float = 0.005
    qty_abs_tol: float = 0.05
    weight_units: list[str] = Field(default_factory=lambda: ["千克", "公斤", "kg", "KG"])
    skip_fill: list[str] = Field(default_factory=list)
    gated_fields: list[str] = Field(
        default_factory=lambda: ["gqty", "customNetWt", "declPrice", "declTotal", "gunit"]
    )


_FILL_MODES = frozenset({"overwrite", "fill", "ignore"})


class AssemblyWeight(BaseModel):
    """表头重量。净重视同重量，不等于毛重。"""

    net_as_weight: bool = True
    copy_net_to_gross: bool = False


class Assembly(BaseModel):
    """整单组装策略。按角色，不按公司。"""

    primary_role: str = "draft"
    role_priority: list[str] = Field(
        default_factory=lambda: ["draft", "packing", "invoice", "contract"]
    )
    fill: dict[str, str] = Field(default_factory=dict)
    reconcile: list[str] = Field(default_factory=lambda: ["packNo", "grossWt", "netWt"])
    customs_only: list[str] = Field(default_factory=list)
    defaults: dict[str, str] = Field(default_factory=dict)
    weight: AssemblyWeight = Field(default_factory=AssemblyWeight)
    invoice_vocab: str = "invoice_no"

    @model_validator(mode="after")
    def check_fill(self) -> "Assembly":
        for role, mode in self.fill.items():
            if mode not in _FILL_MODES:
                raise ValueError(f"unknown assembly fill: {role}={mode}")
        return self


class Schema(BaseModel):
    version: int = 2
    document_types: list[str] = Field(default_factory=list)
    goods_array: str = "tdecGoodsitemsVoArr"
    goods_master: GoodsMaster = Field(default_factory=GoodsMaster)
    assembly: Assembly = Field(default_factory=Assembly)
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


_ROLE_IDS = frozenset(
    {"draft", "declaration_list", "packing", "invoice", "contract", "auxiliary", "unknown"}
)
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

    def known_code(self, table: str, code: str | None) -> bool:
        """值本身是这张表的 code 吗（#66 反查兜底）。"""
        entries = self._require_table(table).entries
        key = str(code or "").strip()
        return bool(key) and any(item.code == key for item in entries)

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
