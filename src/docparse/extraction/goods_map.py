"""商品表：TABLE → 货行。跨表只补空，不另开一张报关单。"""

from __future__ import annotations

import re
from copy import deepcopy

from docparse.domain.fields import ExtractedField, FieldStatus, GoodsItem
from docparse.domain.ir import DocumentIR, Evidence, Sheet, Table
from docparse.schema.loader import FieldSpec, Schema, load_schema

_SPACE = re.compile(r"\s+")
_LEADING_HS = re.compile(r"^(\d{8,10})")
_SKIP_CONSUME = frozenset({"exclude"})
_GOODS_LAYOUTS = frozenset({"table_col"})


def map_document_goods(
    document: DocumentIR,
    schema: Schema | None = None,
) -> list[GoodsItem]:
    """可消费 sheet 先各自映射，再选主表补空。辅助 / unknown 不读。"""
    schema = schema or load_schema()
    mapped: list[tuple[Sheet, list[GoodsItem], int]] = []
    for sheet in document.sheets:
        items = map_sheet_goods(sheet, document, schema)
        if not items:
            continue
        mapped.append((sheet, items, items[0].master_score))
    if not mapped:
        return []
    master_sheet, master_items, _ = max(
        mapped,
        key=lambda item: (item[2], item[0].consume == "primary"),
    )
    if master_items[0].master_score < schema.goods_master.min_score:
        return []
    merged = [deepcopy(item) for item in master_items]
    if schema.goods_master.merge_supplement:
        for sheet, items, _ in mapped:
            if sheet is master_sheet:
                continue
            _merge_sheet(merged, items, schema)
    return merged


def map_sheet_goods(
    sheet: Sheet,
    document: DocumentIR,
    schema: Schema | None = None,
) -> list[GoodsItem]:
    schema = schema or load_schema()
    if sheet.consume in _SKIP_CONSUME:
        return []
    table = _best_table(sheet, schema)
    if table is None:
        return []
    mapping = _column_map(table.headers, schema)
    if not mapping:
        return []
    score = _table_score(mapping, sheet.role, schema)
    items: list[GoodsItem] = []
    for row_index, row in enumerate(table.rows):
        item = _map_row(row, row_index, table, mapping, sheet, document, score)
        if item is not None:
            items.append(item)
    return items


def _best_table(sheet: Sheet, schema: Schema) -> Table | None:
    scored: list[tuple[int, Table]] = []
    for table in sheet.tables:
        mapping = _column_map(table.headers, schema)
        if not mapping:
            continue
        scored.append((_table_score(mapping, sheet.role, schema), table))
    if not scored:
        return None
    return max(scored, key=lambda item: item[0])[1]


def _table_score(mapping: dict[str, FieldSpec], role: str, schema: Schema) -> int:
    present = {spec.name for spec in mapping.values()}
    score = schema.goods_master.role_bonus.get(role, 0)
    for signal in schema.goods_master.signals:
        if signal.field in present:
            score += signal.weight
    return score


def _column_map(headers: list[str], schema: Schema) -> dict[str, FieldSpec]:
    header_best: dict[str, tuple[int, FieldSpec]] = {}
    for header in headers:
        if not header.strip():
            continue
        best: tuple[int, FieldSpec] | None = None
        for spec in schema.goods:
            if not _mappable(spec):
                continue
            for anchor in spec.anchors:
                if not _anchor_hits(anchor, header):
                    continue
                length = len(_fold_key(anchor))
                if best is None or length > best[0]:
                    best = (length, spec)
        if best is not None:
            header_best[header] = best
    field_best: dict[str, tuple[int, str, FieldSpec]] = {}
    for header, (length, spec) in header_best.items():
        current = field_best.get(spec.name)
        if current is None or length > current[0]:
            field_best[spec.name] = (length, header, spec)
    return {header: spec for _, header, spec in field_best.values()}


def _mappable(spec: FieldSpec) -> bool:
    if spec.parse is False or spec.ignore:
        return False
    if spec.layout not in _GOODS_LAYOUTS:
        return False
    if spec.goods_map == "skip":
        return False
    return bool(spec.anchors)


def _map_row(
    row: dict[str, str],
    row_index: int,
    table: Table,
    mapping: dict[str, FieldSpec],
    sheet: Sheet,
    document: DocumentIR,
    score: int,
) -> GoodsItem | None:
    fields: dict[str, ExtractedField] = {}
    for header, spec in mapping.items():
        raw = (row.get(header) or "").strip()
        if not raw:
            continue
        cell = _body_cell(table, header, row_index)
        field = _emit(spec, raw, header, cell, sheet, document)
        if field is not None:
            fields[spec.name] = field
    if not fields:
        return None
    if not any(name in fields for name in ("gno", "codeTs", "gname")):
        return None
    return GoodsItem(
        fields=fields,
        source_role=sheet.role,
        source_sheet=sheet.name,
        source_kind="primary",
        master_score=score,
        review_reasons=_row_reasons(fields),
    )


def _emit(
    spec: FieldSpec,
    raw: str,
    header: str,
    cell: str | None,
    sheet: Sheet,
    document: DocumentIR,
) -> ExtractedField | None:
    value = raw
    status = FieldStatus.ACCEPTED
    if spec.goods_map == "leading_hs":
        match = _LEADING_HS.match(raw)
        if match:
            value = match.group(1)
        else:
            status = FieldStatus.NEEDS_REVIEW
    elif spec.goods_map == "raw_review":
        status = FieldStatus.NEEDS_REVIEW
    return ExtractedField(
        name=spec.name,
        display_name=spec.display_name,
        value=value,
        normalized_value=value.strip(),
        confidence=0.9,
        status=status,
        extraction_method="goods_map",
        source_document_id=document.document_id,
        evidence=[
            Evidence(
                document_id=document.document_id,
                file_id=document.file_id,
                filename=document.filename,
                cell=f"{sheet.name}!{cell}" if cell else sheet.name,
                quote=f"{sheet.name}!{header}"[:500],
            )
        ],
    )


def _merge_sheet(master_items: list[GoodsItem], others: list[GoodsItem], schema: Schema) -> None:
    for other in others:
        hit = _match_item(master_items, other, schema.goods_master.match_keys)
        if hit is None:
            if not _worth_supplement(other):
                continue
            extra = deepcopy(other)
            extra.source_kind = "supplement"
            extra.review_reasons = [*extra.review_reasons, "unmatched_supplement"]
            master_items.append(extra)
            continue
        for name, field in other.fields.items():
            if hit.value_of(name):
                continue
            hit.fields[name] = deepcopy(field)


def _match_item(
    masters: list[GoodsItem],
    other: GoodsItem,
    keys: list[str],
) -> GoodsItem | None:
    for key in keys:
        hits = _hits_on(masters, other, key)
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            refined = hits
            for extra in keys:
                if extra == key:
                    continue
                narrowed = _hits_on(refined, other, extra)
                if len(narrowed) == 1:
                    return narrowed[0]
                if len(narrowed) > 1:
                    refined = narrowed
    return None


def _hits_on(items: list[GoodsItem], other: GoodsItem, key: str) -> list[GoodsItem]:
    needle = _fold_key(other.value_of(key) or "")
    if not needle:
        return []
    return [item for item in items if _fold_key(item.value_of(key) or "") == needle]


def _worth_supplement(item: GoodsItem) -> bool:
    """对不上主表的行：有税号，或品名不是纯数字，才收成补充项。"""
    if item.value_of("codeTs"):
        return True
    name = item.value_of("gname") or ""
    return bool(name) and not name.isdigit()


def _row_reasons(fields: dict[str, ExtractedField]) -> list[str]:
    if "gmodel" in fields:
        return ["gmodel_raw"]
    return []


def _body_cell(table: Table, header: str, row_index: int) -> str | None:
    if header not in table.headers:
        return None
    index = table.headers.index(header)
    if index >= len(table.header_cells):
        return None
    column = "".join(char for char in table.header_cells[index] if char.isalpha())
    if not column or not table.header_rows:
        return None
    return f"{column}{table.header_rows[-1] + 1 + row_index}"


def _anchor_hits(anchor: str, header: str) -> bool:
    needle = _fold_key(anchor)
    text = _fold_key(header)
    if not needle or not text:
        return False
    if needle.isascii() and any(char.isalpha() for char in needle):
        pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return needle in text


def _fold_key(text: str) -> str:
    return _SPACE.sub(" ", text.strip()).casefold()
