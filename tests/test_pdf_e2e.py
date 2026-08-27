"""#23 PDF 伪 sheet 接入同一套抽取 / 组装 / 校验。

夹具程序造，不含客户数据。半岛关键表头用 #60 参照数字自造，
境外发货人用 NORTHWIND，不把客户原件写进仓库。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from docparse.adapters.files.memory import MemoryFileStore
from docparse.adapters.jobs.memory import MemoryJobStore
from docparse.adapters.parsers.ocr import OcrLine, OcrOutcome
from docparse.adapters.parsers.ocr_layout import reconstruct_document
from docparse.config import Settings, get_settings
from docparse.domain.ir import BoundingBox, DocumentIR, Page, TextBlock
from docparse.extraction.assemble import assemble_declaration, declaration_payload
from docparse.pipeline.runner import Pipeline
from docparse.schema.loader import load_schema
from test_ocr_layout import peninsula_like_blocks, peninsula_like_document
from test_pdf_ocr import make_jpeg, make_text_pdf

_DEMO = Path("/Users/baldwin/Desktop/taizhou/AI识别Demo")
REAL_PENINSULA = _DEMO / "SJ25084373-310795HKD.pdf"

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
    return [
        _block(f"{prefix}k", key, x, y, x + key_w, y + h),
        _block(f"{prefix}v", value, x, y + gap, x + val_w, y + gap + h),
    ]


def _goods_header(y: float) -> list[TextBlock]:
    return [
        _block(f"h-{name}", name, x0, y, x1, y + 24) for name, (x0, x1) in _TABLE_XS.items()
    ]


def _goods_row(
    index: int,
    gno: str,
    hs: str,
    name: str,
    qty: str,
    price: str,
    total: str,
    origin: str,
    y: float,
) -> list[TextBlock]:
    values = {
        "项号": gno,
        "商品编号": hs,
        "商品名称及规格型号": name,
        "数量": qty,
        "单价": price,
        "总价": total,
        "原产国": origin,
    }
    blocks: list[TextBlock] = []
    for col, text in values.items():
        x0, x1 = _TABLE_XS[col]
        blocks.append(_block(f"g{index}-{col}", text, x0, y, x1, y + 22))
    return blocks


def two_page_draft_document() -> DocumentIR:
    """第 1 页表头 + 项号 1–2；第 2 页续表项号 3。数字自造。"""
    page1: list[TextBlock] = [
        _block("t1", "中华人民共和国海关出口货物报关单", 40, 20, 520, 48),
    ]
    page1.extend(_kv_pair("man", "备案号", "T0000W000001", x=40, y=70, val_w=140))
    page1.extend(
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
    page1.extend(_kv_pair("pk", "件数", "214", x=40, y=150, key_w=50, val_w=60))
    page1.extend(_kv_pair("gw", "毛重", "1459.62", x=160, y=150, key_w=50, val_w=80))
    page1.extend(_kv_pair("nw", "净重", "485", x=280, y=150, key_w=50, val_w=60))
    header_y = 260.0
    page1.extend(_goods_header(header_y))
    page1.extend(
        _goods_row(
            1, "1", "1905310000", "黄油酥饼", "120", "1.2", "144", "中国", header_y + _ROW_H
        )
    )
    page1.extend(
        _goods_row(
            2, "2", "1905900000", "巧克力派", "80", "2.5", "200", "中国", header_y + 2 * _ROW_H
        )
    )

    page2: list[TextBlock] = [
        _block("t2", "中华人民共和国海关出口货物报关单", 40, 20, 520, 48),
    ]
    page2.extend(_goods_header(80.0))
    page2.extend(
        _goods_row(3, "3", "1806320000", "夹心饼干", "14", "3.1", "43.4", "中国", 80.0 + _ROW_H)
    )

    return DocumentIR(
        document_id="d-two",
        file_id="f-two",
        filename="scan.pdf",
        media_type="application/pdf",
        pages=[
            Page(page_number=1, width=1200, height=800, blocks=page1),
            Page(page_number=2, width=1200, height=800, blocks=page2),
        ],
        raw_text="",
    )


def coded_box_document() -> DocumentIR:
    """包装种类（22）横排标签 + 下一行取值，应走 KV 不当商品表。"""
    blocks: list[TextBlock] = [
        _block("t1", "中华人民共和国海关出口货物报关单", 40, 20, 520, 48),
        _block("k1", "包装种类（22）", 40, 150, 140, 172),
        _block("k2", "件数", 180, 150, 230, 172),
        _block("k3", "毛重（千克）", 280, 150, 380, 172),
        _block("k4", "净重（千克）", 420, 150, 520, 172),
        _block("k5", "成交方式", 560, 150, 640, 172),
        _block("v1", "纸箱", 40, 180, 100, 202),
        _block("v2", "214", 180, 180, 230, 202),
        _block("v3", "1459.62", 280, 180, 360, 202),
        _block("v4", "485", 420, 180, 480, 202),
        _block("v5", "FOB", 560, 180, 610, 202),
    ]
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
    header_y = 280.0
    blocks.extend(_goods_header(header_y))
    blocks.extend(
        _goods_row(1, "1", "1905310000", "黄油酥饼", "120", "1.2", "144", "中国", header_y + _ROW_H)
    )
    return DocumentIR(
        document_id="d-box",
        file_id="f-box",
        filename="scan.pdf",
        media_type="application/pdf",
        pages=[Page(page_number=1, width=1200, height=800, blocks=blocks)],
        raw_text="",
    )


def _payload(document: DocumentIR) -> dict:
    rebuilt = reconstruct_document(document)
    return declaration_payload(assemble_declaration(rebuilt))


# 标准报关单商品表（#84）：一项目三物理行，复合列按行分布。
# x 坐标取自真机样本：品名字块落编号列 / 名称列两个方向都造。
_COMPOUND_HEADER_XS = {
    "项号": (39, 58),
    "商品编号": (64.5, 99),
    "商品名称及规格型号": (173, 242.5),
    "数量及单位": (340.5, 382),
    "单价／总价／币制": (427.5, 483),
    "原产国（地区）": (508, 554.5),
    "最终目的国（地区）": (573.5, 635),
    "境内目的地": (698.5, 739.5),
}


def compound_goods_document() -> DocumentIR:
    """item1 品名粘块落名称列（58-214）；item2 落编号列（58-172，漂移方向）。"""
    blocks: list[TextBlock] = [
        _block("t", "中华人民共和国海关进境货物备案清单", 266.5, 34.0, 573.5, 56.0),
        _block("man", "备案号：T5352W000228", 37.5, 72.5, 168.0, 84.5),
        _block("ent", "海关编号：535220251520029355", 255.0, 72.5, 378.0, 84.5),
    ]
    header_y = 274.0
    for name, (x0, x1) in _COMPOUND_HEADER_XS.items():
        blocks.append(_block(f"h-{name}", name, x0, header_y, x1, header_y + 12))

    def row(y: float, cells: list[tuple[str, float, float]]) -> None:
        for index, (text, x0, x1) in enumerate(cells):
            blocks.append(_block(f"r{y:.0f}-{index}", text, x0, y, x1, y + 12))

    # item 1（y 288/299/310）：HS+品名 58-214 → 名称列
    row(
        288,
        [
            ("1", 35, 43),
            ("1905310000示例黄油酥饼（饼干）", 58, 214),
            ("48千克", 384, 415),
            ("66.8300", 464, 499),
            ("英国", 547, 568),
            ("中国", 624, 644),
            ("（44536／440308）示例综合保税区", 651, 797),
        ],
    )
    row(
        299,
        [
            ("4｜3｜示例成分44％，示例油脂33％", 104, 310),
            ("16039.20", 461, 498),
            ("(GBR)", 544, 566),
            ("(CHN)", 619, 643),
            ("（一期）／示例区", 703, 798),
        ],
    )
    row(
        310,
        [
            ("糖17％｜200克X30盒／箱", 104, 224),
            ("240盒", 388, 415),
            ("港币", 478, 498),
        ],
    )
    # item 2（y 320/331/342）：HS+品名 58-172 → 编号列（列漂移另一方向）
    row(
        320,
        [
            ("2", 35, 43),
            ("1905900000示例巧克力曲奇", 58, 172),
            ("24千克", 374, 415),
            ("76.8800", 464, 498),
            ("英国", 546, 568),
            ("中国", 623, 644),
            ("（44536／440308）示例综合保税区", 651, 797),
        ],
    )
    row(
        331,
        [
            ("4｜3｜示例可可45％", 104, 224),
            ("9225.60", 464, 498),
            ("(GBR)", 544, 566),
            ("(CHN)", 619, 643),
            ("（一期）／示例区", 703, 798),
        ],
    )
    # 规格单行 item：行C 只有成交数量 + 币制（无身份列，靠 #84 兜底并入）
    row(
        342,
        [
            ("120盒", 389, 414),
            ("港币", 477, 498),
        ],
    )
    return DocumentIR(
        document_id="d-compound",
        file_id="f-compound",
        filename="compound.pdf",
        media_type="application/pdf",
        pages=[Page(page_number=1, width=800, height=400, blocks=blocks)],
        raw_text="",
    )


def test_compound_three_row_goods_through_ocr_layout() -> None:
    """OCR 几何全链路：三行一项目 + 复合列 + 品名粘块双向列漂移。"""
    payload = _payload(compound_goods_document())
    goods = payload["tdecGoodsitemsVoArr"]
    assert len(goods) == 2
    first, second = goods
    # item1：HS 从名称列粘块拆出；规格两行无缝拼接
    assert first["codeTs"] == "1905310000"
    assert first["gname"] == "示例黄油酥饼（饼干）"
    assert first["gmodel"] == "4｜3｜示例成分44％，示例油脂33％糖17％｜200克X30盒／箱"
    assert first["qty1"] == "48"
    assert first["unit1"] == "千克"
    assert first["customNetWt"] == "48"
    assert first["gqty"] == "240"
    assert first["gunit"] == "盒"
    assert first["declPrice"] == "66.8300"
    assert first["declTotal"] == "16039.20"
    assert first["tradeCurr"] == "港币"
    assert first["cusOriginCountry"] == "英国"
    assert first["destinationCountry"] == "中国"
    assert first["districtCode"] == "44536"
    assert first["ciqDestCode"] == "440308"
    # item2：HS+品名落编号列，split_target 拆给 gname；行C 无身份靠兜底并入
    assert second["codeTs"] == "1905900000"
    assert second["gname"] == "示例巧克力曲奇"
    assert second["gmodel"] == "4｜3｜示例可可45％"
    assert second["gqty"] == "120"
    assert second["gunit"] == "盒"
    assert second["qty1"] == "24"
    assert second["tradeCurr"] == "港币"
    assert second["declTotal"] == "9225.60"


def test_peninsula_like_declaration_shape() -> None:
    payload = _payload(peninsula_like_document())
    schema = load_schema()
    for spec in schema.head:
        assert spec.name in payload
    assert schema.goods_array in payload
    assert payload["manualNo"] == "T0000W000001"
    assert payload["consignorEname"] == "NORTHWIND TRADING LIMITED"
    assert payload["packNo"] == "214"
    assert payload["grossWt"] == "1459.62"
    assert payload["netWt"] == "485"
    goods = payload[schema.goods_array]
    assert len(goods) == 3
    assert goods[0]["gno"] == "1"
    assert goods[0]["codeTs"] == "1905310000"
    assert "黄油酥饼" in goods[0]["gname"]
    assert payload["_meta"]["has_draft"] is True


def test_coded_box_labels_map_pack_gross_net() -> None:
    payload = _payload(coded_box_document())
    assert payload["packNo"] == "214"
    assert payload["grossWt"] == "1459.62"
    assert payload["netWt"] == "485"
    assert payload["wrapType"] == "纸箱"
    assert payload["transMode"] == "FOB"
    assert payload["consignorEname"] == "NORTHWIND TRADING LIMITED"
    assert len(payload["tdecGoodsitemsVoArr"]) == 1


def test_two_page_draft_concatenates_goods_and_keeps_first_head() -> None:
    payload = _payload(two_page_draft_document())
    assert payload["manualNo"] == "T0000W000001"
    assert payload["consignorEname"] == "NORTHWIND TRADING LIMITED"
    assert payload["packNo"] == "214"
    goods = payload["tdecGoodsitemsVoArr"]
    assert [item["gno"] for item in goods] == ["1", "2", "3"]
    assert goods[2]["gname"] == "夹心饼干"


def _pipeline() -> Pipeline:
    settings = Settings(job_store="memory", file_store="memory", llm_api_key="")
    return Pipeline(settings=settings, jobs=MemoryJobStore(), files=MemoryFileStore())


def test_text_layer_pdf_pipeline_returns_declaration() -> None:
    pytest.importorskip("pymupdf")
    job = _pipeline().process("a.pdf", make_text_pdf())
    assert job.status.value != "failed"
    assert job.result is not None
    declaration = job.result.declaration
    assert declaration is not None
    schema = load_schema()
    for spec in schema.head:
        assert spec.name in declaration
    assert schema.goods_array in declaration


def test_api_upload_pdf_same_shape_as_xlsx() -> None:
    pytest.importorskip("pymupdf")
    from fastapi.testclient import TestClient

    from docparse.api.app import create_app
    from docparse.api.routes import get_pipeline

    pipeline = _pipeline()
    app = create_app()
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    response = TestClient(app).post(
        "/v1/jobs",
        files={"file": ("a.pdf", io.BytesIO(make_text_pdf()), "application/pdf")},
        data={"agentCode": "4403180867", "agentName": "深圳市泰洲物流有限公司"},
    )
    assert response.status_code == 200
    body = response.json()
    declaration = body["result"]["declaration"]
    assert "contrNo" in declaration
    assert "tdecGoodsitemsVoArr" in declaration
    assert declaration["agentCode"] == "4403180867"
    assert "_meta" in declaration
    assert "reviews" in body["result"]


def test_api_upload_png_same_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pymupdf")
    from fastapi.testclient import TestClient

    from docparse.api.app import create_app
    from docparse.api.routes import get_pipeline

    class _Ocr:
        def read_image(self, data: bytes, *, filename: str) -> OcrOutcome:
            return OcrOutcome(
                lines=[
                    OcrLine(
                        text=block.text,
                        x0=block.bbox.x0,
                        y0=block.bbox.y0,
                        x1=block.bbox.x1,
                        y1=block.bbox.y1,
                        score=0.98,
                    )
                    for block in peninsula_like_blocks()
                    if block.bbox is not None
                ],
                width=1200,
                height=800,
            )

    monkeypatch.setattr(
        "docparse.pipeline.steps.extract_content.get_ocr_client",
        lambda settings=None: _Ocr(),
    )
    pipeline = _pipeline()
    app = create_app()
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    response = TestClient(app).post(
        "/v1/jobs",
        files={"file": ("scan.png", io.BytesIO(make_jpeg()), "image/png")},
    )
    assert response.status_code == 200
    declaration = response.json()["result"]["declaration"]
    assert declaration is not None
    assert declaration["manualNo"] == "T0000W000001"
    assert declaration["consignorEname"] == "NORTHWIND TRADING LIMITED"
    assert declaration["packNo"] == "214"
    assert "tdecGoodsitemsVoArr" in declaration
    assert len(declaration["tdecGoodsitemsVoArr"]) == 3


def _has_textin() -> bool:
    settings = get_settings()
    return bool(settings.textin_app_id and settings.textin_secret_code)


@pytest.mark.skipif(
    not REAL_PENINSULA.exists() or not _has_textin(),
    reason="本地半岛样本 + TextIn 密钥才跑，客户原件不入库",
)
def test_peninsula_sample_key_head_fields() -> None:
    """本地真机：关键表头对 #60；对不上 needs_review，不编造。"""
    job = _pipeline().process(REAL_PENINSULA.name, REAL_PENINSULA.read_bytes())
    assert job.status.value != "failed"
    payload = job.result.declaration if job.result else None
    assert payload is not None
    expected = {
        "grossWt": "1459.62",
        "netWt": "485",
        "packNo": "214",
        "manualNo": "T5352W000228",
        "consignorEname": "Peninsula Merchandising Limited",
    }
    for name, value in expected.items():
        got = (payload.get(name) or "").strip()
        if got:
            assert got == value, f"{name}: got {got!r} expected {value!r}"
        else:
            reasons = payload.get("_meta", {}).get("review_reasons") or []
            assert any(name in reason for reason in reasons) or job.status.value == "needs_review"
    goods = payload.get("tdecGoodsitemsVoArr") or []
    if goods:
        # 标准报关单三行一项目（#84）：item1 对照参考识别结果
        assert len(goods) == 19
        first = goods[0]
        assert first.get("gno") == "1"
        assert first.get("codeTs") == "1905310000"
        assert first.get("gname") == "半岛苏格兰黄油酥饼（饼干）"
        # 规格两行无缝拼接（'白砂'+'糖17％'）
        assert "白砂糖17％" in (first.get("gmodel") or "")
        assert (first.get("gmodel") or "").startswith("4｜3｜")
        # 法定/成交数量拆开；法定千克同值补净重
        assert first.get("qty1") == "48"
        assert first.get("unit1") == "千克"
        assert first.get("customNetWt") == "48"
        assert first.get("gqty") == "240"
        assert first.get("gunit") == "盒"
        assert first.get("declPrice") == "66.8300"
        assert first.get("declTotal") == "16039.20"
        assert first.get("tradeCurr") == "港币"
        assert first.get("cusOriginCountry") == "英国"
        assert first.get("destinationCountry") == "中国"
        assert first.get("districtCode") == "44536"
        assert first.get("ciqDestCode") == "440308"
        assert all((item.get("codeTs") or "").isdigit() for item in goods)
        assert all(item.get("gmodel") for item in goods)
        assert all(item.get("qty1") for item in goods)
        assert goods[-1].get("gno") == "19"
