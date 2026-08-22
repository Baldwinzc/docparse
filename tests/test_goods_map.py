from __future__ import annotations

import io
from pathlib import Path

import pytest

pytest.importorskip("openpyxl")

from openpyxl import Workbook
from openpyxl.styles import Border, Side

from docparse.adapters.parsers.excel import parse_excel
from docparse.extraction.goods_map import map_document_goods, map_sheet_goods

_DEMO = Path("/Users/baldwin/Desktop/taizhou/AI识别Demo")
REAL_HENGXIN = _DEMO / "（恒信）一般贸易草单HDX260251BLU.xlsx"
REAL_GUOGUANG = _DEMO / "（国光）箱单发票合同26VN0502-1.xlsx"


def _thin() -> Border:
    line = Side(style="thin")
    return Border(left=line, right=line, top=line, bottom=line)


def _workbook(builders: dict) -> bytes:
    book = Workbook()
    first = True
    for title, fill in builders.items():
        sheet = book.active if first else book.create_sheet(title)
        if first:
            sheet.title = title
            first = False
        fill(sheet)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _draft(sheet) -> None:
    sheet["A1"] = "中华人民共和国海关出口货物报关单"
    sheet["A3"] = "境内发货人"
    sheet["A4"] = "示例公司"
    sheet["E3"] = "出境关别"
    sheet["E4"] = "莲塘口岸"
    sheet["E7"] = "监管方式"
    sheet["E8"] = "一般贸易"
    sheet["I7"] = "征免性质"
    sheet["I8"] = "一般征税"
    headers = [
        ("A17", "项号"),
        ("B17", "商品编号"),
        ("C17", "商品名称及规格型号"),
        ("D17", "申报要素"),
        ("E17", "数量PCS"),
        ("F17", "计价单位"),
        ("G17", "重量KG"),
        ("H17", "单价"),
        ("I17", "总价"),
        ("J17", "币制"),
        ("K17", "原产国（地区）"),
        ("L17", "最终目的国（地区）"),
        ("M17", "境内货源地"),
    ]
    for address, text in headers:
        sheet[address] = text
    sheet["A18"] = 1
    sheet["B18"] = "9111900000"
    sheet["C18"] = "表壳配件/壳体"
    sheet["D18"] = "不锈钢/无中文品牌、无外文品牌/无型号"
    sheet["E18"] = 150
    sheet["F18"] = "只"
    sheet["G18"] = 5.74
    sheet["H18"] = 98
    sheet["I18"] = 14700
    sheet["J18"] = "港币"
    sheet["K18"] = "中国"
    sheet["L18"] = "中国香港"
    sheet["M18"] = "惠州其他"
    for row in sheet.iter_rows(min_row=1, max_row=18, min_col=1, max_col=13):
        for cell in row:
            cell.border = _thin()


def _packing(sheet) -> None:
    sheet["A1"] = "PACKING LIST"
    sheet["I4"] = "Invoice No.﹕"
    sheet["J4"] = "HDX260251"
    sheet["A7"] = "Bill To : BLU PRECISION LIMITED"
    sheet["C11"] = "Description (货物名称)"
    sheet["E11"] = "Ship Q'ty (数量/PCS)"
    sheet["G11"] = "Packing (箱)"
    sheet["H11"] = "N.W. (Kg) (净重)"
    sheet["I11"] = "G.W .(Kg) (毛重)"
    sheet["C12"] = "表壳配件/壳体"
    sheet["E12"] = 150
    sheet["G12"] = 40
    sheet["H12"] = 5.74
    sheet["I12"] = 7.35
    for row in sheet.iter_rows(min_row=1, max_row=12, min_col=1, max_col=10):
        for cell in row:
            cell.border = _thin()


def _invoice(sheet) -> None:
    sheet["A1"] = "INVOICE"
    sheet["F6"] = "发票号INVOICE NO.:"
    sheet["G6"] = "26VN0502-1"
    sheet["A11"] = "运输工具 SHIPPED PER:"
    sheet["B11"] = "BY TRUCK"
    sheet["B16"] = "物料名称"
    sheet["D16"] = "出货数量"
    sheet["E16"] = "币别"
    sheet["F16"] = "单价"
    sheet["G16"] = "汇总价"
    sheet["B17"] = "贴纸"
    sheet["D17"] = 100
    sheet["E17"] = "USD"
    sheet["F17"] = 0.0181
    sheet["G17"] = 1.81
    for row in sheet.iter_rows(min_row=1, max_row=17, min_col=1, max_col=7):
        for cell in row:
            cell.border = _thin()


def _guoguang_packing(sheet) -> None:
    sheet["E5"] = "装箱单 PACKING LIST"
    sheet["A6"] = "日期DATE:"
    sheet["B6"] = "2026-03-15"
    sheet["A7"] = "发票/INVOICE NO.:"
    sheet["B7"] = "26VN0502-1"
    sheet["G7"] = "合同号CONTRACT NO.:"
    sheet["H7"] = "26VN0502"
    sheet["A8"] = "卖方SELLER"
    sheet["A9"] = "GUOGUANG ELECTRIC COMPANY LIMITED."
    sheet["B12"] = "物料名称"
    sheet["C12"] = "单位"
    sheet["D12"] = "出货数量"
    sheet["H12"] = "总净重 NW"
    sheet["J12"] = "总毛重 GW"
    sheet["Q12"] = "HS CODE海关编码"
    sheet["R12"] = "申报要素"
    sheet["S12"] = "原产地"
    sheet["B13"] = "贴纸"
    sheet["C13"] = "个"
    sheet["D13"] = 100
    sheet["H13"] = 0.0013
    sheet["J13"] = 0.5013
    sheet["Q13"] = "4821900000纸或纸板的其他各种标签"
    sheet["R13"] = "0:品牌类型：0|1:出口享惠情况：1"
    sheet["S13"] = "中国"
    for row in sheet.iter_rows(min_row=5, max_row=13, min_col=1, max_col=19):
        for cell in row:
            cell.border = _thin()


def _auxiliary(sheet) -> None:
    sheet["B1"] = "报关单号"
    sheet["C1"] = "报关日期"
    sheet["E1"] = "恒信编号"
    sheet["K1"] = "SAP编号"
    sheet["H1"] = "商品编码"
    sheet["M1"] = "商品名称"
    sheet["B2"] = "SHOULD-NOT-MAP"
    sheet["H2"] = "9999999999"
    sheet["M2"] = "内部料号壳体"
    for row in sheet.iter_rows(min_row=1, max_row=2, min_col=1, max_col=13):
        for cell in row:
            cell.border = _thin()


def _values(item) -> dict[str, str]:
    return {name: field.value for name, field in item.fields.items() if field.value}


def test_hengxin_draft_maps_core_goods_columns() -> None:
    document = parse_excel(
        _workbook({"一般贸易出口": _draft}),
        file_id="hx",
        filename="hengxin-draft.xlsx",
    )
    draft = document.sheets[0]
    assert draft.role == "draft"
    items = map_sheet_goods(draft, document)
    assert len(items) == 1
    values = _values(items[0])
    assert values["gno"] == "1"
    assert values["codeTs"] == "9111900000"
    assert values["gname"] == "表壳配件/壳体"
    assert values["gmodel"] == "不锈钢/无中文品牌、无外文品牌/无型号"
    assert items[0].fields["gmodel"].status.value == "needs_review"
    assert values["gqty"] == "150"
    assert values["gunit"] == "只"
    assert values["declPrice"] == "98"
    assert values["declTotal"] == "14700"
    assert values["tradeCurr"] == "港币"
    assert values["cusOriginCountry"] == "中国"
    assert values["destinationCountry"] == "中国香港"
    assert values["districtCode"] == "惠州其他"
    assert values["customNetWt"] == "5.74"
    assert "qty1" not in values
    assert all(field.evidence for field in items[0].fields.values())


def test_packing_fills_missing_gross_and_does_not_overwrite() -> None:
    document = parse_excel(
        _workbook({"一般贸易出口": _draft, "装箱单": _packing}),
        file_id="mix",
        filename="hengxin.xlsx",
    )
    items = map_document_goods(document)
    assert len(items) == 1
    values = _values(items[0])
    assert items[0].source_role == "draft"
    assert values["gname"] == "表壳配件/壳体"
    assert values["gqty"] == "150"
    assert values["customNetWt"] == "5.74"
    assert values["customGrossWet"] == "7.35"
    assert items[0].fields["customGrossWet"].evidence[0].cell.startswith("装箱单!")
    assert "packQty" not in values
    assert not any("箱" in (field.value or "") for field in items[0].fields.values())


def test_weight_without_gross_copies_net() -> None:
    document = parse_excel(
        _workbook({"一般贸易出口": _draft}),
        file_id="hx",
        filename="draft-only.xlsx",
    )
    items = map_document_goods(document)
    values = _values(items[0])
    assert values["customNetWt"] == "5.74"
    assert values["customGrossWet"] == "5.74"
    assert "net_as_gross" in items[0].review_reasons


def test_auxiliary_is_not_master_or_supplement() -> None:
    document = parse_excel(
        _workbook({"一般贸易出口": _draft, "Sheet3": _auxiliary}),
        file_id="aux",
        filename="aux.xlsx",
    )
    aux = next(sheet for sheet in document.sheets if sheet.name == "Sheet3")
    assert aux.consume == "exclude"
    assert map_sheet_goods(aux, document) == []
    items = map_document_goods(document)
    assert len(items) == 1
    assert items[0].value_of("codeTs") == "9111900000"
    assert all(item.source_role != "auxiliary" for item in items)


def test_guoguang_packing_is_master_invoice_fills_price() -> None:
    document = parse_excel(
        _workbook({"总箱单": _guoguang_packing, "发票": _invoice}),
        file_id="gg",
        filename="guoguang.xlsx",
    )
    packing = next(sheet for sheet in document.sheets if sheet.role == "packing")
    invoice = next(sheet for sheet in document.sheets if sheet.role == "invoice")
    pack_items = map_sheet_goods(packing, document)
    inv_items = map_sheet_goods(invoice, document)
    assert pack_items[0].master_score > inv_items[0].master_score
    items = map_document_goods(document)
    assert len(items) == 1
    values = _values(items[0])
    assert items[0].source_role == "packing"
    assert values["gname"] == "贴纸"
    assert values["codeTs"] == "4821900000"
    assert values["gmodel"].startswith("0:品牌类型")
    assert values["gqty"] == "100"
    assert values["gunit"] == "个"
    assert values["declPrice"] == "0.0181"
    assert values["declTotal"] == "1.81"
    assert values["tradeCurr"] == "USD"
    assert values["customNetWt"] == "0.0013"
    assert values["customGrossWet"] == "0.5013"
    assert items[0].fields["declPrice"].evidence[0].cell.startswith("发票!")


def test_same_name_rows_match_by_qty() -> None:
    def two_caps(sheet) -> None:
        _guoguang_packing(sheet)
        sheet["B14"] = "电容"
        sheet["C14"] = "个"
        sheet["D14"] = 10000
        sheet["H14"] = 0.45
        sheet["Q14"] = "8532241000"
        sheet["R14"] = "瓷介质"
        sheet["S14"] = "中国"
        sheet["B15"] = "电容"
        sheet["C15"] = "个"
        sheet["D15"] = 16000
        sheet["H15"] = 0.57
        sheet["Q15"] = "8532241000"
        sheet["R15"] = "瓷介质"
        sheet["S15"] = "中国"
        for row in sheet.iter_rows(min_row=14, max_row=15, min_col=1, max_col=19):
            for cell in row:
                cell.border = _thin()

    def two_prices(sheet) -> None:
        _invoice(sheet)
        sheet["B18"] = "电容"
        sheet["D18"] = 10000
        sheet["E18"] = "USD"
        sheet["F18"] = 0.00031
        sheet["G18"] = 3.1
        sheet["B19"] = "电容"
        sheet["D19"] = 16000
        sheet["E19"] = "USD"
        sheet["F19"] = 0.00346
        sheet["G19"] = 55.36
        for row in sheet.iter_rows(min_row=18, max_row=19, min_col=1, max_col=7):
            for cell in row:
                cell.border = _thin()

    document = parse_excel(
        _workbook({"总箱单": two_caps, "发票": two_prices}),
        file_id="dup",
        filename="dup.xlsx",
    )
    items = map_document_goods(document)
    caps = [item for item in items if item.value_of("gname") == "电容"]
    assert len(caps) == 2
    by_qty = {item.value_of("gqty"): item.value_of("declPrice") for item in caps}
    assert by_qty == {"10000": "0.00031", "16000": "0.00346"}
    assert all(item.source_kind == "primary" for item in caps)


def test_unmatched_packing_row_is_supplement() -> None:
    def extra_packing(sheet) -> None:
        _packing(sheet)
        sheet["C13"] = "配件"
        sheet["E13"] = 10
        sheet["I13"] = 1.2
        for row in sheet.iter_rows(min_row=13, max_row=13, min_col=1, max_col=10):
            for cell in row:
                cell.border = _thin()

    document = parse_excel(
        _workbook({"一般贸易出口": _draft, "装箱单": extra_packing}),
        file_id="extra",
        filename="extra.xlsx",
    )
    items = map_document_goods(document)
    assert len(items) == 2
    extra = next(item for item in items if item.source_kind == "supplement")
    assert extra.value_of("gname") == "配件"
    assert extra.source_role == "packing"
    assert "unmatched_supplement" in extra.review_reasons


@pytest.mark.skipif(not REAL_HENGXIN.exists(), reason="本地恒信样本不在 CI")
def test_hengxin_sample_goods() -> None:
    document = parse_excel(
        REAL_HENGXIN.read_bytes(),
        file_id="hx-real",
        filename=REAL_HENGXIN.name,
    )
    items = map_document_goods(document)
    first = items[0]
    values = _values(first)
    assert first.source_role == "draft"
    assert values["gno"] == "1"
    assert values["codeTs"] == "9111900000"
    assert values["gname"] == "表壳配件/壳体"
    assert "不锈钢" in (values["gmodel"] or "")
    assert values["customNetWt"] == "5.74"
    assert values["customGrossWet"] == "7.35"
    assert all(item.source_role != "auxiliary" for item in items)
    assert all(field.evidence for field in first.fields.values())


@pytest.mark.skipif(not REAL_GUOGUANG.exists(), reason="本地国光样本不在 CI")
def test_guoguang_sample_goods() -> None:
    document = parse_excel(
        REAL_GUOGUANG.read_bytes(),
        file_id="gg-real",
        filename=REAL_GUOGUANG.name,
    )
    items = map_document_goods(document)
    first = items[0]
    values = _values(first)
    assert first.source_role == "packing"
    assert values["gname"] == "贴纸"
    assert values["codeTs"] == "4821900000"
    assert values["declPrice"] == "0.0181"
    assert values["tradeCurr"] == "USD"
    assert all(field.evidence for field in first.fields.values())
