"""单 sheet：版面 KV → 表头字段。不合并多 sheet，不转 code，不填 agent*。"""

from __future__ import annotations

import re

from docparse.domain.fields import ExtractedField, FieldStatus
from docparse.domain.ir import DocumentIR, Evidence, KeyValue, Sheet
from docparse.schema.loader import FieldSpec, Schema, load_schema

_SPACE = re.compile(r"\s+")
_TRAILING_CUSTOMS_CODE = re.compile(r"^(.*?)([A-Za-z0-9]{10})$")
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
        specs = index.get(_fold_key(pair.key), [])
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
            index.setdefault(_fold_key(anchor), []).append(spec)
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
        name, code = _split_trailing_code(raw)
        fields = [_accepted(spec, name, pair, sheet, document)]
        target = schema.field(spec.split_target or "")
        if code and target is not None:
            fields.append(_accepted(target, code, pair, sheet, document))
        return fields
    return [_accepted(spec, raw, pair, sheet, document)]


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


def _fold_key(text: str) -> str:
    return _SPACE.sub(" ", text.strip()).casefold()
