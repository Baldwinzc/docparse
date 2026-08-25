from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("xlrd")

from docparse.adapters.parsers.detect import SourceKind, detect_kind
from docparse.adapters.parsers.excel import parse_excel
from docparse.adapters.parsers.registry import parse_bytes
from xls_fixtures import _label, _number, build_xls, draft_xls

_SAMPLES = Path("/Users/baldwin/Desktop/taizhou/补充测试")
REAL_DONNELLY = _SAMPLES / "202606 R26JU551-Y报关一般.xls"
REAL_DUOKE = _SAMPLES / "6-17 多科报关资料香港出货 DKTX-2606057 多科通讯乐乐高(1).xls"


def _pairs(sheet) -> dict[str, str]:
    return {item.key: item.value for item in sheet.key_values}


def test_ole2_magic_with_xls_suffix_routes_to_excel() -> None:
    data = draft_xls()
    assert data.startswith(b"\xd0\xcf\x11\xe0")
    assert detect_kind("report.xls", data) is SourceKind.EXCEL


def test_registry_parses_ole2_xls_without_zip_error() -> None:
    document = parse_bytes(draft_xls(), file_id="f1", filename="report.xls")
    assert not document.warnings
    assert {sheet.name for sheet in document.sheets} == {"报关单一般贸易", "发票"}


def test_xls_layout_key_values_and_table() -> None:
    document = parse_excel(draft_xls(), file_id="f1", filename="report.xls")
    assert not document.warnings
    draft = next(sheet for sheet in document.sheets if sheet.name == "报关单一般贸易")
    pairs = _pairs(draft)

    assert pairs["境内发货人"] == "深圳市多科通讯有限公司"
    assert pairs["出口口岸"] == "深圳湾"
    assert pairs["出口日期"] == "2026-06-17 00:00:00"
    assert pairs["运输方式"] == "公路运输"
    assert pairs["件数"] == "40"

    merged = next(cell for cell in draft.cells if cell.address == "A3")
    assert merged.merge_range == "A3:C3"
    assert all(cell.address != "B3" for cell in draft.cells)

    assert draft.tables
    table = draft.tables[0]
    assert table.header_row == 8
    assert "项号" in table.headers
    assert "商品编号" in table.headers
    first = table.rows[0]
    assert first["项号"] == "1"
    assert first["商品编号"] == "4821900000"
    assert first["商品名称及规格型号"] == "标签"
    assert first["数量"] == "100"


def test_xls_date_serial_and_float_shapes() -> None:
    body = (
        _label(0, 0, "出口日期")
        + _number(0, 1, 46190.0, xf=1)
        + _number(0, 2, 218.375)
        + _number(0, 3, 1.81)
    )
    document = parse_excel(build_xls([("S", body)]), file_id="f1", filename="a.xls")
    sheet = document.sheets[0]
    values = {cell.address: cell.value for cell in sheet.cells}
    assert values["B1"] == "2026-06-17 00:00:00"
    assert values["C1"] == "218.375"
    assert values["D1"] == "1.81"


def test_xls_missing_xlrd_registers_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "xlrd", None)
    document = parse_excel(draft_xls(), file_id="f1", filename="report.xls")
    assert not document.sheets
    assert any("xlrd" in warning for warning in document.warnings)


@pytest.mark.skipif(not REAL_DONNELLY.exists(), reason="本地当纳利样本不在 CI")
def test_real_donnelly_xls_layout_reads_in() -> None:
    document = parse_bytes(
        REAL_DONNELLY.read_bytes(),
        file_id="dn",
        filename=REAL_DONNELLY.name,
    )
    assert not document.warnings
    assert document.sheets
    assert {sheet.name for sheet in document.sheets} == {
        "装 箱 单",
        "报关预录入单",
        "出口发票",
        "销售合同",
    }
    draft = next(sheet for sheet in document.sheets if sheet.name == "报关预录入单")
    assert len(draft.cells) > 50
    assert draft.key_values


@pytest.mark.skipif(not REAL_DUOKE.exists(), reason="本地多科样本不在 CI")
def test_real_duoke_xls_export_date_serial_becomes_datetime() -> None:
    document = parse_bytes(
        REAL_DUOKE.read_bytes(),
        file_id="dk",
        filename=REAL_DUOKE.name,
    )
    assert not document.warnings
    draft = next(sheet for sheet in document.sheets if sheet.name == "报关单一般贸易")
    pairs = _pairs(draft)
    assert pairs["出口日期"] == "2026-06-17 00:00:00"
    assert pairs["出口口岸"] == "深圳湾"
