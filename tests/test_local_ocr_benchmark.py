"""本地 OCR 评测台单测（#108）：依赖探测、结果解析、方向层、隐私闸、新指标。

全部离线，不访问网络、不构造真模型。**本机不装 paddleocr / rapidocr 也要跑得通**——
只有用到图片旋转的用例才 importorskip("PIL")。
"""

from __future__ import annotations

import pytest
from benchmarks.ocr import engines as eng_mod
from benchmarks.ocr import local_engines as local
from benchmarks.ocr import metrics


class _ArrayLike:
    """顶替 numpy 数组：只用到 .tolist()。"""

    def __init__(self, values):
        self._values = values

    def tolist(self):
        return self._values


class _StubEngine:
    """本地引擎桩：不 import 任何重依赖，只记录喂进来的图。"""

    name = "stub"
    label = "桩引擎"
    is_cloud = False
    requires: tuple[str, ...] = ()

    def __init__(self, boxes: list | None = None) -> None:
        self.seen: list[bytes] = []
        self._boxes = boxes if boxes is not None else [eng_mod.OcrBox(text="示例")]

    def available(self):
        return True, "可用"

    def recognize(self, image: bytes):
        self.seen.append(image)
        return eng_mod.OcrResult(engine=self.name, boxes=list(self._boxes))


class _StubCloudEngine(_StubEngine):
    name = "stub-cloud"
    is_cloud = True


class _StubOri:
    def __init__(self, deg: int, score: float | None = 0.99) -> None:
        self.deg = deg
        self.score = score
        self.calls = 0

    def available(self):
        return True, "可用"

    def detect(self, image: bytes):
        self.calls += 1
        return self.deg, self.score


def _jpeg_bytes(width: int = 100, height: int = 50) -> bytes:
    """真 JPEG 字节——方向层要真的开图，喂假字节只会撞 UnidentifiedImageError。"""

    pytest.importorskip("PIL")
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


class TestDependencyProbe:
    def test_status_never_raises(self):
        ok, reason = local.dependency_status("paddleocr")
        assert isinstance(ok, bool)
        assert reason

    def test_missing_hint_lists_install_command(self):
        ok, _reason = local.dependency_status("一个不存在的模块")
        assert ok is False
        assert "pip install" in local.missing_hint(("一个不存在的模块",))

    def test_known_dependency_has_package_and_hint(self):
        dep = local.DEPENDENCIES["paddleocr"]
        assert dep.package == "paddleocr"
        assert "local-ocr" in dep.hint


class TestRegistry:
    def test_expected_engine_keys_present(self):
        keys = {entry.key for entry in local.local_registry()}
        assert {
            "local:paddle-v6-tiny",
            "local:paddle-v6-small",
            "local:paddle-v6-medium",
            "local:paddle-v5-mobile",
            "local:paddle-v5-server",
            "local:rapidocr-v6-tiny",
            "local:rapidocr-v6-small",
            "local:rapidocr-v6-medium",
            "local:doc-ori",
        } <= keys

    def test_doc_ori_is_not_an_ocr_engine(self):
        entries = {entry.key: entry for entry in local.local_registry()}
        assert entries["local:doc-ori"].kind == "orientation"

    def test_build_default_excludes_orientation(self):
        built = local.build_local_engines(None)
        assert built
        assert all(not isinstance(engine, local.DocOriEngine) for engine in built)

    def test_build_by_name(self):
        built = local.build_local_engines(["local:paddle-v6-small"])
        assert [engine.name for engine in built] == ["local:paddle-v6-small"]

    def test_build_unknown_name_raises(self):
        with pytest.raises(KeyError, match="未知本地引擎"):
            local.build_local_engines(["local:不存在的档位"])

    def test_status_rows_carry_reason(self):
        rows = local.local_engine_status()
        assert rows
        for row in rows:
            assert row.key and row.label
            assert row.reason

    def test_all_local_engines_are_not_cloud(self):
        built = local.build_local_engines(None)
        assert all(getattr(engine, "is_cloud", False) is False for engine in built)


class TestParsePaddleResult:
    def test_flat_dict(self):
        boxes = local.parse_paddle_result(
            {
                "rec_texts": ["甲"],
                "rec_scores": [0.9],
                "rec_polys": [[[1, 2], [3, 2], [3, 9], [1, 9]]],
            }
        )
        assert boxes[0].text == "甲"
        assert (boxes[0].x0, boxes[0].y0, boxes[0].x1, boxes[0].y1) == (1.0, 2.0, 3.0, 9.0)
        assert boxes[0].confidence == 0.9

    def test_texts_and_polys_zip_by_shortest(self):
        payload = {
            "rec_texts": ["甲", "乙"],
            "rec_scores": [0.99, 0.98],
            "rec_polys": [[[0, 0], [100, 0], [100, 30], [0, 30]]],
        }
        assert len(local.parse_paddle_result(payload)) == 1

    def test_alt_keys_dt_polys_boxes(self):
        boxes = local.parse_paddle_result(
            {"texts": ["甲"], "dt_polys": [[[0, 0], [10, 0], [10, 5], [0, 5]]]}
        )
        assert boxes[0].text == "甲"
        assert boxes[0].x1 == 10.0

    def test_numpy_like_payload(self):
        payload = {
            "rec_texts": _ArrayLike(["乙"]),
            "rec_scores": _ArrayLike([0.8]),
            "rec_polys": _ArrayLike([[[0, 0], [4, 0], [4, 4], [0, 4]]]),
        }
        boxes = local.parse_paddle_result(payload)
        assert boxes[0].text == "乙"

    def test_list_of_pages(self):
        payload = [
            {"rec_texts": ["甲"], "rec_polys": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},
            {"rec_texts": ["乙"], "rec_polys": [[[0, 5], [1, 5], [1, 6], [0, 6]]]},
        ]
        boxes = local.parse_paddle_result(payload)
        assert [box.text for box in boxes] == ["甲", "乙"]

    def test_unknown_keys_report_actual_keys(self):
        with pytest.raises(eng_mod.EngineError, match="实际 keys"):
            local.parse_paddle_result({"something_new": 1})

    def test_bad_type_raises(self):
        with pytest.raises(eng_mod.EngineError, match="无法识别的类型"):
            local.parse_paddle_result("一个字符串")


class TestParseRapidResult:
    def test_attributes(self):
        class _Out:
            boxes = [[[0, 0], [9, 0], [9, 3], [0, 3]]]
            txts = ("甲",)
            scores = (0.7,)

        boxes = local.parse_rapidocr_result(_Out())
        assert boxes[0].text == "甲"
        assert boxes[0].x1 == 9.0

    def test_missing_attributes(self):
        class _Out:
            pass

        with pytest.raises(eng_mod.EngineError, match="RapidOCR"):
            local.parse_rapidocr_result(_Out())

    def test_blank_page_returns_empty(self):
        """空白页 RapidOCR 给 txts=None（属性在、值为 None）——应返回空列表（#110）。"""

        class _Out:
            boxes = None
            txts = None
            scores = None

        assert local.parse_rapidocr_result(_Out()) == []

    def test_empty_tuple_returns_empty(self):
        class _Out:
            boxes = ()
            txts = ()
            scores = ()

        assert local.parse_rapidocr_result(_Out()) == []


class TestRapidParams:
    """RapidOCR 3.9 起枚举项必须传 Enum 实例（#110 实测撞上的 TypeError）。

    用替身枚举注入，**本机不装 rapidocr 也跑得通**。
    """

    @staticmethod
    def _enums():
        class _E:
            def __init__(self, value):
                self.value = value

        return {name: _E for name in ("ModelType", "OCRVersion", "EngineType", "TaskType")}

    def test_model_type_becomes_enum(self):
        out = local.rapidocr_params({"Det.model_type": "tiny"}, enums=self._enums())
        assert out["Det.model_type"].value == "tiny"

    def test_ocr_version_becomes_enum(self):
        out = local.rapidocr_params({"Rec.ocr_version": "PP-OCRv6"}, enums=self._enums())
        assert out["Rec.ocr_version"].value == "PP-OCRv6"

    def test_non_enum_param_passes_through(self):
        out = local.rapidocr_params({"Global.log_level": "info"}, enums=self._enums())
        assert out["Global.log_level"] == "info"

    def test_every_tier_param_resolves(self):
        enums = self._enums()
        for tier in local.RAPID_TIERS:
            out = local.rapidocr_params(tier.params, enums=enums)
            assert set(out) == set(tier.params)
            assert out["Det.model_type"].value in {"tiny", "small", "medium"}


class TestVramHelpers:
    """显存采样的两处小版本差异（#110 实测撞上）。"""

    def test_reset_picks_first_available_alias(self):
        calls = []

        class _Cuda:
            def reset_peak_memory_allocated(self):
                calls.append("peak")

        class _Device:
            cuda = _Cuda()

        class _Paddle:
            device = _Device()

        assert local.reset_paddle_peak(_Paddle()) is True
        assert calls == ["peak"]

    def test_reset_false_when_no_alias(self):
        class _Paddle:
            class device:
                class cuda:
                    pass

        assert local.reset_paddle_peak(_Paddle()) is False

    def test_visible_gpu_id_single(self, monkeypatch):
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2")
        assert local.visible_gpu_id() == "2"

    def test_visible_gpu_id_multi_is_none(self, monkeypatch):
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
        assert local.visible_gpu_id() is None

    def test_visible_gpu_id_unset_is_none(self, monkeypatch):
        monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
        assert local.visible_gpu_id() is None


class TestParseDocOri:
    def test_label_names(self):
        deg, score = local.parse_doc_ori_result({"label_names": ["90"], "scores": [0.99]})
        assert deg == 90
        assert score == 0.99

    def test_label_with_prefix(self):
        deg, _score = local.parse_doc_ori_result({"label_names": ["rot270"], "scores": [0.5]})
        assert deg == 270

    def test_class_ids_map_to_official_order(self):
        deg, _score = local.parse_doc_ori_result({"class_ids": [2], "scores": [0.5]})
        assert deg == 180

    def test_class_id_out_of_range_raises(self):
        with pytest.raises(eng_mod.EngineError, match="越界"):
            local.parse_doc_ori_result({"class_ids": [9], "scores": [0.5]})

    def test_missing_label_raises(self):
        with pytest.raises(eng_mod.EngineError):
            local.parse_doc_ori_result({"nope": 1})


class TestDocOriInvert:
    def test_no_invert_is_identity(self):
        engine = local.DocOriEngine(device="cpu")
        assert [engine.apply_invert(d) for d in (0, 90, 180, 270)] == [0, 90, 180, 270]

    def test_invert_swaps_90_and_270(self):
        engine = local.DocOriEngine(device="cpu", invert=True)
        assert engine.apply_invert(90) == 270
        assert engine.apply_invert(270) == 90
        assert engine.apply_invert(0) == 0
        assert engine.apply_invert(180) == 180

    def test_doc_ori_refuses_to_act_as_ocr(self):
        engine = local.DocOriEngine(device="cpu")
        with pytest.raises(eng_mod.EngineError, match="不是 OCR 引擎"):
            engine.recognize(b"")


class TestRotatingEngine:
    def test_rejects_off_mode(self):
        with pytest.raises(ValueError, match="auto / force"):
            local.RotatingEngine(_StubEngine(), mode="off")

    def test_name_suffix_and_metadata(self):
        engine = local.RotatingEngine(_StubEngine(), mode="force", force_deg=270)
        assert engine.name == "stub@force270"
        assert engine.mode == "force"

    def test_cloud_engine_stays_cloud_after_wrapping(self):
        wrapped = local.RotatingEngine(_StubCloudEngine(), mode="force", force_deg=90)
        assert wrapped.is_cloud is True

    def test_local_engine_stays_local(self):
        wrapped = local.RotatingEngine(_StubEngine(), mode="force", force_deg=90)
        assert wrapped.is_cloud is False

    def test_force_records_angle_without_calling_ori(self):
        ori = _StubOri(0)
        engine = local.RotatingEngine(_StubEngine(), mode="force", force_deg=90, ori=ori)
        result = engine.recognize(_jpeg_bytes())
        assert result.rotate_deg == 90
        assert result.rotate_source == "force"
        assert ori.calls == 0

    def test_auto_uses_ori_and_warns(self):
        ori = _StubOri(90, 0.93)
        engine = local.RotatingEngine(_StubEngine(), mode="auto", ori=ori)
        result = engine.recognize(_jpeg_bytes())
        assert result.rotate_deg == 90
        assert result.rotate_source == "auto"
        assert ori.calls == 1
        assert any("0.93" in w for w in result.warnings)

    def test_auto_without_ori_warns_and_does_not_crash(self):
        engine = local.RotatingEngine(_StubEngine(), mode="auto", ori=None)
        result = engine.recognize(_jpeg_bytes())
        assert result.rotate_deg == 0
        assert any("方向分类" in w for w in result.warnings)

    def test_available_falls_through_to_inner(self):
        class _Unavailable(_StubEngine):
            def available(self):
                return False, "缺依赖"

        wrapped = local.RotatingEngine(_Unavailable(), mode="force", force_deg=90)
        ok, reason = wrapped.available()
        assert ok is False
        assert reason == "缺依赖"


class TestRotateImageNeedsPIL:
    def test_rot90_swaps_dimensions(self):
        pytest.importorskip("PIL")
        import io

        from PIL import Image

        rotated = local.rotate_image_ccw(_jpeg_bytes(100, 50), 90)
        with Image.open(io.BytesIO(rotated)) as handle:
            assert handle.size == (50, 100)

    def test_zero_degrees_is_passthrough(self):
        assert local.rotate_image_ccw(b"raw", 0) == b"raw"

    def test_force_rotates_what_inner_sees(self):
        pytest.importorskip("PIL")
        import io

        from PIL import Image

        inner = _StubEngine()
        local.RotatingEngine(inner, mode="force", force_deg=90).recognize(_jpeg_bytes(100, 50))
        with Image.open(io.BytesIO(inner.seen[0])) as handle:
            assert handle.size == (50, 100)


class TestMetricsPercentile:
    def test_empty_returns_none(self):
        assert metrics.percentile([], 50) is None

    def test_single_value(self):
        assert metrics.percentile([10.0], 95) == 10.0

    def test_interpolates(self):
        assert metrics.percentile([1, 2, 3, 4], 50) == 2.5

    def test_p95_above_p50(self):
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 100]
        assert metrics.percentile(values, 95) > metrics.percentile(values, 50)

    def test_latency_percentiles_carries_n(self):
        stats = metrics.latency_percentiles([100, 200, 300])
        assert stats["n"] == 3
        assert stats["p50"] == 200

    def test_latency_percentiles_empty(self):
        stats = metrics.latency_percentiles([])
        assert stats == {"n": 0, "p50": None, "p95": None}


def _box(text: str, x0: float, y0: float, x1: float, y1: float) -> metrics.TextBox:
    return metrics.TextBox(text=text, x0=x0, y0=y0, x1=x1, y1=y1)


class TestClusterRowBands:
    def test_empty(self):
        assert metrics.cluster_row_bands([]) == []

    def test_two_bands(self):
        boxes = [
            _box("a", 0, 100, 10, 120),
            _box("b", 20, 102, 40, 122),
            _box("c", 0, 200, 10, 220),
            _box("d", 20, 203, 40, 223),
        ]
        bands = metrics.cluster_row_bands(boxes)
        assert [sorted(band) for band in bands] == [[0, 1], [2, 3]]

    def test_tolerance_is_relative_to_height(self):
        # 字块高 20，容差 0.6×20=12：错开 5 像素仍并成一行
        boxes = [_box("a", 0, 100, 10, 120), _box("b", 20, 105, 40, 125)]
        assert len(metrics.cluster_row_bands(boxes)) == 1

    def test_far_apart_stays_separate(self):
        boxes = [_box("a", 0, 100, 10, 120), _box("b", 20, 300, 40, 320)]
        assert len(metrics.cluster_row_bands(boxes)) == 2


class TestGoodsRowStructure:
    ROWS = [
        {"codeTs": "8479899090", "declPrice": "6.68", "cusOriginCountry": "中国"},
        {"codeTs": "1905310000", "declPrice": "3.35", "cusOriginCountry": "中国"},
    ]

    @staticmethod
    def _boxes_for(rows, y_step: float):
        boxes = []
        for index, row in enumerate(rows):
            y = 100 + index * y_step
            boxes.append(_box(row["codeTs"], 0, y, 100, y + 20))
            boxes.append(_box(row["declPrice"], 200, y, 260, y + 20))
            boxes.append(_box(row["cusOriginCountry"], 300, y, 360, y + 20))
        return boxes

    def test_perfect_layout(self):
        stats = metrics.goods_row_structure(
            self.ROWS,
            self._boxes_for(self.ROWS, y_step=60),
            anchor_key="codeTs",
            mate_keys=("declPrice", "cusOriginCountry"),
        )
        assert stats.ref_rows == 2
        assert stats.anchor_rows == 2
        assert stats.anchor_found == 2
        assert stats.merged == 0
        assert stats.attached == 2
        assert stats.attach_rate == 1.0

    def test_duplicate_anchors_with_distinct_mates_still_attach(self):
        """报关单里同一个 HS 码常出现在多行（同商品不同规格），不能因此判失败。

        冒烟时用真半岛参照撞出来的：19 行里有重复 codeTs，早先「锚只能落在一条带」
        的写法把正常行全判成不归属。
        """

        rows = [
            {"codeTs": "1905310000", "declPrice": "66.83", "cusOriginCountry": "GBR"},
            {"codeTs": "1905310000", "declPrice": "12.10", "cusOriginCountry": "GBR"},
        ]
        boxes = [
            _box("1905310000", 0, 100, 100, 120),
            _box("66.83", 200, 100, 260, 120),
            _box("GBR", 300, 100, 360, 120),
            _box("1905310000", 0, 200, 100, 220),
            _box("12.10", 200, 200, 260, 220),
            _box("GBR", 300, 200, 360, 220),
        ]
        stats = metrics.goods_row_structure(
            rows,
            boxes,
            anchor_key="codeTs",
            mate_keys=("declPrice", "cusOriginCountry"),
        )
        assert stats.anchor_found == 2
        assert stats.merged == 0
        assert stats.attached == 2
        assert stats.attach_rate == 1.0

    def test_identical_rows_are_not_counted_as_merged(self):
        """两行签名一模一样时本来就分不开，不该算「行被并」。"""

        rows = [
            {"codeTs": "1905310000", "declPrice": "66.83"},
            {"codeTs": "1905310000", "declPrice": "66.83"},
        ]
        boxes = [
            _box("1905310000", 0, 100, 100, 120),
            _box("66.83", 200, 100, 260, 120),
            _box("1905310000", 0, 200, 100, 220),
            _box("66.83", 200, 200, 260, 220),
        ]
        stats = metrics.goods_row_structure(
            rows, boxes, anchor_key="codeTs", mate_keys=("declPrice",)
        )
        assert stats.merged == 0
        assert stats.attached == 2

    def test_rows_collapsed_into_one_band_is_counted_as_merged(self):
        """#60 §4.3 那种「19 行并成 2–3 行」：锚都还在，但挤进同一条行带。"""

        boxes = []
        for row in self.ROWS:
            boxes.append(_box(row["codeTs"], 0, 100, 100, 120))
            boxes.append(_box(row["declPrice"], 200, 100, 260, 120))
        stats = metrics.goods_row_structure(
            self.ROWS, boxes, anchor_key="codeTs", mate_keys=("declPrice",)
        )
        assert stats.anchor_found == 2
        assert stats.merged == 2
        assert stats.attached == 0
        assert stats.attach_rate == 0.0

    def test_mate_in_wrong_band_is_not_attached(self):
        boxes = self._boxes_for(self.ROWS, y_step=60)
        # 把第二行的单价扔到第一行的行带里
        boxes[4] = _box("3.35", 200, 100, 260, 120)
        stats = metrics.goods_row_structure(
            self.ROWS, boxes, anchor_key="codeTs", mate_keys=("declPrice",)
        )
        assert stats.anchor_found == 2
        assert stats.merged == 0
        assert stats.attached == 1
        assert stats.attach_rate == 0.5

    def test_missing_anchor_reduces_attach_rate(self):
        boxes = self._boxes_for(self.ROWS, y_step=60)[3:]  # 去掉第一行全部字块
        stats = metrics.goods_row_structure(
            self.ROWS, boxes, anchor_key="codeTs", mate_keys=("declPrice",)
        )
        assert stats.anchor_found == 1
        assert stats.attached == 1
        assert stats.attach_rate == 0.5

    def test_rows_without_anchor_are_excluded_from_denominator(self):
        rows = [{"codeTs": "", "declPrice": "6.68"}, {"codeTs": "1905310000", "declPrice": "3.35"}]
        boxes = [
            _box("6.68", 200, 100, 260, 120),
            _box("1905310000", 0, 200, 100, 220),
            _box("3.35", 200, 200, 260, 220),
        ]
        stats = metrics.goods_row_structure(
            rows, boxes, anchor_key="codeTs", mate_keys=("declPrice",)
        )
        assert stats.ref_rows == 2
        assert stats.anchor_rows == 1
        assert stats.attach_rate == 1.0

    def test_region_limits_band_count(self):
        boxes = self._boxes_for(self.ROWS, y_step=60)
        boxes.append(_box("页脚说明", 0, 900, 200, 920))
        whole = metrics.goods_row_structure(self.ROWS, boxes, anchor_key="codeTs")
        scoped = metrics.goods_row_structure(
            self.ROWS, boxes, anchor_key="codeTs", region=(0, 0, 400, 500)
        )
        assert whole.pred_rows == scoped.pred_rows + 1
        assert scoped.row_count_ratio == 1.0

    def test_row_count_ratio_none_without_reference_rows(self):
        stats = metrics.goods_row_structure([], [], anchor_key="codeTs")
        assert stats.row_count_ratio is None
        assert stats.attach_rate is None

    def test_as_dict_is_serializable(self):
        import json

        stats = metrics.goods_row_structure(
            self.ROWS, self._boxes_for(self.ROWS, y_step=60), anchor_key="codeTs"
        )
        assert json.loads(json.dumps(stats.as_dict()))["attached"] == 2


class TestTextBoxesFromDicts:
    """结果 JSON 里 boxes 是 dict，报表要能直接吃（冒烟时撞出来的）。"""

    def test_converts(self):
        boxes = metrics.text_boxes_from_dicts(
            [{"text": "甲", "x0": 1, "y0": 2, "x1": 3, "y1": 4}]
        )
        assert boxes[0].text == "甲"
        assert (boxes[0].x0, boxes[0].y0, boxes[0].x1, boxes[0].y1) == (1.0, 2.0, 3.0, 4.0)

    def test_skips_entries_without_text(self):
        assert metrics.text_boxes_from_dicts([{"x0": 1}, {"text": "乙"}]) == [
            metrics.TextBox(text="乙", x0=0.0, y0=0.0, x1=0.0, y1=1.0)
        ]

    def test_skips_non_dict(self):
        assert metrics.text_boxes_from_dicts(["不是 dict", 42]) == []

    def test_feeds_goods_row_structure(self):
        payload = [
            {"text": "8479899090", "x0": 0, "y0": 100, "x1": 100, "y1": 120},
            {"text": "6.68", "x0": 200, "y0": 100, "x1": 260, "y1": 120},
        ]
        rows = [{"codeTs": "8479899090", "declPrice": "6.68"}]
        stats = metrics.goods_row_structure(
            rows,
            metrics.text_boxes_from_dicts(payload),
            anchor_key="codeTs",
            mate_keys=("declPrice",),
        )
        assert stats.attach_rate == 1.0


class TestVramSampler:
    """读不到显存就写读不到——不许拿社区数字顶替（#97 要求显存峰值只能自测）。"""

    def test_without_start_reports_unavailable(self, monkeypatch):
        monkeypatch.setattr(local, "nvidia_smi_path", lambda: None)
        reading = local.VramSampler().stop()
        assert reading.peak_mb is None
        assert reading.source == "unavailable"
        assert "读不到" in reading.note

    def test_nvidia_smi_source_when_paddle_absent(self, monkeypatch):
        monkeypatch.setattr(local, "nvidia_smi_path", lambda: None)
        sampler = local.VramSampler()
        sampler._peak = 4321.0
        reading = sampler.stop()
        assert reading.peak_mb == 4321.0
        assert reading.source == "nvidia-smi"
        assert "整卡" in reading.note

    def test_paddle_cuda_absent_without_paddle_module(self):
        assert local.VramSampler._paddle_cuda() is None

    def test_nvidia_smi_reader_without_binary(self, monkeypatch):
        monkeypatch.setattr(local, "nvidia_smi_path", lambda: None)
        assert local.read_nvidia_smi_used_mb() is None


class TestProbe:
    def test_probe_engine_ok(self):
        pytest.importorskip("PIL")
        ok, detail = local.probe_engine(_StubEngine(boxes=[]))
        assert ok is True
        assert "跑通" in detail

    def test_probe_engine_reports_exception(self):
        pytest.importorskip("PIL")

        class _Broken(_StubEngine):
            def recognize(self, image):
                raise RuntimeError("模型名不对")

        ok, detail = local.probe_engine(_Broken())
        assert ok is False
        assert "模型名不对" in detail

    def test_probe_orientation_ok(self):
        pytest.importorskip("PIL")
        ok, detail = local.probe_orientation(_StubOri(90))
        assert ok is True
        assert "90" in detail


def _run_module():
    """run.py 会连带 import fixtures / visualize（都要 PIL），没装就整类跳过。"""

    return pytest.importorskip("benchmarks.ocr.run", reason="需要 bench extra（pillow / pymupdf）")


class TestPrivacyGate:
    """真机样本是客户真实数据，云引擎默认一次 HTTP 都不发（#108 硬验收）。"""

    @staticmethod
    def _target(kind: str):
        run_mod = _run_module()
        return run_mod.Target(key="peninsula-p1", image=b"x", kind=kind, rotation=False)

    def test_cloud_on_real_is_blocked_by_default(self):
        run_mod = _run_module()
        reason = run_mod.cloud_gate(
            _StubCloudEngine(), self._target("real"), allow_cloud_on_real=False
        )
        assert reason and "隐私" in reason

    def test_cloud_on_real_passes_only_with_flag(self):
        run_mod = _run_module()
        assert (
            run_mod.cloud_gate(
                _StubCloudEngine(), self._target("real"), allow_cloud_on_real=True
            )
            is None
        )

    def test_cloud_on_synthetic_is_allowed(self):
        run_mod = _run_module()
        assert (
            run_mod.cloud_gate(
                _StubCloudEngine(), self._target("synthetic"), allow_cloud_on_real=False
            )
            is None
        )

    def test_local_engine_on_real_is_allowed(self):
        run_mod = _run_module()
        assert (
            run_mod.cloud_gate(_StubEngine(), self._target("real"), allow_cloud_on_real=False)
            is None
        )

    def test_wrapped_cloud_engine_is_still_gated(self):
        """包了 --rotate-mode 不能变成绕过闸门的口子。"""

        run_mod = _run_module()
        wrapped = local.RotatingEngine(_StubCloudEngine(), mode="force", force_deg=90)
        reason = run_mod.cloud_gate(wrapped, self._target("real"), allow_cloud_on_real=False)
        assert reason and "隐私" in reason

    def test_rotate_mode_force_wraps_cloud_engines(self):
        run_mod = _run_module()
        parser = run_mod.build_parser()
        args = parser.parse_args(["call", "--engine", "cloud", "--rotate-mode", "force"])
        engines = run_mod.build_engine_list(args)
        assert engines
        assert all(engine.is_cloud for engine in engines)
        assert all(isinstance(engine, local.RotatingEngine) for engine in engines)

    def test_rotate_mode_off_does_not_wrap(self):
        run_mod = _run_module()
        parser = run_mod.build_parser()
        args = parser.parse_args(["call", "--engine", "cloud", "--rotate-mode", "off"])
        engines = run_mod.build_engine_list(args)
        assert engines
        assert not any(isinstance(engine, local.RotatingEngine) for engine in engines)

    def test_rotate_mode_auto_keeps_cloud_flag(self):
        run_mod = _run_module()
        parser = run_mod.build_parser()
        args = parser.parse_args(["call", "--engine", "cloud", "--rotate-mode", "auto"])
        engines = run_mod.build_engine_list(args)
        assert all(engine.is_cloud for engine in engines)

    def test_rotation_modes_land_in_different_result_dirs(self):
        run_mod = _run_module()
        parser = run_mod.build_parser()
        names = set()
        for argv in (
            ["call", "--engine", "cloud", "--rotate-mode", "force", "--force-deg", "90"],
            ["call", "--engine", "cloud", "--rotate-mode", "force", "--force-deg", "270"],
            ["call", "--engine", "cloud", "--rotate-mode", "auto"],
        ):
            built = run_mod.build_engine_list(parser.parse_args(argv))
            names.add(tuple(engine.name for engine in built))
        assert len(names) == 3


class TestRotationKeyClassification:
    """#109 起「哪页算旋转页」由样本清单的 `rotation_truth` 判，命名法退役。

    命名法两头都不准：镇发 p1 内容转了 90° 但名字里没有 `rotXX`（漏判），
    `zhenfa-p1-rot90` 是**转正件**、本身正立，名字里却带 `rot90`（误判）。
    清单驱动的判定见 tests/test_ocr_samples.py。
    """

    def test_name_hint_no_longer_decides(self):
        run_mod = _run_module()
        assert not run_mod._is_rotation_key("a-rot90")
        assert not run_mod._is_rotation_key("zhenfa-p1-rot90")

    def test_explicit_key_still_marks_it(self):
        run_mod = _run_module()
        assert not run_mod._is_rotation_key("zhenfa-p1")
        assert run_mod._is_rotation_key("zhenfa-p1", ("zhenfa-p1",))


class TestParseRegion:
    def test_none(self):
        run_mod = _run_module()
        assert run_mod._parse_region(None) is None

    def test_four_numbers(self):
        run_mod = _run_module()
        assert run_mod._parse_region("0, 10, 20, 30") == (0.0, 10.0, 20.0, 30.0)

    def test_bad_arity_exits(self):
        run_mod = _run_module()
        with pytest.raises(SystemExit):
            run_mod._parse_region("1,2,3")


class TestUnknownEngineNames:
    def test_unknown_cloud_name_exits(self):
        run_mod = _run_module()
        parser = run_mod.build_parser()
        args = parser.parse_args(["call", "--engine", "cloud,不存在的引擎"])
        with pytest.raises(SystemExit):
            run_mod.build_engine_list(args)

    def test_unknown_local_name_exits(self):
        run_mod = _run_module()
        parser = run_mod.build_parser()
        args = parser.parse_args(["call", "--engine", "local:不存在的档位"])
        with pytest.raises(SystemExit):
            run_mod.build_engine_list(args)

    def test_doc_ori_cannot_be_run_as_ocr(self):
        run_mod = _run_module()
        parser = run_mod.build_parser()
        args = parser.parse_args(["call", "--engine", "local:doc-ori"])
        with pytest.raises(SystemExit):
            run_mod.build_engine_list(args)


class TestEngineSelection:
    """选引擎的矩阵：空列表不等于「全部」（冒烟时 `--engine local:x` 会把五朵云也带上）。"""

    def _names(self, argv: list[str]) -> list[str]:
        run_mod = _run_module()
        args = run_mod.build_parser().parse_args(["call", *argv])
        return [engine.name for engine in run_mod.build_engine_list(args)]

    def test_cloud_group(self):
        names = self._names(["--engine", "cloud"])
        assert names == [
            "textin-general",
            "textin-customs",
            "baidu-general",
            "aliyun-general",
            "tencent-general",
        ]

    def test_local_group_has_no_cloud(self):
        names = self._names(["--engine", "local"])
        assert names
        assert all(name.startswith("local:") for name in names)

    def test_single_local_engine_does_not_drag_cloud_in(self):
        assert self._names(["--engine", "local:paddle-v6-small"]) == ["local:paddle-v6-small"]

    def test_single_cloud_engine(self):
        assert self._names(["--engine", "textin-general"]) == ["textin-general"]

    def test_mixed_names(self):
        assert self._names(["--engine", "textin-general,local:paddle-v6-small"]) == [
            "textin-general",
            "local:paddle-v6-small",
        ]

    def test_all_is_cloud_plus_local(self):
        names = self._names(["--engine", "all"])
        assert "textin-general" in names
        assert "local:paddle-v6-small" in names

    def test_build_engines_empty_list_means_none(self):
        assert eng_mod.build_engines([]) == []
        assert len(eng_mod.build_engines(None)) == 5
