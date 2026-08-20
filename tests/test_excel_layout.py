from __future__ import annotations

import io
from pathlib import Path

import pytest

pytest.importorskip("openpyxl")

from openpyxl import Workbook
from openpyxl.styles import Border, Side

from docparse.adapters.parsers.excel import parse_excel

REAL_HENGXIN = Path(
    "/Users/chenzecong/Documents/泰洲数据/AI识别Demo/AI识别Demo/"
    "（恒信）一般贸易草单HDX260251BLU.xlsx"
)


def _thin() -> Border:
    line = Side(style="thin")
    return Border(left=line, right=line, top=line, bottom=line)


def _box_workbook() -> bytes:
    book = Workbook()
    draft = book.active
    draft.title = "一般贸易出口"
    packing = book.create_sheet("装箱单")

    packing["G58"] = 40
    packing["I58"] = 296.46
    packing["H58"] = 218.375

    draft.merge_cells("A3:D3")
    draft["A3"] = "境内发货人"
    draft.merge_cells("A4:D4")
    draft["A4"] = "惠州市恒德信精密科技有限公司441394164D"

    draft["E3"] = "出境关别"
    draft["E4"] = "莲塘口岸"

    draft.merge_cells("A5:D5")
    draft["A5"] = "境外收货人"
    draft.merge_cells("A6:D6")
    draft["A6"] = "BLU PRECISION LIMITED"

    draft["E5"] = "运输方式"
    draft["E6"] = "公路运输"

    draft.merge_cells("A7:D7")
    draft["A7"] = "生产销售单位"
    draft.merge_cells("A8:D8")
    draft["A8"] = "惠州市恒德信精密科技有限公司"

    draft["E7"] = "监管方式"
    draft["E8"] = "一般贸易"
    draft.merge_cells("I7:J7")
    draft["I7"] = "征免性质"
    draft["I8"] = "一般征税"

    draft.merge_cells("A9:D9")
    draft["A9"] = "合同协议号"
    draft.merge_cells("A10:D10")
    draft["A10"] = "HDX2026-251"

    draft.merge_cells("A11:C11")
    draft["A11"] = "包装种类"
    draft["D11"] = "件数"
    draft["E11"] = "毛重（千克）"
    draft["F11"] = "净重（千克）"
    draft.merge_cells("G11:H11")
    draft["G11"] = "成交方式"

    draft.merge_cells("A12:C12")
    draft["A12"] = "其它"
    draft["D12"] = "=装箱单!G58"
    draft["E12"] = "=装箱单!I58"
    draft["F12"] = "=装箱单!H58"
    draft.merge_cells("G12:H12")
    draft["G12"] = "FOB"

    headers = [
        "项号",
        "商品编号",
        "商品名称及规格型号",
        "申报要素",
        "数量PCS",
        "计价单位",
        "重量KG",
        "单价",
        "总价",
    ]
    for col, header in enumerate(headers, start=1):
        draft.cell(17, col, header)
    draft["A18"] = 1
    draft["B18"] = "9111900000"
    draft["C18"] = "表壳配件/壳体"
    draft["D18"] = "不锈钢"
    draft["E18"] = 150
    draft["F18"] = "只"
    draft["G18"] = 5.74
    draft["H18"] = 98
    draft["I18"] = "=E18*H18"

    for row in draft.iter_rows(min_row=3, max_row=18, min_col=1, max_col=9):
        for cell in row:
            cell.border = _thin()

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _pairs(sheet) -> dict[str, str]:
    return {item.key: item.value for item in sheet.key_values}


def test_box_form_key_values_and_table() -> None:
    document = parse_excel(_box_workbook(), file_id="f1", filename="draft.xlsx")
    assert {sheet.name for sheet in document.sheets} == {"一般贸易出口", "装箱单"}
    draft = next(sheet for sheet in document.sheets if sheet.name == "一般贸易出口")
    pairs = _pairs(draft)

    assert pairs["境内发货人"] == "惠州市恒德信精密科技有限公司441394164D"
    assert pairs["境外收货人"] == "BLU PRECISION LIMITED"
    assert pairs["合同协议号"] == "HDX2026-251"
    assert pairs["运输方式"] == "公路运输"
    assert pairs["监管方式"] == "一般贸易"
    assert pairs["征免性质"] == "一般征税"
    assert pairs["件数"] == "40"
    assert pairs["毛重（千克）"] == "296.46"
    assert pairs["净重（千克）"] == "218.375"
    assert pairs["成交方式"] == "FOB"

    weight = next(cell for cell in draft.cells if cell.address == "E12")
    assert weight.formula == "=装箱单!I58"
    assert weight.value == "296.46"

    assert draft.tables
    table = draft.tables[0]
    assert "项号" in table.headers
    assert "商品编号" in table.headers
    assert table.rows[0]["项号"] == "1"
    assert table.rows[0]["商品编号"] == "9111900000"
    assert table.rows[0]["商品名称及规格型号"] == "表壳配件/壳体"
    assert table.rows[0]["总价"] == "14700"


@pytest.mark.skipif(not REAL_HENGXIN.exists(), reason="本地恒信样本不在 CI")
def test_hengxin_sample_keeps_formulas_and_goods_table() -> None:
    document = parse_excel(
        REAL_HENGXIN.read_bytes(),
        file_id="hx",
        filename=REAL_HENGXIN.name,
    )
    assert len(document.sheets) >= 4
    draft = next(sheet for sheet in document.sheets if "一般贸易" in sheet.name)
    pairs = _pairs(draft)
    assert pairs["合同协议号"] == "HDX2026-251"
    assert pairs["境外收货人"] == "BLU PRECISION LIMITED"
    assert pairs["出境关别"] == "莲塘口岸"
    assert pairs["离境口岸"] == "莲塘口岸"
    assert pairs["件数"] == "40"
    assert pairs["毛重（千克）"] == "296.46"
    assert draft.tables
    first = draft.tables[0].rows[0]
    assert first["项号"] == "1"
    assert first["商品编号"] == "9111900000"
