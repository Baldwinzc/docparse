"""单 sheet：版面 KV → 表头字段。不合并多 sheet，不转 code，不填 agent*。"""

from __future__ import annotations

import re

from docparse.domain.fields import ExtractedField, FieldStatus
from docparse.domain.ir import DocumentIR, Evidence, KeyValue, Sheet
from docparse.schema.loader import FieldSpec, Schema, load_schema
from docparse.schema.textnorm import fold_key

_TRAILING_CUSTOMS_CODE = re.compile(r"^(.*?)([A-Za-z0-9]{10})$")
# 纯代码值路由（#66）：整体是海关码 / 信用代码（可带括号壳）时不当名称。
_CUSTOMS_CODE = re.compile(r"^[A-Z0-9]{10}$")
_CREDIT_CODE = re.compile(r"^[A-Z0-9]{18}$")
_CODE_SHELL = re.compile(r"^[（(]\s*([A-Za-z0-9]+)\s*[)）]$")
_SKIP_CONSUME = frozenset({"exclude"})
_HEAD_LAYOUTS = frozenset({"box_kv"})
_CALLER_PREFIX = "agent"


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
    return list(found.values())


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
            return routed
        name, code = _split_trailing_code(raw)
        fields = [_accepted(spec, name, pair, sheet, document)]
        target = schema.field(spec.split_target or "")
        if code and target is not None:
            fields.append(_accepted(target, code, pair, sheet, document))
        return fields
    return [_accepted(spec, raw, pair, sheet, document)]


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
                cell=f"{sheet.name}!{pair.value_cell}",
                quote=quote[:500],
            )
        ],
    )
