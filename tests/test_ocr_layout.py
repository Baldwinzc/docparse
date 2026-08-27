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


# 进境备案清单形（#82）：y/x 分布按真机，公司名 / 信用代码 / 单证号换成自造值。
# 关键几何：标签行与取值行的 x 各不相同，列界由最密的包装种类行投出，
# 标签与值会差一列（进境关别 c3 / 莲塘海关 c2），靠邻列兜底配上。
_ENTRY_LIST_USCC = "91440300MA5EXAMP01"


def entry_list_like_blocks() -> list[TextBlock]:
    """进境备案清单头部：标签带信用代码、值列漂移、紧凑日期、词表标签贴值行。"""
    return [
        _block("t", "中华人民共和国海关进境货物备案清单", 266.5, 34.0, 573.5, 56.0),
        # 第一横排：标签 / 值（进境关别与备案号的值会漂一列）
        _block("p1k1", f"境内收货人（{_ENTRY_LIST_USCC}）", 39.0, 89.0, 171.0, 99.0),
        _block("p1k2", "进境关别（5354）", 257.0, 88.0, 322.5, 100.5),
        _block("p1k3", "进境日期", 385.5, 88.0, 419.0, 98.0),
        _block("p1k4", "申报日期", 519.5, 88.0, 551.5, 98.0),
        _block("p1k5", "备案号", 639.5, 89.0, 664.0, 98.0),
        _block("p1v1", "北岸（深圳）供应链有限公司", 38.0, 99.0, 159.5, 111.0),
        _block("p1v2", "莲塘海关", 257.5, 99.0, 297.0, 111.0),
        _block("p1v3", "20250814", 385.5, 100.5, 424.0, 110.5),
        _block("p1v4", "20250813", 518.5, 100.5, 557.0, 110.5),
        _block("p1v5", "T5352W000228", 639.5, 101.5, 695.0, 110.5),
        # 第二横排：同列对照（境外发货人 → 英文名）
        _block("p2k1", "境外发货人", 39.0, 113.0, 79.0, 122.5),
        _block("p2v1", "NORTHWIND TRADING LIMITED", 38.0, 122.5, 182.5, 135.0),
        # 密标签行：给整个框表区定列（漂移由它造成）
        _block("b1", "包装种类（22）", 39.0, 182.5, 90.5, 192.5),
        _block("b2", "件数", 257.5, 182.0, 275.5, 191.5),
        _block("b3", "毛重（千克）", 303.0, 180.5, 342.0, 192.5),
        _block("b4", "净重（千克）", 385.5, 182.0, 425.0, 191.5),
        _block("b5", "成交方式（1）", 459.5, 182.0, 508.0, 194.0),
        _block("b6", "运费", 518.5, 182.0, 536.0, 191.5),
        _block("b7", "保费", 610.5, 182.0, 628.5, 191.5),
        _block("b8", "杂费", 702.5, 182.5, 720.0, 191.5),
        _block("bv1", "纸制或纤维板制盒／箱", 38.0, 192.5, 127.5, 205.0),
        _block("bv2", "214", 257.5, 194.0, 274.0, 203.0),
        _block("bv3", "1459.62", 303.5, 193.5, 337.0, 203.0),
        _block("bv4", "485", 385.5, 194.0, 402.0, 203.0),
        # 词表标签紧贴值行：不当续行并入包装种类值（#82）
        _block("ad", "随附单证及编号", 39.0, 205.0, 94.0, 214.5),
        _block(
            "ad1",
            "随附单证1：保税核注清单QD0000000000000 随附单证2：提／运单",
            39.0,
            215.5,
            303.5,
            228.0,
        ),
    ]


def entry_list_like_document() -> DocumentIR:
    blocks = entry_list_like_blocks()
    return DocumentIR(
        document_id="d-entry",
        file_id="f-entry",
        filename="entry.pdf",
        media_type="application/pdf",
        pages=[Page(page_number=1, width=800, height=400, blocks=blocks)],
        raw_text="",
    )


def footer_like_blocks() -> list[TextBlock]:
    """商品表 + 表尾声明区：声明词命中即停，表尾不进表体（#82）。"""
    blocks: list[TextBlock] = [
        _block("t", "中华人民共和国海关进境货物备案清单", 266.5, 34.0, 573.5, 56.0),
    ]
    header_y = 260.0
    for name, (x0, x1) in _TABLE_XS.items():
        blocks.append(_block(f"h-{name}", name, x0, header_y, x1, header_y + 24))
    goods = [
        ("1", "1905310000", "黄油酥饼", "120", "1.2", "144", "中国"),
        ("2", "1905900000", "巧克力派", "80", "2.5", "200", "中国"),
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
        y += _ROW_H
    # 表尾声明区：不是数据行，也不是整行冒号注记
    blocks.extend(
        [
            _block("f1", "特殊关系确认：否", 75.5, 486.5, 138.5, 500.5),
            _block("f2", "报关人员", 41.5, 512.0, 74.0, 522.0),
            _block(
                "f3",
                "兹声明对以上内容承担如实申报、依法纳税之法律责任",
                371.5,
                510.5,
                556.5,
                522.5,
            ),
            _block("f4", "海关批注及签章", 568.0, 512.0, 623.5, 522.0),
        ]
    )
    return blocks


def footer_like_document() -> DocumentIR:
    blocks = footer_like_blocks()
    return DocumentIR(
        document_id="d-footer",
        file_id="f-footer",
        filename="footer.pdf",
        media_type="application/pdf",
        pages=[Page(page_number=1, width=1200, height=800, blocks=blocks)],
        raw_text="",
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


class TestEntryListReconstruct:
    """#82 进境备案清单：邻列漂移配对 / 键内信用代码 / 紧凑日期 / 词表标签防并。"""

    def _sheet(self) -> Sheet:
        document = reconstruct_document(entry_list_like_document())
        return document.sheets[0]

    def test_adjacent_column_values_pair_with_drifted_labels(self) -> None:
        pairs = {item.key: item.value for item in self._sheet().key_values}
        # 值漂一列（标签 c3 / 值 c2）也能配上，不再抓右侧标签当值
        assert pairs.get("进境关别（5354）") == "莲塘海关"
        assert pairs.get("备案号") == "T5352W000228"

    def test_compact_dates_pass_value_spec(self) -> None:
        pairs = {item.key: item.value for item in self._sheet().key_values}
        assert pairs.get("进境日期") == "20250814"
        assert pairs.get("申报日期") == "20250813"

    def test_label_with_uscc_keeps_pairing(self) -> None:
        pairs = {item.key: item.value for item in self._sheet().key_values}
        assert pairs.get(f"境内收货人（{_ENTRY_LIST_USCC}）") == "北岸（深圳）供应链有限公司"
        assert pairs.get("境外发货人") == "NORTHWIND TRADING LIMITED"

    def test_box_values_stay_clean(self) -> None:
        pairs = {item.key: item.value for item in self._sheet().key_values}
        assert pairs.get("包装种类（22）") == "纸制或纤维板制盒／箱"
        assert pairs.get("件数") == "214"
        assert pairs.get("毛重（千克）") == "1459.62"
        assert pairs.get("净重（千克）") == "485"

    def test_known_label_cell_not_merged_into_value_above(self) -> None:
        cells = [cell for cell in self._sheet().cells if "随附单证及编号" in cell.value]
        assert cells, "词表标签应保住自己的格子"
        assert all("纸制" not in cell.value for cell in cells)

    def test_head_maps_entry_list_fields(self) -> None:
        from docparse.extraction.head_map import map_sheet_head

        document = reconstruct_document(entry_list_like_document())
        sheet = document.sheets[0]
        assert sheet.role == "draft"
        by_name = {field.name: field for field in map_sheet_head(sheet, document)}
        assert by_name["tradeName"].value == "北岸（深圳）供应链有限公司"
        # 键内信用代码路由进 tradeScc（#82），证据指向标签格
        assert by_name["tradeScc"].value == _ENTRY_LIST_USCC
        assert by_name["iePort"].value == "莲塘海关"
        assert by_name["ieDate"].value == "20250814"
        assert by_name["declDate"].value == "20250813"
        assert by_name["manualNo"].value == "T5352W000228"
        assert by_name["wrapType"].value == "纸制或纤维板制盒／箱"


class TestFooterStop:
    """#82 表尾声明区停扫：词表 footer token 命中即表体终点。"""

    def test_footer_rows_do_not_enter_goods_table(self) -> None:
        document = reconstruct_document(footer_like_document())
        sheet = document.sheets[0]
        assert sheet.tables, "商品表应重建"
        table = sheet.tables[0]
        assert len(table.rows) == 2
        values = [value for row in table.rows for value in row.values()]
        assert all("特殊关系确认" not in value for value in values)
        assert all("报关人员" not in value for value in values)
        assert all("如实申报" not in value for value in values)

    def test_footer_cells_free_for_kv(self) -> None:
        """声明区不再被表体占住，冒号声明可走同格 KV。"""
        document = reconstruct_document(footer_like_document())
        pairs = {item.key: item.value for item in document.sheets[0].key_values}
        assert pairs.get("特殊关系确认") == "否"


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
