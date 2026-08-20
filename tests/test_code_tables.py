from pathlib import Path

import pytest

from docparse.schema.loader import CodeEntry, CodeTable, CodeTables, load_code_tables

ROOT = Path(__file__).resolve().parents[1]


def test_acceptance_names_map_to_codes() -> None:
    tables = load_code_tables()
    assert tables.lookup("运输方式", "公路运输") == "4"
    assert tables.lookup("成交方式", "FOB") == "3"
    assert tables.lookup("监管方式", "一般贸易") == "0110"


def test_unknown_name_returns_none() -> None:
    tables = load_code_tables()
    assert tables.lookup("运输方式", "火箭运输") is None
    assert tables.lookup("成交方式", "") is None
    assert tables.lookup("成交方式", None) is None
    assert tables.lookup("监管方式", " 一般贸易 ") == "0110"


def test_colloquial_names_not_aliased() -> None:
    tables = load_code_tables()
    assert tables.lookup("海关口岸代码", "莲塘口岸") is None
    assert tables.lookup("海关口岸代码", "莲塘海关") == "5354"
    assert tables.lookup("包装种类", "纸箱") is None
    assert tables.lookup("包装种类", "其他包装") == "99"


def test_customs_port_and_seaport_are_separate() -> None:
    tables = load_code_tables()
    assert "海关口岸代码" in tables.tables
    assert "港口代码" in tables.tables
    assert tables.lookup("海关口岸代码", "深惠州关") == "5341"
    assert tables.lookup("海关口岸代码", "梅沙海关") == "5352"
    assert tables.lookup("港口代码", "香港（中国香港）") == "HKG003"
    assert tables.lookup("港口代码", "中国香港") == "HKG000"
    assert tables.lookup("港口代码", "德国") == "DEU000"
    assert tables.lookup("港口代码", "北京天竺综合保税区") == "991101"
    assert tables.lookup("海关口岸代码", "香港（中国香港）") is None
    assert tables.lookup("港口代码", "深惠州关") is None


def test_known_customer_rows_and_pending_tables() -> None:
    tables = load_code_tables()
    assert tables.lookup("征免性质", "一般征税") == "101"
    assert tables.lookup("国别", "中国") == "CHN"
    assert tables.lookup("国别", "中国香港") == "HKG"
    assert tables.lookup("计量单位", "千克") == "035"
    assert tables.lookup("计量单位", "只") == "008"
    assert tables.lookup("征减免税方式", "照章征税") == "1"
    assert tables.lookup("国内地区", "惠州其他") == "44139"
    assert tables.reverse("运输方式", "4") == "公路运输"
    pending = {item.name for item in tables.pending}
    assert pending == {"币制", "报关单类型", "入境/离境口岸"}
    for name in pending:
        with pytest.raises(ValueError, match="unknown code table"):
            tables.lookup(name, "USD")


def test_unknown_table_raises() -> None:
    tables = load_code_tables()
    with pytest.raises(ValueError, match="unknown code table"):
        tables.lookup("不存在的表", "FOB")


def test_ambiguous_name_returns_none() -> None:
    tables = CodeTables(
        tables={
            "海关口岸代码": CodeTable(
                entries=[
                    CodeEntry(code="2206", name="邮局海关"),
                    CodeEntry(code="3713", name="邮局海关"),
                ]
            )
        }
    )
    assert tables.lookup("海关口岸代码", "邮局海关") is None
    assert tables.reverse("海关口岸代码", "2206") == "邮局海关"


def test_customer_original_xlsx_not_in_repo() -> None:
    names = {path.name for path in ROOT.rglob("*") if path.is_file()}
    assert "基础报关参数数据.xlsx" not in names
    assert "code_tables.yaml" in names
