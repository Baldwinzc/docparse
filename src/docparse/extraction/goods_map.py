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
            _merge_by_order(merged, items, schema)
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


def _merge_by_order(master_items: list[GoodsItem], others: list[GoodsItem], schema: Schema) -> None:
    """同序对齐。数量对得上才补空；对不上不加行。主表已有值不覆盖。"""
    for index, master in enumerate(master_items):
        if index >= len(others):
            break
        other = others[index]
        if not _qty_aligns(master, other, schema):
            continue
        skip = set(schema.goods_master.skip_fill)
        for name, field in other.fields.items():
            if name in skip or master.value_of(name):
                continue
            if not _fill_allowed(master, name, field, schema):
                continue
            master.fields[name] = deepcopy(field)


def _fill_allowed(master: GoodsItem, name: str, field: ExtractedField, schema: Schema) -> bool:
    """千克行数量格只收与净重一致的候选值：净重即数量，件数混进数量列会错。"""
    if name != "gqty" or not _is_weight_unit(master.value_of("gunit"), schema):
        return True
    net = _as_number(master.value_of("customNetWt"))
    candidate = _as_number(field.value)
    if net is None or candidate is None:
        return False
    return _close(net, candidate, schema)


def _qty_aligns(master: GoodsItem, other: GoodsItem, schema: Schema) -> bool:
    master_qty = _qty_of(master, schema)
    other_qty = _qty_of(other, schema)
    if master_qty is None or other_qty is None:
        return False
    return _close(master_qty, other_qty, schema)


def _close(left: float, right: float, schema: Schema) -> bool:
    policy = schema.goods_master
    delta = abs(left - right)
    scale = max(abs(left), abs(right), 1.0)
    return delta <= policy.qty_abs_tol or delta <= policy.qty_rel_tol * scale


def _qty_of(item: GoodsItem, schema: Schema | None = None) -> float | None:
    """千克：净重即数量，缺净重退总价/单价（单价是每千克价）。其它：gqty，否则总价/单价。毛重不参与。"""
    if _is_weight_unit(item.value_of("gunit"), schema):
        net = _as_number(item.value_of("customNetWt"))
        if net is not None:
            return net
        return _total_over_price(item)
    direct = _as_number(item.value_of("gqty"))
    if direct is not None:
        return direct
    return _total_over_price(item)


def _total_over_price(item: GoodsItem) -> float | None:
    total = _as_number(item.value_of("declTotal"))
    price = _as_number(item.value_of("declPrice"))
    if total is None or price is None or price == 0:
        return None
    return total / price


def _is_weight_unit(unit: str | None, schema: Schema | None) -> bool:
    text = _fold_key(unit or "")
    if not text:
        return False
    names = schema.goods_master.weight_units if schema is not None else []
    return any(_fold_key(name) == text for name in names)


def _as_number(text: str | None) -> float | None:
    if not text:
        return None
    compact = text.replace(",", "").strip()
    try:
        return float(compact)
    except ValueError:
        return None


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
