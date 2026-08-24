"""OCR 实测装置单测：指标、解析、签名、夹具渲染。全部离线，不访问网络。"""

from __future__ import annotations

import pytest

pytest.importorskip("PIL")

from benchmarks.ocr import engines as eng
from benchmarks.ocr import fixtures as fx
from benchmarks.ocr import metrics


class TestMetrics:
    def test_normalize_fullwidth_and_space(self):
        assert metrics.normalize("ＡＢＣ ｄｅｆ") == "ABCDEF"

    def test_normalize_chinese_punct(self):
        assert metrics.normalize("（惠州）有限公司。") == "(惠州)有限公司."

    def test_cer_identical(self):
        assert metrics.cer("中华人民共和国", "中华人民共和国") == 0.0

    def test_cer_one_substitution(self):
        assert metrics.cer("ABCD", "ABXD") == 0.25

    def test_cer_transposition_costs_two(self):
        assert metrics.cer("ABCD", "ABDC") == 0.5

    def test_cer_ignores_width_and_space(self):
        assert metrics.cer("Ａ ＢＣ", "ABC") == 0.0

    def test_field_hits(self):
        text = "境内发货人 示例精密科技（惠州）有限公司"
        hits = metrics.field_hits({"境内发货人": "示例精密科技(惠州)有限公司"}, text)
        assert hits[0][2] is True

    def test_field_hit_miss(self):
        assert metrics.field_hit_rate({"件数": "999"}, "件数 120") == 0.0

    def test_field_cer_missing_field(self):
        rows = metrics.field_cer({"毛重": "100"}, {})
        assert rows == [("毛重", 1.0)]


class TestEnginesParse:
    def test_parse_textin_general(self):
        payload = {
            "code": 200,
            "result": {
                "pages": [
                    {
                        "lines": [
                            {
                                "text": "中华人民共和国",
                                "score": 0.99,
                                "position": [0, 1, 100, 1, 100, 30, 0, 30],
                            }
                        ]
                    }
                ]
            },
        }
        boxes = eng.parse_textin_general(payload)
        assert boxes[0].text == "中华人民共和国"
        assert boxes[0].x0 == 0 and boxes[0].x1 == 100

    def test_parse_textin_customs_flat(self):
        payload = {
            "result": {
                "details": {
                    "customs_number": {"value": "530320260000123456A"},
                    "gross_weight": {"value": "1459.62"},
                }
            }
        }
        fields, items = eng.parse_textin_customs(payload)
        assert fields["customs_number"] == "530320260000123456A"
        assert items == []

    def test_parse_textin_customs_nested_item_list(self):
        payload = {
            "result": {
                "pages": [
                    {
                        "object_list": [
                            {
                                "details": {
                                    "net_weight": {"value": "485"},
                                    "item_list": [
                                        {
                                            "product_id": {"value": "8479899090"},
                                            "unit_price": {"value": "6.68"},
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                ]
            }
        }
        fields, items = eng.parse_textin_customs(payload)
        assert fields["net_weight"] == "485"
        assert items == [{"product_id": "8479899090", "unit_price": "6.68"}]

    def test_parse_baidu(self):
        payload = {
            "words_result": [
                {
                    "words": "海关编号 530320260000123456A",
                    "location": {"left": 10, "top": 20, "width": 300, "height": 25},
                }
            ]
        }
        boxes = eng.parse_baidu(payload)
        assert boxes[0].x0 == 10 and boxes[0].y1 == 45

    def test_parse_tencent(self):
        payload = {
            "Response": {
                "TextDetections": [
                    {
                        "DetectedText": "毛重（千克） 1459.62",
                        "Confidence": 99,
                        "ItemPolygon": {"X": 5, "Y": 6, "Width": 200, "Height": 24},
                    }
                ]
            }
        }
        boxes = eng.parse_tencent(payload)
        assert boxes[0].text == "毛重（千克） 1459.62"
        assert boxes[0].x1 == 205

    def test_parse_tencent_error(self):
        with pytest.raises(eng.EngineError):
            eng.parse_tencent(
                {"Response": {"Error": {"Code": "FailedOperation.OcrFailed", "Message": "x"}}}
            )

    def test_parse_aliyun(self):
        inner = {
            "content": "示例",
            "prism_wordsInfo": [
                {
                    "word": "示例精密科技",
                    "prob": 99,
                    "pos": [
                        {"x": 1, "y": 2},
                        {"x": 101, "y": 2},
                        {"x": 101, "y": 30},
                        {"x": 1, "y": 30},
                    ],
                }
            ],
        }
        import json

        payload = {"Data": json.dumps(inner, ensure_ascii=False)}
        boxes = eng.parse_aliyun(payload)
        assert boxes[0].text == "示例精密科技"
        assert boxes[0].x1 == 101

    def test_parse_aliyun_error(self):
        with pytest.raises(eng.EngineError):
            eng.parse_aliyun({"Code": "noPermission", "Message": "denied"})


class TestSignatures:
    def test_acs3_official_vector(self):
        headers = eng.acs3_authorization(
            "YourAccessKeyId",
            "YourAccessKeySecret",
            method="POST",
            host="ecs.cn-shanghai.aliyuncs.com",
            action="RunInstances",
            api_version="2014-05-26",
            date="2023-10-26T10:22:32Z",
            nonce="3156853299f313e23d1673dc12e1703d",
            body=b"",
            canonical_query="ImageId=win2019_1809_x64_dtc_zh-cn_40G_alibase_20230811.vhd&RegionId=cn-shanghai",
        )
        assert headers["Authorization"].endswith(
            "Signature=06563a9e1b43f5dfe96b81484da74bceab24a1d853912eee15083a6f0f3283c0"
        )

    def test_acs3_signed_headers_order(self):
        headers = eng.acs3_authorization(
            "ak",
            "sk",
            method="POST",
            host="ocr-api.cn-hangzhou.aliyuncs.com",
            action="RecognizeGeneral",
            api_version="2021-07-07",
            date="2026-01-01T00:00:00Z",
            nonce="n",
            body=b"abc",
            content_type="application/octet-stream",
        )
        expected = (
            "SignedHeaders=content-type;host;x-acs-action;x-acs-content-sha256;x-acs-date;"
            "x-acs-signature-nonce;x-acs-version"
        )
        assert expected in headers["Authorization"]

    def test_tc3_authorization_shape(self):
        headers = eng.tc3_authorization(
            "AKIDtest",
            "SecretKey",
            host="ocr.tencentcloudapi.com",
            service="ocr",
            action="GeneralBasicOCR",
            api_version="2018-11-19",
            timestamp=1700000000,
            payload='{"ImageBase64":"eA=="}',
        )
        assert headers["Authorization"].startswith("TC3-HMAC-SHA256 Credential=AKIDtest,")
        assert headers["X-TC-Action"] == "GeneralBasicOCR"


class TestFixtures:
    def test_spec_present(self):
        assert fx.SPEC_A.key == "a"
        assert fx.SPEC_A.head_rows[0][0] == "境内发货人"
        assert len(fx.SPEC_A.goods_rows) == 3
        assert len(fx.SPEC_B.goods_rows) == 1

    def test_variants_complete(self):
        assert fx.VARIANTS == ["base", "rot90", "rot180", "rot270", "jpeg60", "noise", "lowres"]

    def test_render_spec_gt(self):
        try:
            image, gt = fx.render_spec(fx.SPEC_A)
        except RuntimeError:
            pytest.skip("本机无中文字体")
        assert image.size == (fx.PAGE_W, fx.PAGE_H)
        assert len(gt.lines) > 40
        assert gt.fields["境内发货人"] == "示例精密科技（惠州）有限公司"
        assert gt.fields["海关编号"] == "530320260000123456A"
        assert gt.full_text().startswith("中华人民共和国")

    def test_build_fixture_images_variants(self):
        try:
            images = fx.build_fixture_images(fx.SPEC_A)
        except RuntimeError:
            pytest.skip("本机无中文字体")
        assert len(images) == 7
        by_variant = {img.variant: img for img in images}
        assert by_variant["rot90"].width == fx.PAGE_H
        assert by_variant["rot90"].height == fx.PAGE_W
        assert by_variant["base"].image[:2] == b"\xff\xd8"
