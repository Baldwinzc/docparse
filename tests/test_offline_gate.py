"""#100 离线开关：默认不出网 + 零外呼验证。

断言的是「整条链路一次 HTTP 都没发」，靠**拦 transport 层**，不靠拔网线。
与评测台的 #108 隐私闸（`benchmarks/ocr/run.py` 的 `cloud_gate()`）同一条思路：
默认不放行，显式开闸才放行；本文件证明生产侧那条也真的拦住了。

为什么拦 `httpx.HTTPTransport.handle_request` 而不注入 `httpx.MockTransport` 替身：
替身本身就把真实传输换掉了，跑出来「零外呼」是恒真的。要点在于**真实路径**没被碰过，
所以在 httpx 默认传输的入口记账。TextIn OCR 与 OpenAI 兼容口都走 httpx 默认传输，
一个钩子覆盖两个出网点。

**覆盖面**：本文件管的是走 httpx 的进程外请求。不走 httpx 的出网（例如本地引擎首次
运行由 PaddleOCR 自己去拉权重）不在钩子内——那是 #99 / #102 的离线安装课题
（权重随压缩包分发），不是本闸的职责。
"""

from __future__ import annotations

import httpx
import pytest

from docparse.adapters.cloud_gate import CLOUD_SWITCH, cloud_blocked_reason
from docparse.adapters.files.memory import MemoryFileStore
from docparse.adapters.jobs.memory import MemoryJobStore
from docparse.adapters.llm.openai_compat import LLMNotConfiguredError, OpenAICompatClient
from docparse.adapters.parsers.ocr import TextinOcrClient, get_ocr_client
from docparse.config import Settings
from docparse.domain.models import JobStatus
from docparse.pipeline.runner import Pipeline


@pytest.fixture
def egress(monkeypatch) -> list[httpx.Request]:
    """拦 httpx 默认传输：记账每一次真实外呼尝试，并当场断网。

    抛 `httpx.ConnectError` 而不是 `AssertionError`——它是 `httpx.HTTPError` 子类，
    会被两个 client 各自的兜底捕获，于是「开闸后确实会外呼」这条也能在同一个钩子下
    断言（崩溃路径顺带测了），不必为了测它去连真网。
    """
    attempts: list[httpx.Request] = []

    def _handle_request(self, request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError("零外呼验证：出网被 transport 拦截", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _handle_request)
    return attempts


def _cloud_settings(**overrides) -> Settings:
    """云端凭据与 LLM Key **全配齐**、开关保持默认关。

    闸门要拦住的正是这种「看起来已经配好了」的配置：配了密钥不等于允许外发。
    """
    base: dict[str, object] = {
        "job_store": "memory",
        "file_store": "memory",
        "ocr_engine": "textin",
        "textin_app_id": "app-id",
        "textin_secret_code": "secret-code",
        "llm_engine": "cloud",
        "llm_base_url": "https://api.openai.com/v1",
        "llm_api_key": "sk-not-a-real-key",
    }
    base.update(overrides)
    return Settings(**base)


def _pipeline(settings: Settings) -> Pipeline:
    return Pipeline(settings=settings, jobs=MemoryJobStore(), files=MemoryFileStore())


def _scanned_pdf() -> bytes:
    """只嵌一张图、无文字层的 PDF——走 OCR 分支的最小扫描件。"""
    pymupdf = pytest.importorskip("pymupdf")
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100))
    pix.clear_with(90)
    with pymupdf.open() as doc:
        page = doc.new_page(width=400, height=300)
        page.insert_image(pymupdf.Rect(50, 50, 350, 250), stream=pix.tobytes("png"))
        return doc.tobytes()


def _jpeg() -> bytes:
    pymupdf = pytest.importorskip("pymupdf")
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 60))
    pix.clear_with(120)
    return pix.tobytes("jpeg", jpg_quality=90)


def _draft_xlsx() -> bytes:
    """恒信草单夹具。openpyxl 缺了要整模块跳过，所以懒 import。"""
    from xlsx_fixtures import _draft, _workbook

    return _workbook({"草单": _draft})


# ---------------------------------------------------------------------------
# 开关本身


class TestSwitch:
    def test_default_is_off(self) -> None:
        """默认必须关。翻默认值等于把整条闸门拆了，这条盯着它。"""
        assert Settings().allow_cloud is False

    def test_reason_names_the_switch(self) -> None:
        reason = cloud_blocked_reason(allow_cloud=False)
        assert reason is not None
        assert CLOUD_SWITCH in reason

    def test_open_switch_has_no_reason(self) -> None:
        assert cloud_blocked_reason(allow_cloud=True) is None


# ---------------------------------------------------------------------------
# 两个出网点：关着不发，开了才发


class TestCloudOcrGate:
    def test_off_does_not_send(self, egress: list[httpx.Request]) -> None:
        outcome = TextinOcrClient("app-id", "secret-code").read_image(b"x", filename="a.jpg")
        assert egress == []
        assert outcome.lines == []
        assert any(CLOUD_SWITCH in warning for warning in outcome.warnings)

    def test_keys_configured_are_still_blocked(self, egress: list[httpx.Request]) -> None:
        """密钥配齐也照拦；且文案不得误报成「未配置密钥」——那是另一回事。"""
        outcome = TextinOcrClient("app-id", "secret-code").read_image(b"x", filename="a.jpg")
        assert egress == []
        assert not any("密钥" in warning for warning in outcome.warnings)

    def test_open_switch_does_send(self, egress: list[httpx.Request]) -> None:
        client = TextinOcrClient("app-id", "secret-code", allow_cloud=True)
        outcome = client.read_image(b"x", filename="a.jpg")
        assert len(egress) == 1
        assert outcome.lines == []
        assert any("请求失败" in warning for warning in outcome.warnings)


class TestCloudLlmGate:
    def test_off_does_not_send(self, egress: list[httpx.Request]) -> None:
        client = OpenAICompatClient(_cloud_settings())
        with pytest.raises(LLMNotConfiguredError, match=CLOUD_SWITCH):
            client.complete_json(system="s", user="u")
        assert egress == []

    def test_off_beats_missing_key_order(self, egress: list[httpx.Request]) -> None:
        """没密钥 + 没开闸时，报的是闸门——策略先于配置。"""
        client = OpenAICompatClient(_cloud_settings(llm_api_key=""))
        with pytest.raises(LLMNotConfiguredError, match=CLOUD_SWITCH):
            client.complete_json(system="s", user="u")
        assert egress == []

    def test_open_switch_does_send(self, egress: list[httpx.Request]) -> None:
        client = OpenAICompatClient(_cloud_settings(allow_cloud=True))
        with pytest.raises(httpx.ConnectError):
            client.complete_json(system="s", user="u")
        assert len(egress) == 1


# ---------------------------------------------------------------------------
# 整条链路：Issue #100 的核心验收，覆盖纯 xlsx 与扫描 PDF 两条路径


class TestPipelineZeroEgress:
    def test_xlsx_zero_egress(self, egress: list[httpx.Request]) -> None:
        """纯 xlsx：即使云端凭据与 LLM Key 全配齐、引擎选了 textin，也一次不发。"""
        pipeline = _pipeline(_cloud_settings())
        job = pipeline.process("草单.xlsx", _draft_xlsx())
        assert egress == []
        assert job.error is None
        assert job.status is not JobStatus.FAILED

    def test_scanned_pdf_zero_egress(self, egress: list[httpx.Request]) -> None:
        """扫描 PDF：真走到云 OCR 分支，被闸住，只留 warning，不崩。"""
        pipeline = _pipeline(_cloud_settings())
        job = pipeline.process("scan.pdf", _scanned_pdf())
        assert egress == []
        assert job.error is None
        assert job.status is not JobStatus.FAILED
        documents = job.result.package.documents
        assert any(
            CLOUD_SWITCH in warning for document in documents for warning in document.warnings
        )

    def test_scanned_image_default_local_zero_egress(self, egress: list[httpx.Request]) -> None:
        """默认配置（#99 的 local 引擎）：本来就不该有云 client 参与。

        本机没装 `.[local-ocr]` 时走降级路径（只告警），装了就跑真引擎——两条都不出网。
        """
        settings = Settings(
            job_store="memory",
            file_store="memory",
            ocr_engine="local",
            textin_app_id="",
            textin_secret_code="",
            llm_api_key="",
        )
        from docparse.adapters.parsers.local_ocr import LocalOcrClient

        assert isinstance(get_ocr_client(settings), LocalOcrClient)
        job = _pipeline(settings).process("scan.jpg", _jpeg())
        assert egress == []
        assert job.status is not JobStatus.FAILED

    def test_text_llm_field_zero_egress(self, egress: list[httpx.Request], monkeypatch) -> None:
        """链路真的走到 `complete_json` 才算验到了 LLM 出网点。

        xlsx 走 `assemble_declaration` 分支、根本不碰 LLM（上面那条的零外呼因此是
        偏弱的断言），所以这里给真 schema 挂一个只启用了 `llm` 抽取器的探针字段，
        让 `_extract_one` 必然落到 `_llm_extract`。
        """
        from docparse.pipeline import runner as runner_mod
        from docparse.schema.loader import FieldSpec, load_schema

        probe = FieldSpec(
            name="probeField",
            display_name="探针字段",
            extractors=["llm"],
            anchors=[],
        )

        def _schema_with_probe():
            # load_schema 是 lru_cache，直接 append 会污染全局缓存，必须 copy
            schema = load_schema().model_copy(deep=True)
            schema.head.append(probe)
            schema.fields.append(probe)
            return schema

        monkeypatch.setattr(runner_mod, "load_schema", _schema_with_probe)
        job = _pipeline(_cloud_settings()).process("note.txt", "没有任何锚点的正文。".encode())

        assert egress == []
        assert job.status is not JobStatus.FAILED
        fields = {field.name: field for field in job.result.package.fields}
        assert "probeField" in fields, "探针字段没进结果，LLM 分支没被走到，这条断言会失真"
        assert fields["probeField"].value is None
