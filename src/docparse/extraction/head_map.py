"""单 sheet：版面 KV / 平表恒定列 → 表头字段。不合并多 sheet，不转 code，不填 agent*。"""

from __future__ import annotations

import re

from docparse.domain.fields import ExtractedField, FieldStatus
from docparse.domain.ir import DocumentIR, Evidence, KeyValue, Sheet, Table
from docparse.extraction.goods_map import best_goods_table
from docparse.schema.loader import FieldSpec, Schema, load_schema, load_sheet_roles
from docparse.schema.textnorm import fold_key

_TRAILING_CUSTOMS_CODE = re.compile(r"^(.*?)([A-Za-z0-9]{10})$")
# 纯代码值路由（#66）：整体是海关码 / 信用代码（可带括号壳）时不当名称。
_CUSTOMS_CODE = re.compile(r"^[A-Z0-9]{10}$")
_CREDIT_CODE = re.compile(r"^[A-Z0-9]{18}$")
_CODE_SHELL = re.compile(r"^[（(]\s*([A-Za-z0-9]+)\s*[)）]$")
# 键内代码路由（#82）：标签尾部的（10 位海关码 / 18 位信用代码）。
_KEY_TRAILING_CODE = re.compile(r"[（(]\s*([A-Za-z0-9]{10}|[A-Za-z0-9]{18})\s*[)）]\Z")
_SKIP_CONSUME = frozenset({"exclude"})
_HEAD_LAYOUTS = frozenset({"box_kv"})
_CALLER_PREFIX = "agent"
_COLUMN_STRATEGY = "column"
# 恒定列判定（#67）：非空值集合无冲突（只一个值）即恒定。合计列常只填
# 首行（通达2 总件数=272 只在第一行），照样恒定；每行变化的行级列
# （件数 / 净重 / 毛重）值集合 >1，天然被拦。
_CONSTANT_MAX_VALUES = 1
_SINGLE_ROW_ERROR = "single_row_column"


def map_document_head(
    document: DocumentIR,
    schema: Schema | None = None,
) -> list[ExtractedField]:
    """对文档里每张可消费 sheet 各映射一次，结果并排，不覆盖。"""
    schema = schema or load_schema()
    fields: list[ExtractedField] = []
    for sheet in document.sheets:
        fields.extend(map_sheet_head(sheet, document, schema))
    return fields


def map_sheet_head(
    sheet: Sheet,
    document: DocumentIR,
    schema: Schema | None = None,
) -> list[ExtractedField]:
    schema = schema or load_schema()
    if sheet.consume in _SKIP_CONSUME:
        return []
    index = _anchor_index(schema)
    found: dict[str, ExtractedField] = {}
    for pair in sheet.key_values:
        if not pair.value.strip():
            continue
        specs = index.get(fold_key(pair.key), [])
        for spec in specs:
            if spec.name in found:
                continue
            for field in _emit(spec, pair, sheet, document, schema):
                if field.name not in found:
                    found[field.name] = field
    if _columns_enabled(sheet):
        _head_from_columns(sheet, document, schema, index, found)
    return list(found.values())


def _columns_enabled(sheet: Sheet) -> bool:
    """表列路径只对显式声明 head_from_columns 的角色开（#67 默认仅平表）。

    框表 sheet 不走，防商品表常量列误伤表头 KV。
    """
    role = load_sheet_roles().role(sheet.role)
    return role is not None and role.head_from_columns


def _head_from_columns(
    sheet: Sheet,
    document: DocumentIR,
    schema: Schema,
    index: dict[str, list[FieldSpec]],
    found: dict[str, ExtractedField],
) -> None:
    """平表恒定列 → 表头字段（#67）。

    恒定 = 该列非空值集合无冲突（合计列只填首行也算）。每行变化的列
    （件数 / 净重 / 毛重）是行级信息，不出表头。整表只有一行数据时
    恒定性无法佐证，取值但标 needs_review。
    """
    table = best_goods_table(sheet, schema)
    if table is None:
        return
    single_row = len(table.rows) == 1
    for column, header in enumerate(table.headers):
        if not header.strip():
            continue
        values = _column_values(table, column)
        if not values:
            continue
        unique = {text for text, _ in values}
        if len(unique) > _CONSTANT_MAX_VALUES:
            continue
        value, first_row = values[0]
        pair = _column_pair(table, column, header, value, first_row)
        for spec in index.get(fold_key(header), []):
            if spec.name in found:
                continue
            for field in _emit(spec, pair, sheet, document, schema):
                if field.name not in found:
                    if single_row:
                        field.status = FieldStatus.NEEDS_REVIEW
                        field.validation_errors = [
                            *field.validation_errors,
                            _SINGLE_ROW_ERROR,
                        ]
                    found[field.name] = field


def _column_values(table: Table, column: int) -> list[tuple[str, int]]:
    """该列的非空值及所在数据行序，按行序。"""
    header = table.headers[column]
    values: list[tuple[str, int]] = []
    for row_index, row in enumerate(table.rows):
        text = (row.get(header) or "").strip()
        if text:
            values.append((text, row_index))
    return values


def _column_pair(table: Table, column: int, header: str, value: str, row: int) -> KeyValue:
    """把「表头格 + 首个值格」包成 KeyValue，复用 KV 发射（拆码 / 纯码路由同路径）。"""
    return KeyValue(
        key=header,
        value=value,
        key_cell=table.header_cells[column] if column < len(table.header_cells) else header,
        value_cell=_column_cell(table, column, row) or header,
        strategy=_COLUMN_STRATEGY,
    )


def _column_cell(table: Table, column: int, row_index: int) -> str | None:
    if column >= len(table.header_cells):
        return None
    letters = "".join(char for char in table.header_cells[column] if char.isalpha())
    if not letters or not table.header_rows:
        return None
    return f"{letters}{table.header_rows[-1] + 1 + row_index}"


def _anchor_index(schema: Schema) -> dict[str, list[FieldSpec]]:
    index: dict[str, list[FieldSpec]] = {}
    for spec in schema.head:
        if not _mappable(spec):
            continue
        for anchor in spec.anchors:
            index.setdefault(fold_key(anchor), []).append(spec)
    return index


def _mappable(spec: FieldSpec) -> bool:
    if spec.parse is False or spec.ignore:
        return False
    if spec.layout not in _HEAD_LAYOUTS:
        return False
    if spec.head_map == "skip":
        return False
    if spec.name.lower().startswith(_CALLER_PREFIX):
        return False
    return bool(spec.anchors)


def _emit(
    spec: FieldSpec,
    pair: KeyValue,
    sheet: Sheet,
    document: DocumentIR,
    schema: Schema,
) -> list[ExtractedField]:
    raw = pair.value.strip()
    if spec.head_map == "trailing_code":
        routed = _route_code_value(spec, raw, pair, sheet, document, schema)
        if routed is not None:
            return _with_key_codes(spec, routed, pair, sheet, document, schema)
        name, code = _split_trailing_code(raw)
        fields = [_accepted(spec, name, pair, sheet, document)]
        target = schema.field(spec.split_target or "")
        if code and target is not None:
            fields.append(_accepted(target, code, pair, sheet, document))
        return _with_key_codes(spec, fields, pair, sheet, document, schema)
    return [_accepted(spec, raw, pair, sheet, document)]


def _with_key_codes(
    spec: FieldSpec,
    fields: list[ExtractedField],
    pair: KeyValue,
    sheet: Sheet,
    document: DocumentIR,
    schema: Schema,
) -> list[ExtractedField]:
    """键内代码路由（#82）：标签自带的（尾码）补进对应代码字段。

    进境备案清单把 18 位信用代码印在标签里：「境内收货人（91440300…）」。
    值侧已拆出同一目标的不重复写；证据仍指向标签格。
    """
    match = _KEY_TRAILING_CODE.search(pair.key.strip())
    if match is None:
        return fields
    code = match.group(1)
    target_name = spec.scc_target if len(code) == 18 else spec.split_target
    target = schema.field(target_name or "")
    if target is None or any(field.name == target.name for field in fields):
        return fields
    return [
        *fields,
        _accepted(target, code, pair, sheet, document, evidence_cell=pair.key_cell),
    ]


def _route_code_value(
    spec: FieldSpec,
    raw: str,
    pair: KeyValue,
    sheet: Sheet,
    document: DocumentIR,
    schema: Schema,
) -> list[ExtractedField] | None:
    """纯代码值路由：值整体是海关码 / 信用代码（可带括号壳）时不当名称。

    name 字段留空并标 needs_review，码写进对应的 *Code / *Scc 字段。
    """
    shell = _CODE_SHELL.fullmatch(raw)
    candidate = (shell.group(1) if shell else raw).replace(" ", "")
    if _CREDIT_CODE.fullmatch(candidate):
        fields = [_code_only_name(spec, pair, sheet, document)]
        target = schema.field(spec.scc_target or "")
        if spec.scc_target and target is not None:
            fields.append(_accepted(target, candidate, pair, sheet, document))
        return fields
    if _CUSTOMS_CODE.fullmatch(candidate):
        fields = [_code_only_name(spec, pair, sheet, document)]
        target = schema.field(spec.split_target or "")
        if spec.split_target and target is not None:
            fields.append(_accepted(target, candidate, pair, sheet, document))
        return fields
    return None


def _code_only_name(
    spec: FieldSpec,
    pair: KeyValue,
    sheet: Sheet,
    document: DocumentIR,
) -> ExtractedField:
    """名称格只来了一个码：名称留空待补，证据仍指向原格。"""
    field = _accepted(spec, "", pair, sheet, document)
    field.status = FieldStatus.NEEDS_REVIEW
    field.validation_errors = ["pure_code_value"]
    return field


def _split_trailing_code(value: str) -> tuple[str, str | None]:
    compact = value.replace(" ", "")
    match = _TRAILING_CUSTOMS_CODE.fullmatch(compact)
    if match is None or not match.group(1):
        return value, None
    return match.group(1), match.group(2)


def _accepted(
    spec: FieldSpec,
    value: str,
    pair: KeyValue,
    sheet: Sheet,
    document: DocumentIR,
    evidence_cell: str | None = None,
) -> ExtractedField:
    quote = f"{sheet.name}!{pair.key_cell}:{pair.key}"
    return ExtractedField(
        name=spec.name,
        display_name=spec.display_name,
        value=value,
        normalized_value=value.strip(),
        confidence=0.9,
        status=FieldStatus.ACCEPTED,
        extraction_method="head_map",
        source_document_id=document.document_id,
        evidence=[
            Evidence(
                document_id=document.document_id,
                file_id=document.file_id,
                filename=document.filename,
                cell=f"{sheet.name}!{evidence_cell or pair.value_cell}",
                quote=quote[:500],
            )
        ],
    )
