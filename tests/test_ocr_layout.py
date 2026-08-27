"""#62 OCR 版面重建。夹具按 #60 真机 y/x 分布程序造，不含客户数据。"""

from __future__ import annotations

from docparse.adapters.parsers.ocr_layout import reconstruct_document, reconstruct_page
from docparse.domain.ir import BoundingBox, Cell, DocumentIR, Page, Sheet, TextBlock
from docparse.extraction.sheet_role import classify_sheet
from docparse.pipeline.runner import DEFAULT_STEPS
from docparse.pipeline.steps.reconstruct_layout import reconstruct_layout_step

# 半岛真机（#60）：行带约 65px，列中心大致
# 项号 70 / HS+品名 116 / 数量 768 / 单价 929 / 总价 1020 / 原产国 1088
_ROW_H = 65.0
_TABLE_XS = {
    "项号": (50, 90),
    "商品编号": (100, 250),
    "商品名称及规格型号": (260, 520),
    "数量": (740, 800),
    "单价": (900, 960),
    "总价": (990, 1050),
    "原产国": (1070, 1140),
}


def _block(block_id: str, text: str, x0: float, y0: float, x1: float, y1: float) -> TextBlock:
    return TextBlock(
        block_id=block_id,
        text=text,
        bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1),
        ocr_confidence=0.98,
    )


def _kv_pair(
    prefix: str,
    key: str,
    value: str,
    *,
    x: float,
    y: float,
    key_w: float = 90,
    val_w: float = 160,
    h: float = 22,
    gap: float = 28,
) -> list[TextBlock]:
    """上标签下取值（框表 below 策略）。"""
    return [
        _block(f"{prefix}k", key, x, y, x + key_w, y + h),
        _block(f"{prefix}v", value, x, y + gap, x + val_w, y + gap + h),
    ]


def peninsula_like_blocks() -> list[TextBlock]:
    """合成报关单页：框表 KV + 商品表（含跨行品名）。数字是自造的。"""
    blocks: list[TextBlock] = [
        _block("t1", "中华人民共和国海关出口货物报关单", 40, 20, 520, 48),
    ]
    # 框表：备案号 / 境外发货人 左右；件数 / 毛重 / 净重 横排
    blocks.extend(_kv_pair("man", "备案号", "T0000W000001", x=40, y=70, val_w=140))
    blocks.extend(
        _kv_pair(
            "cons",
            "境外发货人",
            "NORTHWIND TRADING LIMITED",
            x=360,
            y=70,
            key_w=100,
            val_w=280,
        )
    )
    blocks.extend(_kv_pair("pk", "件数", "214", x=40, y=150, key_w=50, val_w=60))
    blocks.extend(_kv_pair("gw", "毛重", "1459.62", x=160, y=150, key_w=50, val_w=80))
    blocks.extend(_kv_pair("nw", "净重", "485", x=280, y=150, key_w=50, val_w=60))

    header_y = 260.0
    for name, (x0, x1) in _TABLE_XS.items():
        blocks.append(_block(f"h-{name}", name, x0, header_y, x1, header_y + 24))

    goods = [
        ("1", "1905310000", "黄油酥饼", "120", "1.2", "144", "中国"),
        ("2", "1905900000", "巧克力派", "80", "2.5", "200", "中国"),
        ("3", "1806320000", "夹心饼干", "14", "3.1", "43.4", "中国"),
    ]
    y = header_y + _ROW_H
    for index, (gno, hs, name, qty, price, total, origin) in enumerate(goods, start=1):
        values = {
            "项号": gno,
            "商品编号": hs,
            "商品名称及规格型号": name,
            "数量": qty,
            "单价": price,
            "总价": total,
            "原产国": origin,
        }
        for col, text in values.items():
            x0, x1 = _TABLE_XS[col]
            blocks.append(_block(f"g{index}-{col}", text, x0, y, x1, y + 22))
        if index == 1:
            # 第 1 件规格跨到下一行同列（多行格）
            nx0, nx1 = _TABLE_XS["商品名称及规格型号"]
            blocks.append(
                _block("g1-spec", "规格:原味", nx0, y + 28, nx0 + 90, y + 48)
            )
        y += _ROW_H
    return blocks


def peninsula_like_document() -> DocumentIR:
    blocks = peninsula_like_blocks()
    return DocumentIR(
        document_id="d1",
        file_id="f1",
        filename="scan.pdf",
        media_type="application/pdf",
        pages=[Page(page_number=1, width=1200, height=800, blocks=blocks)],
        raw_text="\n".join(block.text for block in blocks),
    )


def _kv(sheet, key: str) -> str | None:
    for item in sheet.key_values:
        if item.key == key:
            return item.value
    return None


class TestReconstructPeninsulaLike:
    def test_rebuilds_kv_and_goods_table(self) -> None:
        document = reconstruct_document(peninsula_like_document())
        assert len(document.sheets) == 1
        sheet = document.sheets[0]
        assert sheet.name == "1"
        assert _kv(sheet, "备案号") == "T0000W000001"
        assert _kv(sheet, "境外发货人") == "NORTHWIND TRADING LIMITED"
        assert _kv(sheet, "件数") == "214"
        assert _kv(sheet, "毛重") == "1459.62"
        assert _kv(sheet, "净重") == "485"
        assert sheet.tables
        table = sheet.tables[0]
        assert "项号" in table.headers
        assert "商品编号" in table.headers
        assert len(table.rows) == 3
        first = table.rows[0]
        assert first["项号"] == "1"
        assert first["商品编号"] == "1905310000"
        assert first["数量"] == "120"

    def test_merges_multiline_goods_name(self) -> None:
        document = reconstruct_document(peninsula_like_document())
        table = document.sheets[0].tables[0]
        name_header = next(h for h in table.headers if "商品名称" in h)
        assert "黄油酥饼" in table.rows[0][name_header]
        assert "规格:原味" in table.rows[0][name_header]
        # 规格行没有另开一件商品
        assert len(table.rows) == 3

    def test_cells_point_back_to_blocks(self) -> None:
        document = reconstruct_document(peninsula_like_document())
        sheet = document.sheets[0]
        hit = next(cell for cell in sheet.cells if cell.value == "T0000W000001")
        assert hit.bbox is not None
        assert hit.block_ids
        assert all(item.startswith("man") or item for item in hit.block_ids)
        assert hit.address.startswith("p1r")

    def test_sheet_role_is_draft(self) -> None:
        document = reconstruct_document(peninsula_like_document())
        sheet = classify_sheet(document.sheets[0], filename="scan.pdf")
        assert sheet.role == "draft"
        assert sheet.consume == "primary"


class TestReconstructGuards:
    def test_skips_document_that_already_has_sheets(self) -> None:
        existing = Sheet(
            name="一般贸易出口",
            cells=[Cell(address="A1", value="已有格子", row=1, column=1)],
        )
        original = DocumentIR(
            document_id="xlsx",
            file_id="x",
            filename="draft.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            pages=[
                Page(
                    page_number=1,
                    blocks=[_block("ignored", "备案号", 10, 10, 80, 30)],
                )
            ],
            sheets=[existing],
        )
        rebuilt = reconstruct_document(original)
        assert rebuilt.sheets is original.sheets
        assert rebuilt.sheets[0].cells[0].value == "已有格子"

    def test_empty_pages_stay_sheetless(self) -> None:
        document = DocumentIR(
            document_id="d2",
            file_id="f2",
            filename="blank.pdf",
            media_type="application/pdf",
            pages=[Page(page_number=1, width=100, height=100, blocks=[])],
        )
        rebuilt = reconstruct_document(document)
        assert rebuilt.sheets == []

    def test_blocks_without_bbox_are_ignored(self) -> None:
        document = DocumentIR(
            document_id="d3",
            file_id="f3",
            filename="nobbox.pdf",
            media_type="application/pdf",
            pages=[
                Page(
                    page_number=1,
                    blocks=[TextBlock(block_id="a", text="备案号")],
                )
            ],
        )
        rebuilt = reconstruct_document(document)
        assert rebuilt.sheets == []

    def test_two_pages_become_two_sheets(self) -> None:
        page1 = Page(
            page_number=1,
            width=400,
            height=200,
            blocks=[_block("a", "备案号", 10, 10, 80, 30), _block("b", "X1", 10, 40, 80, 60)],
        )
        page2 = Page(
            page_number=2,
            width=400,
            height=200,
            blocks=[_block("c", "件数", 10, 10, 50, 30), _block("d", "3", 10, 40, 40, 60)],
        )
        document = DocumentIR(
            document_id="d4",
            file_id="f4",
            filename="two.pdf",
            media_type="application/pdf",
            pages=[page1, page2],
        )
        rebuilt = reconstruct_document(document)
        assert [sheet.name for sheet in rebuilt.sheets] == ["1", "2"]


class TestPipelineHook:
    def test_step_sits_between_extract_and_classify(self) -> None:
        names = [name for name, _ in DEFAULT_STEPS]
        assert names.index("extract") + 1 == names.index("reconstruct")
        assert names.index("reconstruct") + 1 == names.index("classify")

    def test_step_rebuilds_sheets_on_context(self) -> None:
        class _Pkg:
            def __init__(self) -> None:
                self.documents: list[DocumentIR] = []

        class _Ctx:
            def __init__(self) -> None:
                self.documents = [peninsula_like_document()]
                self.package = _Pkg()

        ctx = _Ctx()
        reconstruct_layout_step(ctx)
        assert ctx.documents[0].sheets
        assert ctx.documents[0].sheets[0].key_values
        assert ctx.package.documents is ctx.documents


class TestColumnOverlap:
    def test_wider_value_stays_under_short_label(self) -> None:
        """同左缘、值更宽时按重叠归属，不漂到下一列。"""
        page = Page(
            page_number=1,
            width=400,
            height=160,
            blocks=[
                _block("k1", "件数", 10, 10, 40, 28),
                _block("k2", "备案号", 200, 10, 240, 28),
                _block("k3", "毛重", 320, 10, 360, 28),
                _block("v1", "214", 10, 40, 40, 58),
                _block("v2", "T5352W000228", 200, 40, 300, 58),
                _block("v3", "12.5", 320, 40, 360, 58),
            ],
        )
        sheet = reconstruct_page(page)
        pairs = {item.key: item.value for item in sheet.key_values}
        assert pairs.get("备案号") == "T5352W000228"
        assert pairs.get("件数") == "214"

    def test_long_title_does_not_steal_box_columns(self) -> None:
        """横贯标题不当列种子；短标签行定列，值按重叠落回标签列。"""
        page = Page(
            page_number=1,
            width=800,
            height=220,
            blocks=[
                _block("title", "中华人民共和国海关出口货物报关单", 80, 10, 520, 32),
                _block("k1", "境外发货人", 40, 50, 100, 70),
                _block("k2", "运输方式", 240, 50, 300, 70),
                _block("k3", "备案号", 520, 50, 560, 70),
                _block("v1", "NORTHWIND TRADING LIMITED", 40, 80, 220, 100),
                _block("v2", "公路运输", 240, 80, 300, 100),
                _block("v3", "T0000W000001", 520, 80, 600, 100),
                _block("k4", "件数", 40, 130, 80, 150),
                _block("k5", "毛重", 200, 130, 240, 150),
                _block("k6", "净重", 360, 130, 400, 150),
                _block("v4", "214", 40, 160, 80, 180),
                _block("v5", "1459.62", 200, 160, 260, 180),
                _block("v6", "485", 360, 160, 400, 180),
            ],
        )
        sheet = reconstruct_page(page)
        pairs = {item.key: item.value for item in sheet.key_values}
        assert pairs.get("备案号") == "T0000W000001"
        assert pairs.get("境外发货人") == "NORTHWIND TRADING LIMITED"
        assert pairs.get("件数") == "214"
        assert pairs.get("毛重") == "1459.62"
        assert pairs.get("净重") == "485"


class TestReconstructPageAddress:
    def test_address_uses_page_row_column(self) -> None:
        page = Page(
            page_number=3,
            width=300,
            height=120,
            blocks=[
                _block("a", "项号", 10, 10, 40, 28),
                _block("b", "数量", 80, 10, 120, 28),
                _block("c", "单价", 160, 10, 200, 28),
            ],
        )
        sheet = reconstruct_page(page)
        addresses = {cell.address for cell in sheet.cells}
        assert "p3r1c1" in addresses
        assert all(item.startswith("p3r") for item in addresses)
