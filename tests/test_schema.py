from pathlib import Path

from docparse.schema.loader import load_layout_vocab, load_schema, load_sheet_roles

ROOT = Path(__file__).resolve().parents[1]

JSON_HEAD = {
    "cusIEFlag",
    "consignorEname",
    "agentCode",
    "agentName",
    "agentScc",
    "ownerCode",
    "ownerName",
    "ownerScc",
    "ownerCiqCode",
    "transMode",
    "contrNo",
    "cusTradeCountry",
    "cusTradeNationCode",
    "cutMode",
    "grossWt",
    "netWt",
    "cusTrafMode",
    "customMaster",
    "distinatePort",
    "entryType",
    "feeCurr",
    "feeMark",
    "feeRate",
    "insurCurr",
    "insurMark",
    "insurRate",
    "otherCurr",
    "otherMark",
    "otherRate",
    "manualNo",
    "markNo",
    "noteS",
    "promiseItems",
    "supvModeCdde",
    "wrapType",
    "tradeScc",
    "tradeCode",
    "tradeCiqCode",
    "tradeName",
    "packNo",
    "dataSource",
    "promiseItem1",
    "promiseItem2",
    "promiseItem3",
}

JSON_GOODS = {
    "gno",
    "codeTs",
    "gname",
    "gmodel",
    "declPrice",
    "declTotal",
    "tradeCurr",
    "gqty",
    "gunit",
    "qty1",
    "unit1",
    "qty2",
    "unit2",
    "cusOriginCountry",
    "destinationCountry",
    "districtCode",
    "dutyMode",
    "exgVersion",
    "customGrossWet",
    "customNetWt",
    "id",
    "brand",
}

MUST_HEAD = {
    "preEntryId",
    "entryId",
    "tradeName",
    "tradeCode",
    "iePort",
    "ieDate",
    "declDate",
    "manualNo",
    "consignorEname",
    "cusTrafMode",
    "trafName",
    "cusVoyageNo",
    "billNo",
    "goodsPlace",
    "ownerName",
    "ownerCode",
    "supvModeCdde",
    "licenseNo",
    "despPortCode",
    "contrNo",
    "cusTradeNationCode",
    "cusTradeCountry",
    "distinatePort",
    "ciqEntyPortCode",
    "wrapType",
    "packNo",
    "grossWt",
    "netWt",
    "transMode",
    "feeMark",
    "insurMark",
    "otherMark",
    "attachedDocs",
    "markNo",
    "noteS",
}

MUST_GOODS = {
    "gno",
    "codeTs",
    "gname",
    "gmodel",
    "brand",
    "gqty",
    "gunit",
    "declPrice",
    "declTotal",
    "tradeCurr",
    "cusOriginCountry",
    "destinationCountry",
    "districtCode",
}


def _all_names(schema) -> set[str]:
    names: set[str] = set()
    for collection in (
        schema.head,
        schema.goods,
        schema.caller_params,
        schema.ignored,
        schema.empty_arrays,
    ):
        names.update(item.name for item in collection)
    return names


def test_catalog_covers_json_and_must_items() -> None:
    schema = load_schema()
    names = _all_names(schema)
    assert not (JSON_HEAD - names), JSON_HEAD - names
    assert not (JSON_GOODS - names), JSON_GOODS - names
    assert not (MUST_HEAD - names), MUST_HEAD - names
    assert not (MUST_GOODS - names), MUST_GOODS - names
    assert schema.goods_array == "tdecGoodsitemsVoArr"
    assert schema.field("entryId") is not None
    assert "rule" in schema.field("entryId").extractors


def test_no_required_distinction_this_issue() -> None:
    schema = load_schema()
    for spec in [*schema.head, *schema.goods]:
        assert spec.required is False, spec.name


def test_head_map_split_and_skip() -> None:
    schema = load_schema()
    assert schema.field("tradeName").head_map == "trailing_code"
    assert schema.field("tradeCode").head_map == "skip"
    assert schema.field("ownerName").head_map == "trailing_code"
    assert schema.field("feeRate").head_map == "skip"
    assert schema.field("cusVoyageNo").head_map == "skip"
    assert schema.field("noteS").anchors == ["备注"]


def test_goods_map_flags_and_master_signals() -> None:
    schema = load_schema()
    assert schema.field("codeTs").goods_map == "leading_hs"
    assert schema.field("gmodel").goods_map == "raw_review"
    assert "重量KG" not in schema.field("qty1").anchors
    assert "重量KG" in schema.field("customNetWt").anchors
    assert "项目编号" in schema.field("codeTs").anchors
    assert "海关十位编码" in schema.field("codeTs").anchors
    assert "商品名称及商品规格" in schema.field("gname").anchors
    assert "币值" in schema.field("tradeCurr").anchors
    assert "最终目的地" in schema.field("destinationCountry").anchors
    fields = {item.field for item in schema.goods_master.signals}
    assert {"gno", "codeTs", "gname", "gqty", "declPrice", "cusOriginCountry"} <= fields
    assert schema.goods_master.role_bonus["draft"] > schema.goods_master.role_bonus["packing"]


def test_assembly_policy_is_role_based() -> None:
    schema = load_schema()
    policy = schema.assembly
    assert policy.primary_role == "draft"
    assert policy.fill["draft"] == "overwrite"
    assert policy.fill["packing"] == "fill"
    assert "packNo" in policy.reconcile
    assert "supvModeCdde" in policy.customs_only
    assert policy.weight.copy_net_to_gross is False
    assert policy.weight.net_as_weight is True
    assert policy.defaults["cusIEFlag"] == "E"
    assert "不把净重抄进本字段" in schema.field("grossWt").notes
    assert "视同重量" in schema.field("netWt").notes


def test_agent_fields_are_caller_params() -> None:
    schema = load_schema()
    by_name = {item.name: item for item in schema.caller_params}
    for name in ("agentCode", "agentName", "agentScc", "agentCiqCode"):
        spec = by_name[name]
        assert spec.parse is False
        assert spec.layout == "caller"
        assert spec.group == "caller"
        assert spec.default


def test_ignored_items_listed() -> None:
    schema = load_schema()
    names = {item.name for item in schema.ignored}
    assert {
        "dataSource",
        "promiseItem1",
        "promiseItem2",
        "promiseItem3",
        "sysBillNo",
        "ownerCompanyId",
        "requestId",
        "decId",
    } <= names
    assert "brand" not in names
    assert any(item.name == "id" and item.group == "goods" for item in schema.ignored)
    assert any(item.name == "headId" for item in schema.ignored)
    assert all(item.ignore and not item.parse for item in schema.ignored)


def test_port_mapping() -> None:
    schema = load_schema()
    by_label = {item.draft_label: item for item in schema.port_mapping}
    assert by_label["申报地海关"].field == "customMaster"
    assert by_label["出境关别"].field == "iePort"
    assert by_label["离境口岸"].field == "ciqEntyPortCode"
    assert by_label["指运港"].field == "distinatePort"
    assert {item.status for item in schema.port_mapping} == {"decided"}
    assert schema.field("iePort").layout == "box_kv"
    assert schema.field("customMaster").code_table == "海关口岸代码"
    assert schema.field("ciqEntyPortCode").code_table == "入境/离境口岸"


def test_layouts_answer_where_fields_come_from() -> None:
    schema = load_schema()
    allowed = {"box_kv", "table_col", "caller", "default", "none", "empty_array"}
    for spec in [*schema.head, *schema.goods, *schema.caller_params, *schema.empty_arrays]:
        assert spec.layout in allowed, spec.name
        assert spec.notes, spec.name
    assert schema.field("declDate").layout == "box_kv"
    assert schema.field("brand").layout == "table_col"
    assert schema.field("attachedDocs").layout == "box_kv"
    assert schema.field("tdecDocusVoArr").layout == "empty_array"
    assert schema.field("gmodel").layout == "table_col"
    assert schema.field("tdecContasVoArr").layout == "empty_array"


def test_layout_vocab_covers_issue_aliases() -> None:
    vocab = load_layout_vocab()
    box = vocab.box_labels()
    table = set(vocab.table_tokens())
    assert "毛重（千克）" in box
    assert "毛重" in box
    assert "货物存放地点" in box
    assert "启运港" in box
    assert "申报地海关" in box
    assert "G.W." not in box
    assert "N.W." not in box
    assert "物料名称" in table
    assert "出货数量" in table
    assert "Qty" in table
    assert "Q'ty" in table
    assert "N.W." in table
    assert "G.W." in table
    assert "G.W" in table
    assert "申报要素" in table
    assert "海关十位编码" in table
    assert "货物名称" in table
    assert "单位" not in table
    kv = vocab.kv_labels()
    assert "Invoice No." in kv
    assert "日期DATE" in kv
    assert "SHIPPED PER" in kv
    assert "Invoice No." not in box
    assert "G.W." not in kv
    assert all(
        alias.source for group in [*vocab.box, *vocab.kv, *vocab.table] for alias in group.aliases
    )
    ie_date = next(group for group in vocab.box if group.id == "ie_date")
    assert ie_date.value is not None
    assert ie_date.value.type == "datetime"
    invoice = next(group for group in vocab.kv if group.id == "invoice_no")
    assert invoice.value is not None
    assert invoice.value.type == "pattern"
    assert vocab.value_for_key("出口日期") is ie_date.value
    assert vocab.value_for_key("货物存放地点") is None
    assert vocab.group_for_key("Invoice No.") is invoice


def test_sheet_roles_cover_issue_roles() -> None:
    catalog = load_sheet_roles()
    by_id = {role.id: role for role in catalog.roles}
    assert set(by_id) == {"draft", "packing", "invoice", "contract", "auxiliary"}
    assert by_id["draft"].consume == "primary"
    assert {by_id[name].consume for name in ("packing", "invoice", "contract")} == {"supplement"}
    assert by_id["auxiliary"].consume == "exclude"
    assert catalog.unknown_consume == "exclude"
    titles = {signal.text for role in catalog.roles for signal in role.signals.titles}
    assert "一般贸易出口" in titles
    assert "PACKING LIST" in titles
    assert "SALES CONTRACT" in titles
    invoice = next(signal for signal in by_id["invoice"].signals.titles if signal.text == "INVOICE")
    assert invoice.match == "exact"


def test_customer_originals_not_in_repo() -> None:
    forbidden_names = (
        "（恒信）一般贸易草单HDX260251BLU.xlsx",
        "（国光）箱单发票合同26VN0502-1.xlsx",
        "基础报关参数数据.xlsx",
        "SJ25084373-310795HKD.pdf",
    )
    tracked = [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts
    ]
    names = {path.name for path in tracked}
    for name in forbidden_names:
        assert name not in names, name
    for path in tracked:
        if path.suffix.lower() in {".xlsx", ".xls", ".pdf", ".zip"}:
            raise AssertionError(f"binary original slipped in: {path}")
