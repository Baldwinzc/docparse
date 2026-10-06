"""本地 OCR 引擎接入（#99）：返回值解析、转正、降级、分发。

全部离线，不构造真模型、不发任何 HTTP——本机不装 paddleocr 也跑得通：重依赖只在
`LocalOcrClient._get_engine` / `_get_ori` 里懒 import，单测一律注入替身。
需要 PIL 的用例（转正、造图）在模块级 importorskip。
"""

from __future__ import annotations

import io
from typing import Any

import pytest

pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from docparse.adapters.parsers import local_ocr as local  # noqa: E402
from docparse.adapters.parsers.local_ocr import (  # noqa: E402
    LocalOcrClient,
    cpu_kwargs,
    get_local_ocr_client,
    parse_orientation,
    parse_paddle_lines,
    prepare_image,
    resolve_device,
)
from docparse.adapters.parsers.ocr import TextinOcrClient, get_ocr_client  # noqa: E402
from docparse.config import Settings  # noqa: E402


def _jpeg(width: int = 120, height: int = 60) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _png(width: int = 120, height: int = 60) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _bmp(width: int = 120, height: int = 60) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="BMP")
    return buffer.getvalue()


class _StubEngine:
    """识别替身：读临时文件记下喂进来的图尺寸与后缀，回放固定 payload。"""

    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.seen: list[tuple[int, int]] = []
        self.suffixes: list[str] = []

    def predict(self, input: str | None = None) -> Any:  # noqa: A002 —— 对齐 PaddleOCR 签名
        if self.error is not None:
            raise self.error
        import os

        self.suffixes.append(os.path.splitext(input)[1])
        with Image.open(input) as handle:
            self.seen.append(handle.size)
        if self.payload is not None:
            return self.payload
        return {
            "rec_texts": ["海关编号 530320260000123456A"],
            "rec_scores": [0.99],
            "rec_polys": [[[10, 20], [400, 20], [400, 50], [10, 50]]],
        }


class _StubOri:
    """方向分类替身：回放固定标签。"""

    def __init__(self, label: str = "90", error: Exception | None = None) -> None:
        self.label = label
        self.error = error
        self.calls = 0

    def predict(self, input: str | None = None) -> Any:  # noqa: A002
        self.calls += 1
        if self.error is not None:
            raise self.error
        return [{"label_names": [self.label], "scores": [0.97]}]


# ---------------------------------------------------------------------------
# 返回值解析（不装 Paddle 也能测）


class TestParsePaddleLines:
    def test_texts_and_polys(self) -> None:
        lines = parse_paddle_lines(
            {
                "rec_texts": ["甲", "乙"],
                "rec_scores": [0.9, 0.8],
                "rec_polys": [
                    [[0, 0], [10, 0], [10, 5], [0, 5]],
                    [[0, 10], [20, 10], [20, 15], [0, 15]],
                ],
            }
        )
        assert [line.text for line in lines] == ["甲", "乙"]
        assert (lines[0].x0, lines[0].y0, lines[0].x1, lines[0].y1) == (0, 0, 10, 5)
        assert lines[1].score == 0.8

    def test_alt_keys_and_box_shapes(self) -> None:
        # 备选键名 `boxes` + 每个点用 dict 表达（官方两种写法都兜住）
        lines = parse_paddle_lines(
            {
                "texts": ["x"],
                "boxes": [
                    [
                        {"x": 1, "y": 2},
                        {"x": 5, "y": 2},
                        {"x": 5, "y": 9},
                        {"x": 1, "y": 9},
                    ]
                ],
            }
        )
        assert len(lines) == 1
        assert (lines[0].x0, lines[0].y0, lines[0].x1, lines[0].y1) == (1, 2, 5, 9)
        assert lines[0].score is None

    def test_numpy_like_payload(self) -> None:
        class _Arr:
            """顶替 numpy 数组：只用到 .tolist()。"""

            def __init__(self, values: Any) -> None:
                self._values = values

            def tolist(self) -> Any:
                return self._values

        lines = parse_paddle_lines(
            {
                "rec_texts": _Arr(["z"]),
                "rec_scores": _Arr([0.5]),
                "rec_polys": _Arr([[[0, 0], [1, 0], [1, 1], [0, 1]]]),
            }
        )
        assert [line.text for line in lines] == ["z"]
        assert lines[0].score == 0.5

    def test_blank_and_empty_texts(self) -> None:
        assert parse_paddle_lines({"rec_texts": [], "rec_polys": []}) == []
        lines = parse_paddle_lines(
            {"rec_texts": ["  ", "甲"], "rec_polys": [[[0, 0], [1, 0], [1, 1], [0, 1]]] * 2}
        )
        assert [line.text for line in lines] == ["甲"]

    def test_unknown_keys_report_actual_keys(self) -> None:
        with pytest.raises(ValueError, match="实际 keys"):
            parse_paddle_lines({"weird": 1})

    def test_bad_type_raises(self) -> None:
        with pytest.raises(ValueError, match="无法识别"):
            parse_paddle_lines(42)


class TestParseOrientation:
    def test_label_names(self) -> None:
        assert parse_orientation({"label_names": ["90"], "scores": [0.99]}) == (90, 0.99)

    def test_label_with_prefix(self) -> None:
        assert parse_orientation({"labels": ["rot270"], "scores": [0.5]}) == (270, 0.5)

    def test_class_ids_map_to_official_order(self) -> None:
        assert parse_orientation({"class_ids": [3], "scores": [0.8]}) == (270, 0.8)

    def test_class_id_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="越界"):
            parse_orientation({"class_ids": [9]})

    def test_missing_label_raises(self) -> None:
        with pytest.raises(ValueError, match="角度数字|解析出标签"):
            parse_orientation({"label_names": ["sideways"]})


# ---------------------------------------------------------------------------
# 转正 / 设备 / CPU 参数


class TestPrepareImage:
    def test_rot90_swaps_dimensions(self) -> None:
        upright, width, height, suffix = prepare_image(_jpeg(120, 60), 90)
        assert (width, height) == (60, 120)
        assert suffix == ".jpg"
        with Image.open(io.BytesIO(upright)) as handle:
            assert handle.size == (60, 120)

    def test_zero_degrees_jpeg_passthrough(self) -> None:
        data = _jpeg(120, 60)
        upright, width, height, suffix = prepare_image(data, 0)
        assert upright is data
        assert (width, height, suffix) == (120, 60, ".jpg")

    def test_zero_degrees_png_keeps_png_suffix(self) -> None:
        data = _png(120, 60)
        upright, width, height, suffix = prepare_image(data, 0)
        assert upright is data
        assert (width, height, suffix) == (120, 60, ".png")

    def test_unrecognized_format_normalized_to_jpeg(self) -> None:
        # image.py 也收 tif / webp / bmp：这里并成 JPEG，后缀如实给 .jpg
        upright, width, height, suffix = prepare_image(_bmp(120, 60), 0)
        assert (width, height, suffix) == (120, 60, ".jpg")
        with Image.open(io.BytesIO(upright)) as handle:
            assert handle.format == "JPEG"


class TestDeviceAndCpuKwargs:
    def test_explicit_device_passthrough(self) -> None:
        assert resolve_device("cpu") == "cpu"
        assert resolve_device("gpu") == "gpu"

    def test_auto_without_paddle_falls_back_to_cpu(self) -> None:
        # 本机没装 paddle：import 失败 → cpu（引擎构造再按 cpu 参数走）
        assert resolve_device("auto") in {"cpu", "gpu"}  # gpu 只有在真有 CUDA 时

    def test_cpu_kwargs_only_on_cpu(self) -> None:
        assert cpu_kwargs("gpu") == {}
        assert cpu_kwargs("cpu") == {"enable_mkldnn": False}
        assert cpu_kwargs("cpu", 4) == {"enable_mkldnn": False, "cpu_threads": 4}


# ---------------------------------------------------------------------------
# LocalOcrClient：转正语义 + 降级路径


class TestLocalOcrClient:
    def test_lines_log_angle_and_upright_size(self) -> None:
        engine = _StubEngine()
        ori = _StubOri(label="90")
        outcome = LocalOcrClient(engine=engine, ori=ori).read_image(
            _jpeg(120, 60), filename="x.jpg"
        )
        # 先按 90° 转正再识别：引擎看到的是转正后的图
        assert engine.seen == [(60, 120)]
        # OcrOutcome 以正立图为参照系：宽高对调、angle 留档、bbox 原样传回
        assert (outcome.width, outcome.height) == (60, 120)
        assert outcome.angle == 90
        assert any("判定 90" in w for w in outcome.warnings)
        assert len(outcome.lines) == 1
        assert outcome.lines[0].text == "海关编号 530320260000123456A"
        assert (outcome.lines[0].x0, outcome.lines[0].x1) == (10, 400)

    def test_flat_page_angle_zero(self) -> None:
        engine = _StubEngine()
        outcome = LocalOcrClient(engine=engine, ori=_StubOri(label="0")).read_image(
            _jpeg(), filename="x.jpg"
        )
        assert outcome.angle == 0
        assert engine.seen == [(120, 60)]

    def test_png_input_gets_png_suffix_no_reencode(self) -> None:
        # jpg / png 与扫描 PDF 页走同一入口；PNG 不该被伪装成 .jpg 糊引擎
        engine = _StubEngine()
        outcome = LocalOcrClient(engine=engine, ori=_StubOri(label="0")).read_image(
            _png(), filename="x.png"
        )
        assert engine.suffixes == [".png"]
        assert (outcome.width, outcome.height) == (120, 60)
        assert len(outcome.lines) == 1

    def test_ori_absent_warns_and_reads_at_zero(self) -> None:
        engine = _StubEngine()
        client = LocalOcrClient(engine=engine, ori=_StubOri())
        client._ori = None  # 强行让 ori 不可用
        client._get_ori = lambda: None  # type: ignore[method-assign]
        outcome = client.read_image(_jpeg(), filename="x.jpg")
        assert outcome.angle == 0
        assert any("方向分类模型不可用" in w for w in outcome.warnings)
        assert len(outcome.lines) == 1  # 仍出字，只是没转正

    def test_ori_failure_warns_and_reads_at_zero(self) -> None:
        client = LocalOcrClient(engine=_StubEngine(), ori=_StubOri(error=RuntimeError("boom")))
        outcome = client.read_image(_jpeg(), filename="x.jpg")
        assert outcome.angle == 0
        assert any("方向分类判定失败" in w for w in outcome.warnings)

    def test_engine_unavailable_warns_no_text(self, monkeypatch) -> None:
        monkeypatch.setattr(local, "dependency_status", lambda: (False, "未安装 paddleocr"))
        outcome = LocalOcrClient().read_image(_jpeg(), filename="x.jpg")
        assert outcome.lines == []
        assert outcome.width == 0 and outcome.height == 0
        assert any("引擎不可用" in w for w in outcome.warnings)

    def test_engine_load_failure_warns_no_crash(self, monkeypatch) -> None:
        def _boom(self: LocalOcrClient) -> Any:
            raise RuntimeError("权重缺失 / 下载失败")

        monkeypatch.setattr(LocalOcrClient, "_get_engine", _boom)
        # 注入 engine 让 available() 为真，_get_engine 被换成抛异常 → 走「加载失败」分支
        outcome = LocalOcrClient(engine=_StubEngine(), ori=_StubOri()).read_image(
            _jpeg(), filename="x.jpg"
        )
        assert outcome.lines == []
        assert any("加载失败" in w for w in outcome.warnings)

    def test_recognize_failure_warns_no_crash(self) -> None:
        outcome = LocalOcrClient(
            engine=_StubEngine(error=RuntimeError("识别炸了")), ori=_StubOri()
        ).read_image(_jpeg(), filename="x.jpg")
        assert outcome.lines == []
        assert any("识别失败" in w for w in outcome.warnings)

    def test_available_true_when_injected(self) -> None:
        ok, _reason = LocalOcrClient(engine=_StubEngine()).available()
        assert ok is True


# ---------------------------------------------------------------------------
# 分发：默认本地优先，textin 显式选


class TestGetOcrClientDispatch:
    def test_default_is_local(self) -> None:
        assert isinstance(get_ocr_client(Settings()), LocalOcrClient)

    def test_explicit_local(self) -> None:
        assert isinstance(get_ocr_client(Settings(ocr_engine="local")), LocalOcrClient)

    def test_textin_selected_explicitly(self) -> None:
        client = get_ocr_client(
            Settings(ocr_engine="textin", textin_app_id="a", textin_secret_code="b")
        )
        assert isinstance(client, TextinOcrClient)

    def test_get_local_client_reuses_by_device(self) -> None:
        first = get_local_ocr_client(Settings(local_ocr_device="cpu"))
        assert get_local_ocr_client(Settings(local_ocr_device="cpu")) is first
        other = get_local_ocr_client(Settings(local_ocr_device="gpu"))
        assert other is not first


# ---------------------------------------------------------------------------
# 流水线：默认本地引擎不可用时降级，不崩、不编字


class TestPipelineLocalDegradation:
    def test_scanned_pdf_engine_unavailable_needs_review(self, monkeypatch) -> None:
        from docparse.adapters.files.memory import MemoryFileStore
        from docparse.adapters.jobs.memory import MemoryJobStore
        from docparse.domain.models import JobStatus
        from docparse.pipeline.runner import Pipeline
        from test_pdf_ocr import make_scanned_pdf

        monkeypatch.setattr(
            "docparse.adapters.parsers.local_ocr.dependency_status",
            lambda: (False, "未安装 paddleocr；pip install -e '.[local-ocr]'"),
        )
        # 默认设置（ocr_engine 未设 → local），扫描页应降级为 warning
        settings = Settings(job_store="memory", file_store="memory", llm_api_key="")
        pipeline = Pipeline(settings=settings, jobs=MemoryJobStore(), files=MemoryFileStore())
        job = pipeline.process("scan.pdf", make_scanned_pdf())
        assert job.status in {JobStatus.SUCCEEDED, JobStatus.NEEDS_REVIEW}
        assert job.error is None
        documents = job.result.package.documents
        assert any("本地 OCR" in warning for warning in documents[0].warnings)
