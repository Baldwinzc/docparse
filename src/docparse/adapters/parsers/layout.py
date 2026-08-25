"""从格子拆出版面：框表键值、冒号键值、表头行。

不做报关单字段映射，只把看得到的键值和对表留下来。
"""

from __future__ import annotations

import re

from docparse.domain.ir import Cell, KeyValue, Sheet, Table
from docparse.schema.loader import VocabValue, load_layout_vocab

# 半角 / 全角 / 小冒号（U+FE55）/ 竖排冒号。不按客户码点特判。
_COLON_CHARS = ":：﹕︰"
_COLON_CLASS = re.escape(_COLON_CHARS)
_SPLIT_COLON = re.compile(rf"^(.{{1,40}}?)\s*[{_COLON_CLASS}]\s*(.+)$")
_TRAIL_COLON = re.compile(rf"[{_COLON_CLASS}]+$")
_DATETIME_FULL = re.compile(
    r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$"
)
_DATE_ONLY = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")
_DATETIME_LEFT = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]\d{1,2})?$")
_TIME_FULL = re.compile(r"^\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?$")
_NUMERIC = re.compile(r"^[\d.,]+$")
# 占位格：(  ) / （　） 视同空。占位后跟提示文字（「(  )跨境的才需要申报」）
# 也整体视同空——那是模板提示，不是填了的值。
_PLACEHOLDER = re.compile(r"^[\(（]\s*[\)）]")
# 右向跳空取值：标签与值之间允许的空列上限（#64）。间距更大改这里。
_RIGHT_SKIP_MAX = 2


def _is_placeholder(text: str) -> bool:
    return _PLACEHOLDER.match(text.strip()) is not None


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
        header_rows = [row_idx]
        extra_row = row_idx + 1
        extra_cells = sorted(by_row.get(extra_row, []), key=lambda c: c.column or 0)
        if extra_row not in used_rows and _is_translation_row(extra_cells):
            header_rows.append(extra_row)
            used_rows.add(extra_row)
        headers = _compose_headers(row_cells, extra_cells if len(header_rows) > 1 else [])
        header_cells = [c.address for c in row_cells]
        columns = [c.column for c in row_cells]
        body_start = header_rows[-1] + 1
        body: list[dict[str, str]] = []
        for body_row in range(body_start, body_start + 200):
            if body_row not in by_row:
                break
            used_rows.add(body_row)
            values_by_col = {c.column: c.value for c in by_row[body_row]}
            record = {
                header: _blank_if_placeholder(values_by_col.get(col, ""))
                for header, col in zip(headers, columns, strict=True)
            }
            if not any(record.values()):
                break
            body.append(record)
        used_rows.add(row_idx)
        tables.append(
            Table(
                header_row=row_idx,
                header_rows=header_rows,
                headers=headers,
                header_cells=header_cells,
                rows=body,
            )
        )
    return tables


def _compose_headers(row_cells: list[Cell], extra_cells: list[Cell]) -> list[str]:
    extra_by_col = {c.column: c.value for c in extra_cells}
    headers: list[str] = []
    for cell in row_cells:
        headers.append(_join_header(cell.value, extra_by_col.get(cell.column, "")))
    return headers


def _join_header(primary: str, extra: str) -> str:
    left = primary.strip()
    right = extra.strip()
    if not right or right == left:
        return left
    if left in right:
        return right
    if right in left:
        return left
    return f"{left} {right}"


def _table_tokens() -> tuple[str, ...]:
    return load_layout_vocab().table_tokens()


def _box_labels() -> frozenset[str]:
    return load_layout_vocab().box_labels()


def _kv_labels() -> frozenset[str]:
    return load_layout_vocab().kv_labels()


def _all_kv_keys() -> frozenset[str]:
    return _box_labels() | _kv_labels()


def _norm_label(text: str) -> str:
    # 词形归一去掉全部空白（#64）：标签里的换行/空格（「毛重\n（公斤）」「毛    重」）
    # 不该挡住词表匹配。锚点侧的全面归一（空白/尾码/繁体）在 #66。
    cleaned = re.sub(r"\s+", "", _label_text(text))
    return cleaned.casefold()


def _kv_norms() -> frozenset[str]:
    return frozenset(_norm_label(item) for item in _all_kv_keys())


def _is_known_key(text: str) -> bool:
    cleaned = _label_text(text)
    if cleaned in _all_kv_keys():
        return True
    return _norm_label(cleaned) in _kv_norms()


def _token_in_text(token: str, text: str) -> bool:
    if token.isascii() and any(ch.isalpha() for ch in token):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])"
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
    return token in text


def _label_text(text: str) -> str:
    return _TRAIL_COLON.sub("", text.strip()).strip()


def _ends_with_colon(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and stripped[-1] in _COLON_CHARS


def _blank_if_placeholder(text: str) -> str:
    return "" if _is_placeholder(text) else text


def _is_box_label_row(row_cells: list[Cell]) -> bool:
    """框表标签横排（包装种类/件数/毛重…）不当表头。只看 BOX，不看 KV。

    占位格视同空（#64）：不占「整行 BOX」的名额，也不破坏判定。
    """
    labels = _box_labels()
    hits = 0
    present = 0
    for cell in row_cells:
        cleaned = _label_text(cell.value)
        if _is_placeholder(cleaned):
            continue
        present += 1
        if cleaned in labels:
            hits += 1
    return hits >= 3 and hits == present


def _is_header_row(row_cells: list[Cell]) -> bool:
    if len(row_cells) < 3:
        return False
    if _is_box_label_row(row_cells):
        return False
    tokens = _table_tokens()
    hits = 0
    for cell in row_cells:
        text = cell.value
        # 真实表头行全是文本（#64）：混进纯数值 / 日期 / 占位格的是数据行，
        # 长套话格凑 token 不算表头。
        if _looks_like_data_cell(text) or _is_placeholder(text):
            return False
        if any(_token_in_text(token, text) for token in tokens):
            hits += 1
    return hits >= 2


def _looks_like_data_cell(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if _DATETIME_FULL.match(stripped) or _TIME_FULL.match(stripped):
        return True
    if _NUMERIC.match(stripped) and any(ch.isdigit() for ch in stripped):
        return True
    return False


def _looks_like_header_cell(text: str) -> bool:
    stripped = text.strip()
    if not stripped or _looks_like_data_cell(stripped):
        return False
    if any(_token_in_text(token, stripped) for token in _table_tokens()):
        return True
    letters = [ch for ch in stripped if ch.isalpha()]
    if len(letters) < 3:
        return False
    ascii_letters = [ch for ch in letters if ch.isascii()]
    return len(ascii_letters) >= 3 and len(ascii_letters) >= len(letters) * 0.6


def _is_translation_row(row_cells: list[Cell]) -> bool:
    """中文表头下一行是英文翻译 / 补充表头，不当数据行。"""
    if len(row_cells) < 2:
        return False
    if _is_box_label_row(row_cells):
        return False
    data_like = 0
    header_like = 0
    for cell in row_cells:
        text = cell.value
        if _looks_like_data_cell(text):
            data_like += 1
        elif _looks_like_header_cell(text):
            header_like += 1
    if data_like >= 2:
        return False
    return header_like >= 2 and header_like > data_like


def _table_cells(tables: list[Table], cells: list[Cell]) -> set[str]:
    if not tables:
        return set()
    table_rows: set[int] = set()
    for table in tables:
        header_rows = table.header_rows or [table.header_row]
        table_rows.update(header_rows)
        start = max(header_rows) + 1
        table_rows.update(range(start, start + len(table.rows)))
    return {cell.address for cell in cells if cell.row in table_rows}


_STRATEGY_RANK = {"same_cell": 0, "below": 1, "right": 2}


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
        if cell.address in occupied or not cell.value or _is_placeholder(cell.value):
            continue
        candidates = [
            item
            for item in (
                _same_cell_colon(cell),
                _value_below(cell, by_pos, occupied),
                _value_right(cell, by_pos, occupied),
            )
            if item is not None
        ]
        chosen = _pick_key_value(candidates)
        if chosen:
            add(chosen)

    return found


def _pick_key_value(candidates: list[KeyValue]) -> KeyValue | None:
    if not candidates:
        return None
    kept = [item for item in candidates if _value_shape_ok(item)]
    if not kept:
        return None
    if len(kept) == 1:
        return kept[0]
    return min(kept, key=lambda item: _STRATEGY_RANK.get(item.strategy, 99))


def _value_shape_ok(item: KeyValue) -> bool:
    spec = load_layout_vocab().value_for_key(item.key)
    if spec is None:
        return True
    return _matches_value_spec(item.value, spec)


def _matches_value_spec(text: str, spec: VocabValue) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if spec.type == "text":
        return True
    if spec.type == "number":
        return _NUMERIC.fullmatch(stripped) is not None and any(ch.isdigit() for ch in stripped)
    if spec.type == "date":
        return _DATE_ONLY.fullmatch(stripped) is not None
    if spec.type == "datetime":
        return _DATETIME_FULL.fullmatch(stripped) is not None
    if spec.type == "pattern":
        return re.fullmatch(spec.pattern or "", stripped) is not None
    return True


def _split_colon(text: str) -> tuple[str, str] | None:
    match = _SPLIT_COLON.match(text.strip())
    if not match:
        return None
    key, value = match.group(1).strip(), match.group(2).strip()
    if not key or not value:
        return None
    return key, value


def _same_cell_colon(cell: Cell) -> KeyValue | None:
    text = cell.value.strip()
    if _DATETIME_FULL.match(text) or _TIME_FULL.match(text):
        return None
    split = _split_colon(text)
    if not split:
        return None
    key, value = split
    if _is_placeholder(value):
        return None
    if _DATETIME_LEFT.match(key) or _TIME_FULL.match(key):
        return None
    if any(_token_in_text(token, key) for token in _table_tokens()):
        return None
    return KeyValue(
        key=key,
        value=value,
        key_cell=cell.address,
        value_cell=cell.address,
        strategy="same_cell",
    )


def _known_key_part(text: str) -> str | None:
    """整格或冒号左侧是词表键时，返回该键。"""
    stripped = text.strip()
    cleaned = _label_text(stripped)
    if _is_known_key(cleaned):
        return cleaned
    split = _split_colon(stripped)
    if split and _is_known_key(split[0]):
        return split[0]
    return None


def _key_text(text: str) -> str:
    known = _known_key_part(text)
    if known is not None:
        return known
    return _label_text(text)


def _looks_like_label(text: str) -> bool:
    stripped = text.strip()
    cleaned = _label_text(stripped)
    if not cleaned or len(cleaned) > 40:
        return False
    if _known_key_part(stripped) is not None:
        return True
    if _ends_with_colon(stripped) and not re.fullmatch(r"[\d.\-]+", cleaned):
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
    if _is_placeholder(other.value):
        return None
    if _same_cell_colon(other) is not None or _looks_like_label(other.value):
        return None
    key = _key_text(cell.value)
    return KeyValue(
        key=key,
        value=other.value,
        key_cell=cell.address,
        value_cell=other.address,
        strategy="below",
    )


def _scan_right(
    cell: Cell,
    by_pos: dict[tuple[int, int], Cell],
) -> Cell | None:
    """右向找值：跳过 ≤_RIGHT_SKIP_MAX 个空列 / 占位格，取第一个非空格。"""
    row = cell.row
    col = (_merge_right(cell) or 0) + 1
    blanks = 0
    while blanks <= _RIGHT_SKIP_MAX:
        other = by_pos.get((row, col))
        if other is None or not other.value.strip() or _is_placeholder(other.value):
            blanks += 1
            col += 1
            continue
        return other
    return None


def _value_right(
    cell: Cell,
    by_pos: dict[tuple[int, int], Cell],
    occupied: set[str],
) -> KeyValue | None:
    if cell.row is None or cell.column is None:
        return None
    text = cell.value.strip()
    key = _key_text(text)
    if not (_ends_with_colon(text) or _is_known_key(key)):
        return None
    other = _scan_right(cell, by_pos)
    if other is None or other.address in occupied:
        return None
    if _same_cell_colon(other) is not None or _looks_like_label(other.value):
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
