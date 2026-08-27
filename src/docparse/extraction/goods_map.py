"""商品表：TABLE → 货行。跨表只补空，不另开一张报关单。"""

from __future__ import annotations

import re
from copy import deepcopy

from docparse.domain.fields import ExtractedField, FieldStatus, GoodsItem
from docparse.domain.ir import DocumentIR, Evidence, Sheet, Table
from docparse.schema.loader import FieldSpec, Schema, load_schema
from docparse.schema.textnorm import fold_key, fold_spaced

_LEADING_HS = re.compile(r"^(\d{8,10})")
# 数量+单位粘连值（#84 标准报关单「数量及单位」复合列）：'48千克' / '240盒'。
_QTY_UNIT = re.compile(r"^(\d[\d,]*(?:\.\d+)?)\s*([^\d\s]{1,4})$")
# 规格形状（#84）：全角 ｜／％ 归一后含 | 或 % 即规格行；纯文字名称换行不算。
_SPEC_SHAPE = re.compile(r"[|%]")
_WIDTH_FOLD = str.maketrans("｜％", "|%")
# 境内目的地前缀双码（#84）：'（44536／440308）深圳盐田综合保税区'。
# 两码都非空才拆；当纳利 '(44199/)东莞/' 第二码空，保持原值。
_DISTRICT_CODES = re.compile(r"^[（(]\s*(\d{4,6})\s*[／/]\s*(\d{4,6})\s*[)）]")
_SKIP_CONSUME = frozenset({"exclude"})
_GOODS_LAYOUTS = frozenset({"table_col"})
# PDF 伪 sheet 名是页号（#62 reconstruct）。xlsx 草单名不是数字，不接续。
_PAGE_SHEET_NAME = re.compile(r"^(sheet\s*\d+|\d+)$", re.IGNORECASE)


def map_document_goods(
    document: DocumentIR,
    schema: Schema | None = None,
) -> list[GoodsItem]:
    """可消费 sheet 先各自映射，再选主表补空。辅助 / unknown 不读。"""
    schema = schema or load_schema()
    mapped: list[tuple[Sheet, list[GoodsItem], int]] = []
    for sheet in document.sheets:
        items = _map_sheet_goods(sheet, document, schema)
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
    same_role = [
        (sheet, items) for sheet, items, _ in mapped if sheet.role == master_sheet.role
    ]
    concat_pages = schema.goods_master.concat_same_role and _concat_page_sheets(same_role)
    if concat_pages:
        # PDF 草单跨页：页号伪 sheet、项号 1–10 / 11–19 按文档顺序拼一张。
        # xlsx 两张具名 draft（进料加工 + Sheet1）不走这里，仍只取主表。
        merged = [deepcopy(item) for _, items in same_role for item in items]
    else:
        merged = [deepcopy(item) for item in master_items]
    if schema.goods_master.merge_supplement:
        for sheet, items, _ in mapped:
            if sheet is master_sheet:
                continue
            if concat_pages and sheet.role == master_sheet.role:
                continue
            _merge_by_order(merged, items, schema)
    for item in merged:
        _prefer_net_as_qty(item, schema)
    return merged


def _is_page_sheet(sheet: Sheet) -> bool:
    return bool(_PAGE_SHEET_NAME.match(sheet.name.strip()))


def _concat_page_sheets(same_role: list[tuple[Sheet, list[GoodsItem]]]) -> bool:
    """同角色 ≥2 张且全是页号名 → 跨页接续。具名 xlsx draft 不接。"""
    return len(same_role) > 1 and all(_is_page_sheet(sheet) for sheet, _ in same_role)


def map_sheet_goods(
    sheet: Sheet,
    document: DocumentIR,
    schema: Schema | None = None,
) -> list[GoodsItem]:
    schema = schema or load_schema()
    items = _map_sheet_goods(sheet, document, schema)
    for item in items:
        _prefer_net_as_qty(item, schema)
    return items


def _map_sheet_goods(
    sheet: Sheet,
    document: DocumentIR,
    schema: Schema,
) -> list[GoodsItem]:
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
            # 无身份列但有商品值（#84：标准报关单规格单行的 item，行C 只剩
            # 成交数量/币制）。有项号列（海关货表）才并上一件；箱单 / 发票
            # 无项号列，无身份行照旧丢弃。
            identityless = _map_row(
                row, row_index, table, mapping, sheet, document, score,
                require_identity=False,
            )
            if (
                identityless is not None
                and items
                and _is_continuation(identityless, items[-1], mapping)
                and _has_value_fields(identityless)
            ):
                _merge_continuation(items[-1], identityless)
            continue
        if _is_continuation(item, items[-1] if items else None, mapping):
            if not items:
                continue
            _merge_continuation(items[-1], item)
            continue
        items.append(item)
    for item in items:
        _postprocess_item(item, schema)
    return items


_VALUE_FIELDS = frozenset(
    {
        "gqty",
        "gunit",
        "qty1",
        "unit1",
        "declPrice",
        "declTotal",
        "tradeCurr",
        "customNetWt",
        "customGrossWet",
    }
)


def _has_value_fields(item: GoodsItem) -> bool:
    return any(name in item.fields for name in _VALUE_FIELDS)


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
    require_identity: bool = True,
) -> GoodsItem | None:
    fields: dict[str, ExtractedField] = {}
    for header, spec in mapping.items():
        raw = (row.get(header) or "").strip()
        if not raw:
            continue
        cell = _body_cell(table, header, row_index)
        for field in _emit(spec, raw, header, cell, sheet, document):
            if field is not None and field.name not in fields:
                fields[field.name] = field
    if not fields:
        return None
    # 续行常只有 gname（申报要素落在品名列）；无身份列的行仍丢。
    if require_identity and not any(
        name in fields for name in ("gno", "codeTs", "gname")
    ):
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
) -> list[ExtractedField]:
    value = raw
    status = FieldStatus.ACCEPTED
    remainder = ""
    if spec.goods_map == "leading_hs":
        match = _LEADING_HS.match(raw)
        if match:
            value = match.group(1)
            remainder = raw[match.end() :].strip()
        else:
            status = FieldStatus.NEEDS_REVIEW
    elif spec.goods_map == "raw_review":
        status = FieldStatus.NEEDS_REVIEW
    fields = [_accepted(spec, value, header, cell, sheet, document, status=status)]
    # HS+品名粘连（#84）：编号列拆出 HS 后余文非空 → 发射到 split_target
    # （同 head_map trailing_code 机制）。余文空 / 无目标只出本字段。
    if remainder and spec.split_target:
        target = _spec_target(spec)
        if target is not None:
            fields.append(
                _accepted(target, remainder, header, cell, sheet, document)
            )
    return fields


def _spec_target(spec: FieldSpec) -> FieldSpec | None:
    """split_target 指向的字段目录项（#84）。无目标返回 None。"""
    if not spec.split_target:
        return None
    return load_schema().field(spec.split_target)


def _accepted(
    spec: FieldSpec,
    value: str,
    header: str,
    cell: str | None,
    sheet: Sheet,
    document: DocumentIR,
    status: FieldStatus = FieldStatus.ACCEPTED,
) -> ExtractedField:
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


def _postprocess_item(item: GoodsItem, schema: Schema) -> None:
    """续行合并后的逐项整形（#84）：粘连拆分、复合数量拆分、目的地双码。"""
    _split_joined_name(item, schema)
    _split_stacked_qty(item, schema)
    _split_district_codes(item, schema)


def _split_joined_name(item: GoodsItem, schema: Schema) -> None:
    """HS+品名粘连落在品名列（列归属漂移）：codeTs 空且品名以 HS 开头 → 拆。"""
    if _usable_hs(item.value_of("codeTs")):
        return
    gname = item.fields.get("gname")
    raw = (gname.value if gname else "") or ""
    match = _LEADING_HS.match(raw.strip())
    if match is None:
        return
    remainder = raw.strip()[match.end() :].strip()
    if not remainder:
        return
    code_spec = schema.field("codeTs")
    if code_spec is None:
        return
    gname.value = remainder
    gname.normalized_value = remainder
    item.fields["codeTs"] = _retarget(gname, "codeTs", code_spec.display_name)
    item.fields["codeTs"].value = match.group(1)
    item.fields["codeTs"].normalized_value = match.group(1)


def _split_stacked_qty(item: GoodsItem, schema: Schema) -> None:
    """「数量及单位」复合列（#84）：法定数量（行A）+成交数量（行C）拆开。

    形状闸：gqty 值带单位后缀、gunit 值是「数字+单位」——当纳利（#68）
    是「裸数字+纯单位」堆叠，形状不符不动。重量单位方是法定数量
    （qty1/unit1，unit1 千克时同值补 customNetWt），另一方是成交数量。
    """
    qty_field = item.fields.get("gqty")
    unit_field = item.fields.get("gunit")
    qty_match = _QTY_UNIT.match((qty_field.value if qty_field else "") or "")
    unit_match = _QTY_UNIT.match((unit_field.value if unit_field else "") or "")
    if qty_field is None or qty_match is None or unit_field is None or unit_match is None:
        return
    statutory, deal = qty_match, unit_match
    statutory_is_weight = _is_weight_unit(statutory.group(2), schema)
    deal_is_weight = _is_weight_unit(deal.group(2), schema)
    if deal_is_weight and not statutory_is_weight:
        statutory, deal = deal, statutory
    # 拆分后法定侧是否重量单位（两码都重量 / 唯一重量码都在法定侧）。
    statutory_weight = _is_weight_unit(statutory.group(2), schema)
    qty1_spec = schema.field("qty1")
    unit1_spec = schema.field("unit1")
    net_spec = schema.field("customNetWt")
    if qty1_spec is not None:
        item.fields["qty1"] = _retarget(qty_field, "qty1", qty1_spec.display_name)
        item.fields["qty1"].value = statutory.group(1)
        item.fields["qty1"].normalized_value = statutory.group(1)
    if unit1_spec is not None:
        item.fields["unit1"] = _retarget(qty_field, "unit1", unit1_spec.display_name)
        item.fields["unit1"].value = statutory.group(2)
        item.fields["unit1"].normalized_value = statutory.group(2)
    if (
        net_spec is not None
        and statutory_weight
        and not (item.value_of("customNetWt") or "").strip()
    ):
        item.fields["customNetWt"] = _retarget(
            qty_field, "customNetWt", net_spec.display_name
        )
        item.fields["customNetWt"].value = statutory.group(1)
        item.fields["customNetWt"].normalized_value = statutory.group(1)
    qty_field.value = deal.group(1)
    qty_field.normalized_value = deal.group(1)
    unit_field.value = deal.group(2)
    unit_field.normalized_value = deal.group(2)


def _split_district_codes(item: GoodsItem, schema: Schema) -> None:
    """境内目的地前缀双码（#84）：'（44536／440308）地名' → districtCode + ciqDestCode。

    两码都非空才拆；单码前缀（当纳利 '(44199/)东莞/'）保持原值。
    """
    district = item.fields.get("districtCode")
    raw = (district.value if district else "") or ""
    match = _DISTRICT_CODES.match(raw.strip())
    if district is None or match is None:
        return
    ciq_spec = schema.field("ciqDestCode")
    if ciq_spec is None:
        return
    district.value = match.group(1)
    district.normalized_value = match.group(1)
    item.fields["ciqDestCode"] = _retarget(district, "ciqDestCode", ciq_spec.display_name)
    item.fields["ciqDestCode"].value = match.group(2)
    item.fields["ciqDestCode"].normalized_value = match.group(2)


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
    """已占字段上的续行值：品名列续行并 gmodel；叠列数字补总价、非数字补币制/单位。"""
    for field in leftovers:
        text = (field.value or "").strip()
        if not text:
            continue
        if field.name == "gname" and _spec_like(text, master.value_of("gmodel")):
            # 规格续行（#84）：行B/行C 的规格文本并进 gmodel；硬换行无缝拼接
            # （'白砂'+'糖17％'='白砂糖17％'）。形状看归一化文本（全角 ｜ 算）。
            existing = master.value_of("gmodel") or ""
            merged = _retarget(field, "gmodel", "规格型号")
            merged.value = existing + text
            merged.normalized_value = existing + text
            master.fields["gmodel"] = merged
            continue
        if field.name == "declPrice":
            if _as_number(text) is not None and not master.value_of("declTotal"):
                master.fields["declTotal"] = _retarget(field, "declTotal", "申报总价")
            elif _as_number(text) is None and not master.value_of("tradeCurr"):
                master.fields["tradeCurr"] = _retarget(field, "tradeCurr", "币制")
        elif field.name == "gqty" and _as_number(text) is None and not master.value_of("gunit"):
            master.fields["gunit"] = _retarget(field, "gunit", "成交单位")


def _spec_like(text: str, existing_gmodel: str | None) -> bool:
    """规格形状：归一化（｜→|、％→%）后含 | 或 %；或 gmodel 已有值（续行拼接）。"""
    if (existing_gmodel or "").strip():
        return True
    return _SPEC_SHAPE.search(text.translate(_WIDTH_FOLD)) is not None


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


def _prefer_net_as_qty(item: GoodsItem, schema: Schema) -> None:
    """千克行同时有数量和净重时，成交数量取净重。件数列（数量PCS）不进 gqty。

    已与净重一致则不改证据。没有数量列不编；没有净重则保持原 gqty
    （当纳利：数量列本身就是千克）。
    """
    if not _is_weight_unit(item.value_of("gunit"), schema):
        return
    if item.value_of("gqty") is None:
        return
    net_field = item.fields.get("customNetWt")
    net = _as_number(item.value_of("customNetWt"))
    if net_field is None or net is None:
        return
    current = _as_number(item.value_of("gqty"))
    if current is not None and _close(net, current, schema):
        return
    item.fields["gqty"] = _retarget(net_field, "gqty", "成交数量")


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
