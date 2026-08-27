"""OCR 字块 → 伪格子（#62）。

扫描页 / 文字层 PDF 进 IR 后只有 pages[].blocks。xlsx 全链路吃的是
Sheet.cells + split_sheet 拆出的 KV / 表。本模块只做几何重建：

    行带聚类 → 分区列切分 → 同列跨行合并 → 压缩空行 → Sheet.cells

表头 KV 与商品表各自定列，避免商品列边界把框表标签挤进同一格。
随后复用 layout.split_sheet + sheet_role，不写第二套词表 / 刀法。
已有 sheets 的文档（xlsx）原样返回。
"""

from __future__ import annotations

from dataclasses import dataclass

from docparse.adapters.parsers.layout import split_sheet
from docparse.domain.ir import BoundingBox, Cell, DocumentIR, Page, Sheet, TextBlock
from docparse.extraction.sheet_role import classify_sheets

# 行带：中心 y 差 ≤ max(行高×比例, 绝对下限) 并入同一行。
# 半岛真机行带约 65px（#60）；文字层 PDF 是 pt，取绝对值下限兜底。
_ROW_GAP_RATIO = 0.55
_ROW_GAP_MIN = 8.0
# 列边界：相邻字块 x 中心差超过这个倍数才切开。
_COL_GAP_RATIO = 0.55
_COL_GAP_MIN = 12.0
# 跨行合并：下一行同列字块相对当前格高度不超过这个倍数。
_MERGE_HEIGHT_RATIO = 1.6
# 表头行：优先用含 TABLE token 的行定列；找不到再用最密的一行。
_HEADER_MIN_BLOCKS = 3


@dataclass
class _Placed:
    block: TextBlock
    bbox: BoundingBox

    @property
    def cx(self) -> float:
        return (self.bbox.x0 + self.bbox.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.bbox.y0 + self.bbox.y1) / 2.0

    @property
    def height(self) -> float:
        return max(self.bbox.y1 - self.bbox.y0, 1.0)

    @property
    def width(self) -> float:
        return max(self.bbox.x1 - self.bbox.x0, 1.0)


@dataclass
class _Band:
    items: list[_Placed]

    @property
    def y0(self) -> float:
        return min(item.bbox.y0 for item in self.items)

    @property
    def y1(self) -> float:
        return max(item.bbox.y1 for item in self.items)

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 1.0)


def reconstruct_document(document: DocumentIR) -> DocumentIR:
    """有 pages[].blocks 且无 sheets 时重建伪 sheet；否则原样返回。"""
    if document.sheets:
        return document
    pages = [page for page in document.pages if any(_usable(block) for block in page.blocks)]
    if not pages:
        return document
    sheets = [reconstruct_page(page) for page in pages]
    rebuilt = document.model_copy(update={"sheets": sheets})
    classify_sheets(rebuilt)
    return rebuilt


def reconstruct_page(page: Page) -> Sheet:
    """一页字块 → 一张伪 sheet（name = 页号），已跑 split_sheet。"""
    placed = [_place(block) for block in page.blocks if _usable(block)]
    if not placed:
        return split_sheet(Sheet(name=str(page.page_number), cells=[]))
    bands = _cluster_rows(placed)
    cells = _cells_by_region(bands, page.page_number)
    return split_sheet(Sheet(name=str(page.page_number), cells=cells))


def _usable(block: TextBlock) -> bool:
    return bool(block.text.strip()) and block.bbox is not None


def _place(block: TextBlock) -> _Placed:
    assert block.bbox is not None
    return _Placed(block=block, bbox=block.bbox)


def _cluster_rows(placed: list[_Placed]) -> list[_Band]:
    """按 y 中心聚类成行带，行内再按 x 排序。"""
    ordered = sorted(placed, key=lambda item: (item.cy, item.cx))
    bands: list[_Band] = []
    for item in ordered:
        if bands and _same_row(item, bands[-1]):
            bands[-1].items.append(item)
            continue
        bands.append(_Band(items=[item]))
    for band in bands:
        band.items.sort(key=lambda item: item.cx)
    return bands


def _same_row(item: _Placed, band: _Band) -> bool:
    gap = max(band.height * _ROW_GAP_RATIO, _ROW_GAP_MIN)
    return abs(item.cy - band.cy) <= gap


def _cells_by_region(bands: list[_Band], page_number: int) -> list[Cell]:
    """表头 KV 与商品表分区定列，行号跨区连续。"""
    header = _header_band(bands)
    if header is None:
        return _cells_from_bands(bands, _column_bounds(bands), page_number, 0)
    header_idx = bands.index(header)
    pre, post = bands[:header_idx], bands[header_idx:]
    cells: list[Cell] = []
    if pre:
        cells.extend(_cells_from_bands(pre, _column_bounds(pre), page_number, 0))
    used_rows = {cell.row or 0 for cell in cells}
    offset = max(used_rows) if used_rows else 0
    cells.extend(_cells_from_bands(post, _column_bounds(post), page_number, offset))
    return cells


def _column_bounds(bands: list[_Band]) -> list[tuple[float, float]]:
    """列区间：优先用表头行；框表区按行内空隙投票，避免标题长块带偏。"""
    if not bands:
        return [(0.0, 1.0)]
    header = _header_band(bands)
    if header is not None:
        return _bounds_from_seeds(header.items, bands)
    # 框表：用最密的标签行定列（海关框表同一行标签最多），取值行只往已定列里放。
    label_bands = [band for band in bands if _looks_like_label_band(band)]
    if label_bands:
        densest_label = max(label_bands, key=lambda band: len(band.items))
        return _bounds_from_seeds(densest_label.items, bands)
    seed_bands = bands
    cuts = _gap_cuts(seed_bands)
    left = _span_x0(bands) - 1.0
    right = _span_x1(bands) + 1.0
    if not cuts:
        densest = max(seed_bands, key=lambda band: len(band.items)).items
        return _bounds_from_seeds(densest, bands)
    bounds: list[tuple[float, float]] = []
    start = left
    for cut in cuts:
        bounds.append((start, cut))
        start = cut
    bounds.append((start, right))
    return bounds


def _bounds_from_seeds(seeds: list[_Placed], bands: list[_Band]) -> list[tuple[float, float]]:
    if not seeds:
        return [(_span_x0(bands), _span_x1(bands))]
    widths = [item.width for item in seeds]
    typical = sorted(widths)[len(widths) // 2]
    gap = max(typical * _COL_GAP_RATIO, _COL_GAP_MIN)
    groups: list[list[_Placed]] = [[seeds[0]]]
    for item in seeds[1:]:
        if item.cx - groups[-1][-1].cx > gap:
            groups.append([item])
        else:
            groups[-1].append(item)
    edges = [_group_x(group) for group in groups]
    mids = [(edges[i][1] + edges[i + 1][0]) / 2.0 for i in range(len(edges) - 1)]
    left = min(edges[0][0], _span_x0(bands)) - 1.0
    right = max(edges[-1][1], _span_x1(bands)) + 1.0
    bounds: list[tuple[float, float]] = []
    start = left
    for mid in mids:
        bounds.append((start, mid))
        start = mid
    bounds.append((start, right))
    return bounds


def _gap_cuts(bands: list[_Band]) -> list[float]:
    """框表区：收集各行相邻字块之间的空隙中点，相近的并成列缝。"""
    raw: list[float] = []
    for band in bands:
        items = sorted(band.items, key=lambda item: item.cx)
        if len(items) < 2:
            continue
        widths = [item.width for item in items]
        typical = sorted(widths)[len(widths) // 2]
        min_gap = max(typical * _COL_GAP_RATIO, _COL_GAP_MIN)
        for left, right in zip(items, items[1:], strict=False):
            if right.bbox.x0 - left.bbox.x1 >= min_gap:
                raw.append((left.bbox.x1 + right.bbox.x0) / 2.0)
    if not raw:
        return []
    raw.sort()
    clusters: list[list[float]] = [[raw[0]]]
    merge_tol = max(_COL_GAP_MIN, (raw[-1] - raw[0]) * 0.04)
    for cut in raw[1:]:
        if cut - clusters[-1][-1] <= merge_tol:
            clusters[-1].append(cut)
        else:
            clusters.append([cut])
    # 多行时丢掉只出现一次的缝（标题长块空隙）；单行框表直接用该行的缝。
    voters = sum(1 for band in bands if len(band.items) >= 2)
    need = 2 if voters >= 2 else 1
    return [sum(group) / len(group) for group in clusters if len(group) >= need]


def _looks_like_label_band(band: _Band) -> bool:
    """标签行：多数是短标签，且没有长取值（公司名 / 单号）。"""
    if len(band.items) < 2:
        return False
    short = 0
    long = 0
    numeric = 0
    for item in band.items:
        text = item.block.text.strip()
        if _looks_numeric(text):
            numeric += 1
        elif len(text) <= 12:
            short += 1
        elif len(text) >= 18:
            long += 1
    if long:
        return False
    return short >= 2 and short > numeric


def _looks_numeric(text: str) -> bool:
    compact = text.replace(",", "").replace(".", "", 1)
    return bool(compact) and compact.isdigit()


def _header_band(bands: list[_Band]) -> _Band | None:
    from docparse.schema.loader import load_layout_vocab

    tokens = load_layout_vocab().table_tokens()
    best: _Band | None = None
    best_hits = 0
    for band in bands:
        if len(band.items) < _HEADER_MIN_BLOCKS:
            continue
        hits = sum(1 for item in band.items if _hits_token(item.block.text, tokens))
        if hits >= 2 and hits > best_hits:
            best = band
            best_hits = hits
    return best


def _hits_token(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token.casefold() in text.casefold() for token in tokens)


def _group_x(group: list[_Placed]) -> tuple[float, float]:
    return min(item.bbox.x0 for item in group), max(item.bbox.x1 for item in group)


def _span_x0(bands: list[_Band]) -> float:
    return min(item.bbox.x0 for band in bands for item in band.items)


def _span_x1(bands: list[_Band]) -> float:
    return max(item.bbox.x1 for band in bands for item in band.items)


def _assign_column(item: _Placed, columns: list[tuple[float, float]]) -> int:
    """按水平重叠最大列归属。同左缘、值更宽时中心会漂到下一列，不能只看 cx。"""
    best = 0
    best_overlap = -1.0
    for index, (left, right) in enumerate(columns):
        overlap = min(item.bbox.x1, right) - max(item.bbox.x0, left)
        if overlap > best_overlap:
            best_overlap = overlap
            best = index
    if best_overlap > 0:
        return best
    for index, (left, right) in enumerate(columns):
        if left <= item.cx < right:
            return index
    return len(columns) - 1


def _cells_from_bands(
    bands: list[_Band],
    columns: list[tuple[float, float]],
    page_number: int,
    row_offset: int,
) -> list[Cell]:
    """行带 × 列区间 → 格子；稀疏续行并入上一格后压缩行号。"""
    grid: list[list[_Placed | None]] = []
    for band in bands:
        row: list[_Placed | None] = [None] * len(columns)
        for item in band.items:
            col = _assign_column(item, columns)
            row[col] = _join_same_cell(row[col], item)
        grid.append(row)

    consumed: set[tuple[int, int]] = set()
    for row_idx, row in enumerate(grid):
        for col_idx, seed in enumerate(row):
            if seed is None or (row_idx, col_idx) in consumed:
                continue
            last = row_idx
            for nxt in range(row_idx + 1, len(grid)):
                other = grid[nxt][col_idx]
                if other is None:
                    continue
                if not _should_merge(
                    grid[nxt], members_height=seed, other=other, row_gap=nxt - last
                ):
                    break
                seed = _join_same_cell(seed, other)
                grid[row_idx][col_idx] = seed
                grid[nxt][col_idx] = None
                consumed.add((nxt, col_idx))
                last = nxt

    kept = [row for row in grid if any(item is not None for item in row)]
    cells: list[Cell] = []
    for row_idx, row in enumerate(kept):
        for col_idx, item in enumerate(row):
            if item is None:
                continue
            cells.append(_make_cell(item, row_offset + row_idx + 1, col_idx + 1, page_number))
    return cells


def _join_same_cell(existing: _Placed | None, incoming: _Placed) -> _Placed:
    """同一格多个字块：同行空格连接，跨行换行连接。"""
    if existing is None:
        return incoming
    sep = "\n" if incoming.bbox.y0 >= existing.bbox.y1 - 1 else " "
    text = f"{existing.block.text}{sep}{incoming.block.text}".strip()
    bbox = _union_bbox(existing.bbox, incoming.bbox)
    ids = ",".join(
        part for part in (existing.block.block_id, incoming.block.block_id) if part
    )
    block = existing.block.model_copy(
        update={"text": text, "bbox": bbox, "block_id": ids or existing.block.block_id}
    )
    return _Placed(block=block, bbox=bbox)


def _should_merge(
    next_row: list[_Placed | None],
    *,
    members_height: _Placed,
    other: _Placed,
    row_gap: int,
) -> bool:
    """品名 / 规格跨行：下一行几乎只有这一列，且紧贴上一格。"""
    if row_gap > 1:
        return False
    limit = max(members_height.height * _MERGE_HEIGHT_RATIO, _ROW_GAP_MIN)
    if other.bbox.y0 - members_height.bbox.y1 > limit:
        return False
    filled = sum(1 for item in next_row if item is not None)
    # 数据行 / 框表标签行多列有值，不并；续行通常只剩品名或规格一列。
    if filled > 1:
        return False
    if other.width > members_height.width * 1.8:
        return False
    return True


def _make_cell(item: _Placed, row: int, column: int, page_number: int) -> Cell:
    text = item.block.text.strip()
    ids: list[str] = []
    for part in (item.block.block_id or "").split(","):
        if part and part not in ids:
            ids.append(part)
    return Cell(
        address=f"p{page_number}r{row}c{column}",
        value=text,
        raw_value=text or None,
        row=row,
        column=column,
        bbox=item.bbox,
        block_ids=ids,
    )


def _union_bbox(left: BoundingBox, right: BoundingBox) -> BoundingBox:
    return BoundingBox(
        x0=min(left.x0, right.x0),
        y0=min(left.y0, right.y0),
        x1=max(left.x1, right.x1),
        y1=max(left.y1, right.y1),
    )
