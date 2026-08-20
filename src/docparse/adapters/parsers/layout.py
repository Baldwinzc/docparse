"""从格子拆出版面：框表键值、冒号键值、表头行。

不做报关单字段映射，只把看得到的键值和对表留下来。
"""

from __future__ import annotations

import re

from docparse.domain.ir import Cell, KeyValue, Sheet, Table

_COLON = re.compile(r"^([^：:]{1,40}?)\s*[：:]\s*(.+)$")

_BOX_LABELS = frozenset(
    {
        "境内发货人",
        "出境关别",
        "出口日期",
        "进口日期",
        "申报日期",
        "备案号",
        "境外收货人",
        "运输方式",
        "运输工具名称及航次号",
        "提运单号",
        "生产销售单位",
        "监管方式",
        "征免性质",
        "许可证号",
        "合同协议号",
        "贸易国（地区）",
        "运抵国（地区）",
        "指运港",
        "离境口岸",
        "包装种类",
        "件数",
        "毛重（千克）",
        "净重（千克）",
        "成交方式",
        "运费",
        "保费",
        "杂费",
        "随附单证及编号",
        "标记唛码及备注",
        "预录入编号",
        "海关编号",
        "备注",
    }
)

_TABLE_HEADERS = (
    "项号",
    "商品编号",
    "商品名称",
    "规格型号",
    "申报要素",
    "品牌",
    "数量",
    "计价单位",
    "重量",
    "单价",
    "总价",
    "币制",
    "原产国",
    "最终目的国",
    "境内货源地",
    "征免",
)


def split_sheet(sheet: Sheet) -> Sheet:
    tables = _detect_tables(sheet.cells)
    occupied = _table_cells(tables, sheet.cells)
    key_values = _detect_key_values(sheet.cells, occupied)
    return sheet.model_copy(update={"tables": tables, "key_values": key_values})


def _detect_tables(cells: list[Cell]) -> list[Table]:
    by_row: dict[int, list[Cell]] = {}
    for cell in cells:
        if cell.row is None or not cell.value:
            continue
        by_row.setdefault(cell.row, []).append(cell)

    tables: list[Table] = []
    used_rows: set[int] = set()
    for row_idx in sorted(by_row):
        if row_idx in used_rows:
            continue
        row_cells = sorted(by_row[row_idx], key=lambda c: c.column or 0)
        if not _is_header_row(row_cells):
            continue
        headers = [c.value for c in row_cells]
        header_cells = [c.address for c in row_cells]
        columns = [c.column for c in row_cells]
        body: list[dict[str, str]] = []
        for body_row in range(row_idx + 1, row_idx + 200):
            if body_row not in by_row:
                break
            used_rows.add(body_row)
            values_by_col = {c.column: c.value for c in by_row[body_row]}
            record = {
                header: values_by_col.get(col, "")
                for header, col in zip(headers, columns, strict=True)
            }
            if not any(record.values()):
                break
            body.append(record)
        used_rows.add(row_idx)
        tables.append(
            Table(
                header_row=row_idx,
                headers=headers,
                header_cells=header_cells,
                rows=body,
            )
        )
    return tables


def _is_header_row(row_cells: list[Cell]) -> bool:
    if len(row_cells) < 3:
        return False
    hits = 0
    for cell in row_cells:
        text = cell.value
        if any(token in text for token in _TABLE_HEADERS):
            hits += 1
    return hits >= 2


def _table_cells(tables: list[Table], cells: list[Cell]) -> set[str]:
    if not tables:
        return set()
    table_rows: set[int] = set()
    for table in tables:
        table_rows.add(table.header_row)
        table_rows.update(range(table.header_row + 1, table.header_row + 1 + len(table.rows)))
    return {cell.address for cell in cells if cell.row in table_rows}


def _detect_key_values(cells: list[Cell], occupied: set[str]) -> list[KeyValue]:
    by_pos = {(c.row, c.column): c for c in cells if c.row is not None and c.column is not None}
    found: list[KeyValue] = []
    seen: set[tuple[str, str, str]] = set()

    def add(item: KeyValue) -> None:
        key = (item.key, item.value, item.strategy)
        if key in seen or not item.value:
            return
        seen.add(key)
        found.append(item)

    for cell in cells:
        if cell.address in occupied or not cell.value:
            continue
        same = _same_cell_colon(cell)
        if same:
            add(same)
            continue
        below = _value_below(cell, by_pos, occupied)
        if below:
            add(below)
            continue
        right = _value_right(cell, by_pos, occupied)
        if right:
            add(right)

    return found


def _same_cell_colon(cell: Cell) -> KeyValue | None:
    match = _COLON.match(cell.value)
    if not match:
        return None
    key, value = match.group(1).strip(), match.group(2).strip()
    if not key or not value:
        return None
    if any(token in key for token in _TABLE_HEADERS):
        return None
    return KeyValue(
        key=key,
        value=value,
        key_cell=cell.address,
        value_cell=cell.address,
        strategy="same_cell",
    )


def _looks_like_label(text: str) -> bool:
    stripped = text.strip()
    cleaned = stripped.rstrip("：:").strip()
    if not cleaned or len(cleaned) > 20:
        return False
    if cleaned in _BOX_LABELS:
        return True
    if stripped.endswith((":", "：")) and not re.fullmatch(r"[\d.\-]+", cleaned):
        return True
    return False


def _value_below(
    cell: Cell,
    by_pos: dict[tuple[int, int], Cell],
    occupied: set[str],
) -> KeyValue | None:
    if cell.row is None or cell.column is None:
        return None
    if not _looks_like_label(cell.value):
        return None
    below_row = _merge_bottom(cell) + 1
    other = by_pos.get((below_row, cell.column))
    if other is None or other.address in occupied or not other.value:
        return None
    if _looks_like_label(other.value) and not _COLON.match(other.value):
        return None
    key = cell.value.strip().rstrip("：:").strip()
    return KeyValue(
        key=key,
        value=other.value,
        key_cell=cell.address,
        value_cell=other.address,
        strategy="below",
    )


def _value_right(
    cell: Cell,
    by_pos: dict[tuple[int, int], Cell],
    occupied: set[str],
) -> KeyValue | None:
    if cell.row is None or cell.column is None:
        return None
    text = cell.value.strip()
    key = text.rstrip("：:").strip()
    if not (text.endswith((":", "：")) or key in _BOX_LABELS):
        return None
    right_col = _merge_right(cell) + 1
    other = by_pos.get((cell.row, right_col))
    if other is None or other.address in occupied or not other.value:
        return None
    if _looks_like_label(other.value):
        return None
    return KeyValue(
        key=key,
        value=other.value,
        key_cell=cell.address,
        value_cell=other.address,
        strategy="right",
    )


def _merge_bottom(cell: Cell) -> int:
    if cell.merge_range and ":" in cell.merge_range:
        end = cell.merge_range.split(":")[1]
        digits = "".join(ch for ch in end if ch.isdigit())
        if digits:
            return int(digits)
    return cell.row or 0


def _merge_right(cell: Cell) -> int:
    if cell.merge_range and ":" in cell.merge_range:
        end = cell.merge_range.split(":")[1]
        letters = "".join(ch for ch in end if ch.isalpha())
        if letters:
            col = 0
            for ch in letters.upper():
                col = col * 26 + (ord(ch) - 64)
            return col
    return cell.column or 0
