from __future__ import annotations

from pathlib import Path

import pytest

from docparse.adapters.parsers.excel import parse_excel
from docparse.extraction.assemble import (
    assemble_declaration,
    declaration_payload,
    declaration_reviews,
)
from xlsx_fixtures import (
    _auxiliary,
    _draft,
    _invoice,
    _mismatch_packing,
    _net_only_packing,
    _packing,
    _workbook,
)

_DEMO = Path("/Users/baldwin/Desktop/taizhou/AI识别Demo")
REAL_HENGXIN = _DEMO / "（恒信）一般贸易草单HDX260251BLU.xlsx"
REAL_GUOGUANG = _DEMO / "（国光）箱单发票合同26VN0502-1.xlsx"


def _parse(builders: dict, filename: str):
    return parse_excel(_workbook(builders), file_id="asm", filename=filename)


def test_draft_is_copied_and_codes_are_looked_up() -> None:
    document = _parse(
        {"一般贸易出口": _draft, "装箱单": _packing, "Sheet3": _auxiliary},
        "hengxin.xlsx",
    )
    declaration = assemble_declaration(
        document,
        agent={"agentCode": "4403180867", "agentName": "深圳市泰洲物流有限公司"},
    )
    payload = declaration_payload(declaration)

    assert declaration.has_draft is True
    assert declaration.source_roles == ["draft", "packing"]
    assert payload["contrNo"] == "HDX2026-251"
    assert payload["consignorEname"] == "BLU PRECISION LIMITED"
    assert payload["packNo"] == "40"
    assert payload["grossWt"] == "296.46"
    assert payload["netWt"] == "218.375"
    assert payload["cusTrafMode"] == "4"
    assert payload["transMode"] == "3"
    assert payload["supvModeCdde"] == "0110"
    assert payload["cusIEFlag"] == "E"
    assert payload["agentCode"] == "4403180867"
    assert payload["agentName"] == "深圳市泰洲物流有限公司"
    assert payload["agentScc"] == ""
    assert payload["iePort"] == "莲塘口岸"
    assert declaration.head["iePort"].status.value == "needs_review"
    assert payload["wrapType"] == "其它"
    assert declaration.head["wrapType"].status.value == "needs_review"
    assert len(payload["tdecGoodsitemsVoArr"]) == 1
    goods = payload["tdecGoodsitemsVoArr"][0]
    assert goods["gno"] == "1"
    assert goods["gname"] == "表壳配件/壳体"
    assert goods["gunit"] == "008"
    assert goods["cusOriginCountry"] == "CHN"
    assert goods["destinationCountry"] == "HKG"
    assert goods["districtCode"] == "44139"
    assert payload["tdecContasVoArr"] == []
    assert payload["_meta"]["source_roles"] == ["draft", "packing"]
    assert "SHOULD-NOT-ASSEMBLE" not in payload.values()
    reviews = {item.path: item for item in declaration_reviews(declaration)}
    assert reviews["iePort"].status == "needs_review"
    assert any("unknown_code" in reason for reason in reviews["iePort"].reasons)
    assert reviews["iePort"].evidence


def test_caller_overrides_default_ie_flag() -> None:
    document = _parse({"一般贸易出口": _draft}, "draft-only.xlsx")
    payload = declaration_payload(assemble_declaration(document, agent={"cusIEFlag": "I"}))
    assert payload["cusIEFlag"] == "I"


def test_commercial_mismatch_keeps_draft_value() -> None:
    document = _parse({"一般贸易出口": _draft, "装箱单": _mismatch_packing}, "mismatch.xlsx")
    declaration = assemble_declaration(document)
    assert declaration.value_of("packNo") == "40"
    assert declaration.head["packNo"].status.value == "needs_review"
    assert "packNo:head_mismatch" in declaration.review_reasons


def test_net_only_does_not_copy_to_gross() -> None:
    document = _parse({"总箱单": _net_only_packing}, "net-only.xlsx")
    declaration = assemble_declaration(document)
    assert declaration.has_draft is False
    assert declaration.value_of("netWt") == "2825.47"
    assert declaration.value_of("grossWt") in {None, ""}
    assert declaration.head["grossWt"].status.value == "needs_review"
    assert "grossWt:net_is_not_gross" in declaration.review_reasons
    payload = declaration_payload(declaration)
    assert payload["grossWt"] == ""
    assert payload["netWt"] == "2825.47"
    assert payload["supvModeCdde"] == ""
    assert payload["cutMode"] == ""
    assert payload["iePort"] == ""
    assert "supvModeCdde:customs_empty" in declaration.review_reasons


def test_no_draft_fills_commercial_and_leaves_customs_empty() -> None:
    document = _parse(
        {"总箱单": _net_only_packing, "发票": _invoice, "Sheet3": _auxiliary},
        "guoguang.xlsx",
    )
    declaration = assemble_declaration(document)
    payload = declaration_payload(declaration)
    assert declaration.has_draft is False
    assert payload["contrNo"] == "26VN0502"
    assert payload["consignorEname"] == "GUOGUANG ACOUSTICS (VIETNAM) COMPANY LIMITED"
    assert payload["tradeName"] == "GUOGUANG ELECTRIC COMPANY LIMITED."
    assert payload["supvModeCdde"] == ""
    assert payload["cutMode"] == ""
    assert payload["customMaster"] == ""
    assert payload["wrapType"] == ""
    assert payload["agentCode"] == ""
    assert len(payload["tdecGoodsitemsVoArr"]) == 1
    assert payload["tdecGoodsitemsVoArr"][0]["gname"] == "贴纸"
    assert payload["tdecGoodsitemsVoArr"][0]["gqty"] == "100"
    assert "SHOULD-NOT-ASSEMBLE" not in payload.values()
    assert "auxiliary" not in declaration.source_roles


def test_agent_not_taken_from_file() -> None:
    document = _parse({"一般贸易出口": _draft}, "draft-only.xlsx")
    declaration = assemble_declaration(document)
    assert declaration.value_of("agentCode") is None
    assert declaration.value_of("agentName") is None


@pytest.mark.skipif(not REAL_HENGXIN.exists(), reason="本地恒信样本不在 CI")
def test_hengxin_sample_one_declaration() -> None:
    document = parse_excel(
        REAL_HENGXIN.read_bytes(),
        file_id="hx-real",
        filename=REAL_HENGXIN.name,
    )
    payload = declaration_payload(assemble_declaration(document))
    assert payload["contrNo"] == "HDX2026-251"
    assert payload["packNo"] == "40"
    assert payload["grossWt"] == "296.46"
    assert payload["transMode"] == "3"
    assert payload["cusTrafMode"] == "4"
    assert payload["supvModeCdde"] == "0110"
    assert len(payload["tdecGoodsitemsVoArr"]) >= 1
    assert payload["tdecGoodsitemsVoArr"][0]["gname"]


@pytest.mark.skipif(not REAL_GUOGUANG.exists(), reason="本地国光样本不在 CI")
def test_guoguang_sample_one_declaration() -> None:
    document = parse_excel(
        REAL_GUOGUANG.read_bytes(),
        file_id="gg-real",
        filename=REAL_GUOGUANG.name,
    )
    payload = declaration_payload(assemble_declaration(document))
    assert payload["contrNo"] == "26VN0502"
    assert payload["consignorEname"] == "GUOGUANG ACOUSTICS (VIETNAM) COMPANY LIMITED"
    assert payload["supvModeCdde"] == ""
    assert payload["cutMode"] == ""
    assert len(payload["tdecGoodsitemsVoArr"]) >= 1
    assert payload["tdecGoodsitemsVoArr"][0]["gname"]
