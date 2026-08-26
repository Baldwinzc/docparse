"""#22 PDF → IR / 图片 OCR。

夹具全部 pymupdf 现场生成（文字层 / 扫描 / rotation），OCR client 全 mock，
离线不访问网络；TextIn client 用 httpx.MockTransport 覆盖。
"""

from __future__ import annotations

import httpx
import pytest

pytest.importorskip("pymupdf")

import pymupdf

from docparse.adapters.parsers.image import parse_image
from docparse.adapters.parsers.ocr import (
    OcrLine,
    OcrOutcome,
    TextinOcrClient,
    get_ocr_client,
    parse_textin_general,
)
from docparse.adapters.parsers.pdf import RENDER_ZOOM, parse_pdf

# ---------------------------------------------------------------------------
# 夹具：pymupdf 现场生成


def make_text_pdf() -> bytes:
    """两行文字的文字层 PDF。"""
    with pymupdf.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 96), "EntryID: ABCD1234567890")
        page.insert_text((72, 120), "GrossWt 1459.62")
        return doc.tobytes()


def make_scanned_pdf(*, rotation: int = 0, width: float = 400, height: float = 300) -> bytes:
    """只嵌一张图、无文字层的 PDF，模拟扫描件；rotation 写进页面元数据。"""
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100))
    pix.clear_with(90)
    with pymupdf.open() as doc:
        page = doc.new_page(width=width, height=height)
        page.insert_image(pymupdf.Rect(50, 50, width - 50, height - 50), stream=pix.tobytes("png"))
        if rotation:
            page.set_rotation(rotation)
        return doc.tobytes()


def make_jpeg() -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 60))
    pix.clear_with(120)
    return pix.tobytes("jpeg", jpg_quality=90)


class MockOcr:
    """记录调用并回放固定 outcome 的 OCR client。"""

    def __init__(self, outcome: OcrOutcome, *, expect_jpeg: bool = True) -> None:
        self.outcome = outcome
        self.expect_jpeg = expect_jpeg
        self.calls: list[bytes] = []
        self.filenames: list[str] = []

    def read_image(self, data: bytes, *, filename: str) -> OcrOutcome:
        self.calls.append(data)
        self.filenames.append(filename)
        if self.expect_jpeg:
            assert data[:3] == b"\xff\xd8\xff", "传给 OCR 的应为 JPEG"
        return self.outcome


# ---------------------------------------------------------------------------
# PDF 文字层


class TestPdfTextLayer:
    def test_blocks_have_bbox_and_text(self) -> None:
        ir = parse_pdf(make_text_pdf(), file_id="f1", filename="a.pdf", ocr=MockOcr(OcrOutcome()))
        assert ir.warnings == []
        page = ir.pages[0]
        assert page.width == 595 and page.height == 842
        assert len(page.blocks) == 2
        first = page.blocks[0]
        assert first.text.startswith("EntryID")
        assert first.bbox is not None
        assert first.bbox.x0 == pytest.approx(72, abs=2)
        assert 80 <= first.bbox.y0 <= 96  # insert_text 的 y 是基线
        assert "ABCD1234567890" in ir.raw_text

    def test_text_layer_wins_no_ocr_call(self) -> None:
        mock = MockOcr(OcrOutcome(lines=[OcrLine(text="不应出现")]))
        ir = parse_pdf(make_text_pdf(), file_id="f1", filename="a.pdf", ocr=mock)
        assert mock.calls == []
        assert all(block.text != "不应出现" for page in ir.pages for block in page.blocks)

    def test_rotation_metadata_page_upright(self) -> None:
        # 页横图竖（半岛形态）：rotation=270，显示坐标系下宽高已对调
        ir = parse_pdf(
            make_scanned_pdf(rotation=270),
            file_id="f1",
            filename="r.pdf",
            ocr=MockOcr(OcrOutcome()),
        )
        page = ir.pages[0]
        assert page.width == 300 and page.height == 400


# ---------------------------------------------------------------------------
# PDF 扫描页 → OCR


class TestPdfScannedOcr:
    def test_ocr_blocks_scaled_back_to_points(self) -> None:
        outcome = OcrOutcome(
            lines=[
                OcrLine(text="EntryID: ABCD1234567890", x0=100, y0=50, x1=500, y1=80, score=0.98)
            ],
            width=400 * RENDER_ZOOM,
            height=300 * RENDER_ZOOM,
        )
        mock = MockOcr(outcome)
        ir = parse_pdf(make_scanned_pdf(), file_id="f1", filename="scan.pdf", ocr=mock)
        assert len(mock.calls) == 1
        assert mock.filenames == ["scan.pdf#p1"]
        page = ir.pages[0]
        block = page.blocks[0]
        assert block.block_id == "p1-o1"
        assert block.text == "EntryID: ABCD1234567890"
        assert block.bbox is not None
        assert block.bbox.x0 == pytest.approx(50.0)
        assert block.bbox.y0 == pytest.approx(25.0)
        assert block.bbox.x1 == pytest.approx(250.0)
        assert block.bbox.y1 == pytest.approx(40.0)
        assert block.ocr_confidence == 0.98
        assert page.width == 400 and page.height == 300
        assert "ABCD1234567890" in ir.raw_text
        assert ir.warnings == []

    def test_content_rotation_swaps_size_and_logs_angle(self) -> None:
        # 无 rotation 元数据、内容旋转 90°（镇发 p1 形态）
        outcome = OcrOutcome(
            lines=[OcrLine(text="中华人民共和国海关出口货物报关单", x0=10, y0=20, x1=300, y1=60)],
            angle=90,
            width=300,
            height=400,
        )
        ir = parse_pdf(make_scanned_pdf(), file_id="f1", filename="z.pdf", ocr=MockOcr(outcome))
        page = ir.pages[0]
        assert page.width == 300 and page.height == 400
        assert any("angle=90" in warning for warning in ir.warnings)

    def test_ocr_failure_keeps_page_with_warning(self) -> None:
        outcome = OcrOutcome(warnings=["TextIn 请求失败（z.pdf#p1）：timeout"])
        ir = parse_pdf(make_scanned_pdf(), file_id="f1", filename="z.pdf", ocr=MockOcr(outcome))
        assert ir.pages[0].blocks == []
        assert ir.raw_text == ""
        assert any("第1页" in warning and "TextIn" in warning for warning in ir.warnings)

    def test_mixed_pdf_text_and_scanned_pages(self) -> None:
        with pymupdf.open() as doc:
            doc.new_page(width=595, height=842).insert_text((72, 96), "EntryID: ABCD1234567890")
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 50))
            doc.new_page(width=400, height=300).insert_image(
                pymupdf.Rect(50, 50, 350, 250), stream=pix.tobytes("png")
            )
            data = doc.tobytes()
        outcome = OcrOutcome(lines=[OcrLine(text="GrossWt 1459.62", x0=0, y0=0, x1=200, y1=30)])
        ir = parse_pdf(data, file_id="f1", filename="mix.pdf", ocr=MockOcr(outcome))
        assert len(ir.pages) == 2
        assert ir.pages[0].blocks[0].block_id == "p1-b1"
        assert ir.pages[1].blocks[0].block_id == "p2-o1"
        assert "ABCD1234567890" in ir.raw_text and "1459.62" in ir.raw_text


# ---------------------------------------------------------------------------
# 图片 → 同一 OCR 入口


class TestImageOcr:
    def test_jpeg_ocr_blocks_and_size(self) -> None:
        outcome = OcrOutcome(
            lines=[OcrLine(text="海关编号 530320260000123456A", x0=10, y0=20, x1=400, y1=60)],
            width=1280,
            height=720,
        )
        ir = parse_image(make_jpeg(), file_id="f1", filename="x.jpg", ocr=MockOcr(outcome))
        page = ir.pages[0]
        assert page.width == 1280 and page.height == 720
        block = page.blocks[0]
        assert block.text == "海关编号 530320260000123456A"
        assert block.bbox is not None and block.bbox.x1 == pytest.approx(400)
        assert "530320260000123456A" in ir.raw_text
        assert ir.warnings == []

    def test_rotated_image_swaps_size(self) -> None:
        outcome = OcrOutcome(
            lines=[OcrLine(text="x", x0=0, y0=0, x1=10, y1=10)], angle=270, width=720, height=1280
        )
        ir = parse_image(make_jpeg(), file_id="f1", filename="x.jpg", ocr=MockOcr(outcome))
        assert ir.pages[0].width == 720 and ir.pages[0].height == 1280
        assert any("angle=270" in warning for warning in ir.warnings)

    def test_ocr_failure_only_warning(self) -> None:
        outcome = OcrOutcome(warnings=["未配置 TextIn 密钥，x.jpg 跳过 OCR。"])
        ir = parse_image(make_jpeg(), file_id="f1", filename="x.jpg", ocr=MockOcr(outcome))
        assert ir.pages[0].blocks == []
        assert ir.warnings and "密钥" in ir.warnings[0]


# ---------------------------------------------------------------------------
# TextIn client（httpx.MockTransport，不出网）


def _transport(payload: dict | None = None, *, status: int = 200, error: Exception | None = None):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if error is not None:
            raise error
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler), calls


def _success_payload() -> dict:
    return {
        "code": 200,
        "message": "success",
        "result": {
            "pages": [
                {
                    "angle": 0,
                    "width": 800,
                    "height": 600,
                    "lines": [
                        {
                            "text": "海关编号 530320260000123456A",
                            "score": 0.99,
                            "position": [10, 20, 400, 20, 400, 50, 10, 50],
                        }
                    ],
                }
            ]
        },
    }


class TestTextinClient:
    def test_success_parse_lines_and_headers(self) -> None:
        transport, calls = _transport(_success_payload())
        client = TextinOcrClient("app-id", "secret", transport=transport)
        outcome = client.read_image(b"\xff\xd8\xffimg", filename="x.jpg")
        assert outcome.warnings == []
        assert len(outcome.lines) == 1
        line = outcome.lines[0]
        assert line.text == "海关编号 530320260000123456A"
        assert (line.x0, line.y0, line.x1, line.y1) == (10, 20, 400, 50)
        assert line.score == 0.99
        assert outcome.width == 800 and outcome.height == 600
        request = calls[0]
        assert request.headers["x-ti-app-id"] == "app-id"
        assert request.headers["x-ti-secret-code"] == "secret"
        assert request.headers["content-type"] == "application/octet-stream"
        assert request.url.params["straighten"] == "1"

    def test_rate_limited_no_retry(self) -> None:
        transport, calls = _transport({"code": 40306, "message": "QPS超过限制"})
        client = TextinOcrClient("app-id", "secret", transport=transport)
        outcome = client.read_image(b"img", filename="x.jpg")
        assert outcome.lines == []
        assert "限流" in outcome.warnings[0]
        assert len(calls) == 1  # 官方要求 40306 不重试

    def test_other_error_code_warns(self) -> None:
        transport, _calls = _transport({"code": 40102, "message": "验证失败"})
        client = TextinOcrClient("app-id", "secret", transport=transport)
        outcome = client.read_image(b"img", filename="x.jpg")
        assert "code=40102" in outcome.warnings[0]

    def test_network_error_warns_not_raises(self) -> None:
        transport, _calls = _transport(error=httpx.ConnectError("boom"))
        client = TextinOcrClient("app-id", "secret", transport=transport)
        outcome = client.read_image(b"img", filename="x.jpg")
        assert "请求失败" in outcome.warnings[0]

    def test_missing_credentials_no_http(self) -> None:
        transport, calls = _transport(_success_payload())
        client = TextinOcrClient("", "", transport=transport)
        outcome = client.read_image(b"img", filename="x.jpg")
        assert "密钥" in outcome.warnings[0]
        assert calls == []


class TestParseTextinGeneral:
    def test_angle_90_swaps_upright_size(self) -> None:
        payload = _success_payload()
        page = payload["result"]["pages"][0]
        page["angle"] = 90
        page["width"] = 1280
        page["height"] = 1440
        outcome = parse_textin_general(payload)
        assert outcome.angle == 90
        assert outcome.width == 1440 and outcome.height == 1280

    def test_skips_empty_lines(self) -> None:
        payload = _success_payload()
        payload["result"]["pages"][0]["lines"].append(
            {"text": "  ", "position": [0, 0, 1, 0, 1, 1, 0, 1]}
        )
        outcome = parse_textin_general(payload)
        assert len(outcome.lines) == 1


# ---------------------------------------------------------------------------
# 流水线：无密钥不崩


class TestPipelineNoCredentials:
    def test_scanned_pdf_without_credentials_needs_review(self) -> None:
        from docparse.adapters.files.memory import MemoryFileStore
        from docparse.adapters.jobs.memory import MemoryJobStore
        from docparse.config import Settings
        from docparse.domain.models import JobStatus
        from docparse.pipeline.runner import Pipeline

        settings = Settings(
            job_store="memory",
            file_store="memory",
            llm_api_key="",
            textin_app_id="",
            textin_secret_code="",
        )
        pipeline = Pipeline(settings=settings, jobs=MemoryJobStore(), files=MemoryFileStore())
        job = pipeline.process("scan.pdf", make_scanned_pdf())
        assert job.status in {JobStatus.SUCCEEDED, JobStatus.NEEDS_REVIEW}
        assert job.error is None
        documents = job.result.package.documents
        assert any("密钥" in warning for warning in documents[0].warnings)

    def test_get_ocr_client_reuses_by_credentials(self) -> None:
        from docparse.config import Settings

        settings = Settings(textin_app_id="a", textin_secret_code="b")
        first = get_ocr_client(settings)
        assert get_ocr_client(settings) is first
        other = get_ocr_client(Settings(textin_app_id="c", textin_secret_code="d"))
        assert other is not first
