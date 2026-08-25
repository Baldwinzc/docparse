"""商品表：TABLE → 货行。跨表只补空，不另开一张报关单。"""

from __future__ import annotations

import re
from copy import deepcopy

from docparse.domain.fields import ExtractedField, FieldStatus, GoodsItem
from docparse.domain.ir import DocumentIR, Evidence, Sheet, Table
from docparse.schema.loader import FieldSpec, Schema, load_schema
from docparse.schema.textnorm import fold_key, fold_spaced

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
    mapping = _column_map(table.headers, schema, table.rows)
    if not mapping:
        return []
    score = _table_score(mapping, sheet.role, schema)
    items: list[GoodsItem] = []
    for row_index, row in enumerate(table.rows):
        if _is_total_row(row, schema, sheet, table, row_index):
            continue
        item = _map_row(row, row_index, table, mapping, sheet, document, score)
        if item is None:
            continue
        if _is_continuation(item, items[-1] if items else None, mapping):
            if not items:
                continue
            _merge_continuation(items[-1], item)
            continue
        items.append(item)
    return items


def best_goods_table(sheet: Sheet, schema: Schema) -> Table | None:
    """该 sheet 的最佳商品表。head_map 表列路径（#67）复用同一张表。"""
    return _best_table(sheet, schema)


def _best_table(sheet: Sheet, schema: Schema) -> Table | None:
    scored: list[tuple[int, Table]] = []
    for table in sheet.tables:
        mapping = _column_map(table.headers, schema, table.rows)
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


def _column_map(
    headers: list[str],
    schema: Schema,
    rows: list[dict[str, str]] | None = None,
) -> dict[str, FieldSpec]:
    """列 → 字段。

    每列归属：按锚点在 fields.yaml 里的先后（先专后泛），再看锚点长度——
    与数据无关，恒定规则。同一字段多列命中时才看数据形状：
    常量列（>1 行且非空值全部相同，如通达2「总净重(千克)」全表合计）
    降级，让行级列（净重(千克)）赢；国光「总净重 NW」每行不同，不受影响。
    """
    constant = _constant_headers(headers, rows or [])
    header_best: dict[str, tuple[int, int, FieldSpec]] = {}
    for header in headers:
        if not header.strip():
            continue
        best: tuple[int, int, FieldSpec] | None = None
        for spec in schema.goods:
            if not _mappable(spec):
                continue
            for order, anchor in enumerate(spec.anchors):
                if not _anchor_hits(anchor, header):
                    continue
                rank = (-order, len(fold_key(anchor)))
                if best is None or rank > (best[0], best[1]):
                    best = (*rank, spec)
        if best is not None:
            header_best[header] = best
    field_best: dict[str, tuple[int, int, int, str, FieldSpec]] = {}
    for header, (order, length, spec) in header_best.items():
        current = field_best.get(spec.name)
        rank = (0 if header in constant else 1, order, length)
        if current is None or rank > (current[0], current[1], current[2]):
            field_best[spec.name] = (*rank, header, spec)
    return {header: spec for _, _, _, header, spec in field_best.values()}


def _constant_headers(headers: list[str], rows: list[dict[str, str]]) -> frozenset[str]:
    """非空值全部相同且行数 >1 的列是合计列。空值不参与判定。"""
    constant: set[str] = set()
    if len(rows) <= 1:
        return frozenset(constant)
    for header in headers:
        values = {(row.get(header) or "").strip() for row in rows}
        values.discard("")
        if len(values) == 1 and values:
            constant.add(header)
    return frozenset(constant)


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
    # 续行常只有 gname（申报要素落在品名列）；无身份列的行仍丢。
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


def _is_total_row(
    row: dict[str, str],
    schema: Schema,
    sheet: Sheet,
    table: Table,
    row_index: int,
) -> bool:
    """行首格或整行任一格命中合计词 → 整行丢弃。不并单、不成商品。

    映射列和物理行都扫：MXY 装箱单「合计」落在无表头的中间列，不进 row dict。
    """
    tokens = [_fold_token(token) for token in schema.goods_master.total_row_tokens]
    tokens = [token for token in tokens if token]
    if not tokens:
        return False
    texts = [str(value) for value in row.values()]
    excel_row = _excel_row(table, row_index)
    if excel_row is not None:
        texts.extend(cell.value for cell in sheet.cells if cell.row == excel_row)
    return any(_text_has_total(text, tokens) for text in texts)


def _excel_row(table: Table, row_index: int) -> int | None:
    if not table.header_rows:
        return None
    return table.header_rows[-1] + 1 + row_index


def _fold_token(text: str | None) -> str:
    return fold_key(text or "").rstrip("：:").strip()


def _text_has_total(text: str | None, tokens: list[str]) -> bool:
    folded = _fold_token(text)
    if not folded:
        return False
    for token in tokens:
        if not token:
            continue
        if token.isascii():
            pattern = r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])"
            if re.search(pattern, folded):
                return True
        elif token in folded:
            return True
    return False


def _is_continuation(
    item: GoodsItem,
    previous: GoodsItem | None,
    mapping: dict[str, FieldSpec],
) -> bool:
    """无可用税号，且项号空 / 0 / 与上一件相同 → 并入上一件。

    只对有项号列的海关货表生效。箱单 / 发票没有项号，相邻两行都是独立商品，
    不能因「无 gno」互并。无主行的续行也算续行，调用方丢弃。

    项号空 / 0 才是续行。字母项号（恒信箱单 D001）是身份，不并。
    """
    if not any(spec.name == "gno" for spec in mapping.values()):
        return False
    if _usable_hs(item.value_of("codeTs")):
        return False
    raw_gno = item.value_of("gno")
    if not raw_gno:
        return True
    gno = _item_no(raw_gno)
    if gno == 0:
        return True
    if previous is None or gno is None:
        return False
    prev = _item_no(previous.value_of("gno"))
    return prev is not None and gno == prev


def _usable_hs(text: str | None) -> bool:
    raw = (text or "").strip()
    return bool(raw) and _LEADING_HS.match(raw) is not None


def _item_no(text: str | None) -> int | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        number = float(raw.replace(",", ""))
    except ValueError:
        return None
    if not number.is_integer():
        return None
    return int(number)


def _merge_continuation(master: GoodsItem, other: GoodsItem) -> None:
    """同名字段主行空位补、已占用不覆盖；叠列溢出按形状改落到空字段。"""
    leftovers: list[ExtractedField] = []
    for name, field in other.fields.items():
        if not master.value_of(name):
            master.fields[name] = deepcopy(field)
        else:
            leftovers.append(field)
    _route_leftovers(master, leftovers)
    master.review_reasons = _row_reasons(master.fields)


def _route_leftovers(master: GoodsItem, leftovers: list[ExtractedField]) -> None:
    """已占字段上的续行值：申报要素形状补 gmodel；叠列数字补总价、非数字补币制/单位。"""
    for field in leftovers:
        text = (field.value or "").strip()
        if not text:
            continue
        if text.count("|") >= 2 and not master.value_of("gmodel"):
            master.fields["gmodel"] = _retarget(field, "gmodel", "规格型号")
            continue
        if field.name == "declPrice":
            if _as_number(text) is not None and not master.value_of("declTotal"):
                master.fields["declTotal"] = _retarget(field, "declTotal", "申报总价")
            elif _as_number(text) is None and not master.value_of("tradeCurr"):
                master.fields["tradeCurr"] = _retarget(field, "tradeCurr", "币制")
        elif field.name == "gqty" and _as_number(text) is None and not master.value_of("gunit"):
            master.fields["gunit"] = _retarget(field, "gunit", "成交单位")


def _retarget(field: ExtractedField, name: str, display_name: str) -> ExtractedField:
    routed = deepcopy(field)
    routed.name = name
    routed.display_name = display_name
    return routed


def _merge_by_order(master_items: list[GoodsItem], others: list[GoodsItem], schema: Schema) -> None:
    """同序对齐。计算链字段走数量闸，其余字段检测到即补。主表已有值不覆盖。"""
    skip = set(schema.goods_master.skip_fill)
    gated = set(schema.goods_master.gated_fields)
    for index, master in enumerate(master_items):
        if index >= len(others):
            break
        other = others[index]
        unit_aligns = _unit_aligns(master, other, schema)
        qty_aligns = unit_aligns and _qty_aligns(master, other, schema)
        for name, field in other.fields.items():
            if name in skip or master.value_of(name):
                continue
            if name in gated and not qty_aligns:
                continue
            if not _fill_allowed(master, name, field, schema):
                continue
            master.fields[name] = deepcopy(field)


def _unit_aligns(master: GoodsItem, other: GoodsItem, schema: Schema) -> bool:
    """单位语义对上才可能对数量：千克 vs 只，数量不可比。"""
    master_unit = (master.value_of("gunit") or "").strip()
    other_unit = (other.value_of("gunit") or "").strip()
    if not master_unit or not other_unit:
        return True
    return fold_key(master_unit) == fold_key(other_unit)


def _fill_allowed(master: GoodsItem, name: str, field: ExtractedField, schema: Schema) -> bool:
    """字段级闸：千克行数量格候选值须 ≈ 净重；毛重候选值须 ≥ 净重（占位 0 会被拦）。"""
    if name == "gqty" and _is_weight_unit(master.value_of("gunit"), schema):
        net = _as_number(master.value_of("customNetWt"))
        candidate = _as_number(field.value)
        if net is None or candidate is None:
            return False
        return _close(net, candidate, schema)
    if name == "customGrossWet":
        net = _as_number(master.value_of("customNetWt"))
        gross = _as_number(field.value)
        if net is None or gross is None:
            return True
        return gross >= net
    return True


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
    text = fold_key(unit or "")
    if not text:
        return False
    names = schema.goods_master.weight_units if schema is not None else []
    return any(fold_key(name) == text for name in names)


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
    needle = fold_spaced(anchor)
    text = fold_spaced(header)
    if not needle or not text:
        return False
    if needle.isascii() and any(char.isalpha() for char in needle):
        pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return fold_key(anchor) in fold_key(text)
