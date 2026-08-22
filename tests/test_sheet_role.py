from __future__ import annotations

import io
from pathlib import Path

import pytest

pytest.importorskip("openpyxl")

from openpyxl import Workbook
from openpyxl.styles import Border, Side

from docparse.adapters.parsers.excel import parse_excel
from docparse.schema.loader import load_sheet_roles

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
    sheet["A17"] = "项号"
    sheet["B17"] = "商品编号"
    sheet["C17"] = "商品名称及规格型号"
    sheet["D17"] = "申报要素"
    sheet["A18"] = 1
    sheet["B18"] = "9111900000"
    sheet["C18"] = "壳体"
    sheet["D18"] = "不锈钢"
    for row in sheet.iter_rows(min_row=1, max_row=18, min_col=1, max_col=4):
        for cell in row:
            cell.border = _thin()


def _packing(sheet) -> None:
    sheet["A1"] = "PACKING LIST"
    sheet["I4"] = "Invoice No.﹕"
    sheet["J4"] = "HDX260251"
    sheet["A7"] = "Bill To : BLU PRECISION LIMITED"
    sheet["C11"] = "Description (货物名称)"
    sheet["E11"] = "Ship Q'ty (数量/PCS)"
    sheet["H11"] = "N.W. (Kg) (净重)"
    sheet["I11"] = "G.W .(Kg) (毛重)"
    sheet["C12"] = "壳体"
    sheet["E12"] = 150
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
    sheet["F16"] = "单价"
    sheet["G16"] = "汇总价"
    sheet["B17"] = "贴纸"
    sheet["D17"] = 100
    for row in sheet.iter_rows(min_row=1, max_row=17, min_col=1, max_col=7):
        for cell in row:
            cell.border = _thin()


def _contract(sheet) -> None:
    sheet["C1"] = "合     同"
    sheet["C2"] = "SALES CONTRACT"
    sheet["A5"] = "卖 方:"
    sheet["B5"] = "示例卖方"
    sheet["A8"] = "买 方:"
    sheet["B8"] = "示例买方"
    sheet["F6"] = "合同号："
    sheet["G6"] = "HDX2026-251"
    sheet["A14"] = "(1)货物名称"
    sheet["C14"] = "(3)数量"
    sheet["F14"] = "(6)总值"
    sheet["A15"] = "Description"
    sheet["C15"] = "Quantity"
    sheet["F15"] = "Total Amount(HKD)"
    sheet["A16"] = 1
    sheet["C16"] = 150
    sheet["F16"] = 14700
    for row in sheet.iter_rows(min_row=1, max_row=16, min_col=1, max_col=7):
        for cell in row:
            cell.border = _thin()


def _code_lookup(sheet) -> None:
    sheet["C2"] = "BLU PRECISION LIMITED"
    sheet["G2"] = "005"
    sheet["C3"] = "TIME INVENTION LIMITED"
    sheet["G3"] = "006"
    sheet["C4"] = "HANSON PRECISION TECHNOLOGY LIMITED"
    sheet["G4"] = "002"


def _internal_sku(sheet) -> None:
    sheet["B1"] = "编号"
    sheet["C1"] = "货物名称"
    sheet["E1"] = "恒信编号"
    sheet["F1"] = "数量"
    sheet["O1"] = "ERP编号"
    sheet["B2"] = "D001"
    sheet["C2"] = "表殻殻身"
    sheet["E2"] = "HNC3591GA"
    sheet["F2"] = 150
    for row in sheet.iter_rows(min_row=1, max_row=2, min_col=2, max_col=15):
        for cell in row:
            cell.border = _thin()


def _history_ledger(sheet) -> None:
    sheet["A1"] = "序号"
    sheet["B1"] = "报关日期"
    sheet["C1"] = "报关单号"
    sheet["H1"] = "商品编码"
    sheet["K1"] = "SAP编号"
    sheet["M1"] = "商品名称"
    sheet["A2"] = 1
    sheet["C2"] = "E123"
    sheet["H2"] = "9111900000"
    for row in sheet.iter_rows(min_row=1, max_row=2, min_col=1, max_col=13):
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
    sheet["B12"] = "物料名称"
    sheet["D12"] = "出货数量"
    sheet["F12"] = "总箱数"
    sheet["H12"] = "总净重 NW"
    sheet["J12"] = "总毛重 GW"
    sheet["B13"] = "贴纸"
    sheet["D13"] = 100
    for row in sheet.iter_rows(min_row=5, max_row=13, min_col=1, max_col=10):
        for cell in row:
            cell.border = _thin()


def _notes(sheet) -> None:
    sheet["A1"] = "临时备注"
    sheet["A2"] = "今天对一下件数"
    sheet["A3"] = "不要当箱单"


def _roles(document) -> dict[str, str]:
    return {sheet.name: sheet.role for sheet in document.sheets}


def test_sheet_roles_catalog_loads() -> None:
    catalog = load_sheet_roles()
    assert {role.id for role in catalog.roles} == {
        "draft",
        "packing",
        "invoice",
        "contract",
        "auxiliary",
    }
    assert catalog.role("draft").consume == "primary"
    assert catalog.role("packing").consume == "supplement"
    assert catalog.role("auxiliary").consume == "exclude"
    assert catalog.unknown_consume == "exclude"
    assert all(
        signal.source
        for role in catalog.roles
        for group in (
            role.signals.titles,
            role.signals.keys,
            role.signals.headers,
            role.signals.filename,
        )
        for signal in group
    )


def test_fixture_covers_hengxin_seven_roles() -> None:
    document = parse_excel(
        _workbook(
            {
                "一般贸易出口": _draft,
                "裝箱單": _packing,
                "发票": _invoice,
                "合同": _contract,
                "Sheet1": _code_lookup,
                "1": _internal_sku,
                "Sheet3": _history_ledger,
            }
        ),
        file_id="hx",
        filename="hengxin-fixture.xlsx",
    )
    assert _roles(document) == {
        "一般贸易出口": "draft",
        "裝箱單": "packing",
        "发票": "invoice",
        "合同": "contract",
        "Sheet1": "auxiliary",
        "1": "auxiliary",
        "Sheet3": "auxiliary",
    }
    consume = {sheet.name: sheet.consume for sheet in document.sheets}
    assert consume["一般贸易出口"] == "primary"
    assert consume["裝箱單"] == "supplement"
    assert consume["Sheet1"] == "exclude"
    leftover = next(sheet for sheet in document.sheets if sheet.name == "Sheet1")
    assert leftover.cells
    assert leftover.role == "auxiliary"


def test_fixture_covers_guoguang_packing_and_invoice() -> None:
    document = parse_excel(
        _workbook({"总箱单": _guoguang_packing, "发票 ": _invoice}),
        file_id="gg",
        filename="guoguang-fixture.xlsx",
    )
    assert _roles(document) == {"总箱单": "packing", "发票 ": "invoice"}
    packing = next(sheet for sheet in document.sheets if sheet.name == "总箱单")
    assert packing.consume == "supplement"


def test_nameless_sheet_still_classifies_from_content() -> None:
    document = parse_excel(
        _workbook({"Sheet1": _draft, "工作表2": _packing}),
        file_id="anon",
        filename="untitled.xlsx",
    )
    assert _roles(document) == {"Sheet1": "draft", "工作表2": "packing"}


def test_filename_alone_does_not_route() -> None:
    document = parse_excel(
        _workbook({"Sheet2": _notes}),
        file_id="fn",
        filename="一般贸易草单箱单发票合同.xlsx",
    )
    notes = document.sheets[0]
    assert notes.role == "unknown"
    assert notes.consume == "exclude"
    assert any(cell.value == "临时备注" for cell in notes.cells)


def test_unknown_keeps_cells() -> None:
    document = parse_excel(
        _workbook({"备注": _notes}),
        file_id="unk",
        filename="notes.xlsx",
    )
    sheet = document.sheets[0]
    assert sheet.role == "unknown"
    assert sheet.consume == "exclude"
    assert any(cell.value == "临时备注" for cell in sheet.cells)


@pytest.mark.skipif(not REAL_HENGXIN.exists(), reason="本地恒信样本不在 CI")
def test_hengxin_sample_roles() -> None:
    document = parse_excel(
        REAL_HENGXIN.read_bytes(),
        file_id="hx-real",
        filename=REAL_HENGXIN.name,
    )
    roles = _roles(document)
    assert roles["一般贸易出口"] == "draft"
    assert any(name in {"裝箱單", "装箱单"} and role == "packing" for name, role in roles.items())
    assert any("发票" in name and role == "invoice" for name, role in roles.items())
    assert roles["合同"] == "contract"
    auxiliaries = [name for name, role in roles.items() if role == "auxiliary"]
    assert len(auxiliaries) == 3


@pytest.mark.skipif(not REAL_GUOGUANG.exists(), reason="本地国光样本不在 CI")
def test_guoguang_sample_roles() -> None:
    document = parse_excel(
        REAL_GUOGUANG.read_bytes(),
        file_id="gg-real",
        filename=REAL_GUOGUANG.name,
    )
    roles = _roles(document)
    assert roles["总箱单"] == "packing"
    invoice = next(name for name in roles if "发票" in name)
    assert roles[invoice] == "invoice"
