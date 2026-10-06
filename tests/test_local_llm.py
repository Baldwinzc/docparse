"""#101 本地 LLM 端点：内网 OpenAI 兼容口（vLLM / Ollama），默认关。

与 #100 共用**同一套开关语义**——闸未显式开，两个档位都不发 HTTP；本地档也照样要
开闸（「本地」不等于「可以随便发请求」，见
[local-models-survey.md](../docs/local-models-survey.md) §5.3）。
本文件断言四件事：

1. 档位解析：默认 `local` 指内网地址；显式 `cloud` 才走云端口，且要求密钥。
2. 开关：闸未开时两档都不发 HTTP，报的是闸门而不是「没配密钥」。
3. 本地档免密钥：空密钥不带 `Authorization` 头，照样跑通 `complete_json`。
4. 守门：`fields.yaml` 里没有字段启用 `llm` extractor——#101 不改抽取行为。

拦截层与 #100 的 [test_offline_gate.py](test_offline_gate.py) 一致：monkeypatch
`httpx.HTTPTransport.handle_request`，断言的是**真实路径**发没发请求，不是替身。

不在本文件范围：消歧**效果**。本地模型够不够用是 #26 / #27 开工时另评的事，
#101 只保证「端点可指内网 + 默认不发请求」。
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from docparse.adapters.cloud_gate import CLOUD_SWITCH
from docparse.adapters.llm import (
    CLOUD_ENGINE,
    LOCAL_ENGINE,
    LLMNotConfiguredError,
    OpenAICompatClient,
    resolve_endpoint,
)
from docparse.config import Settings
from docparse.schema.loader import load_schema

CLOUD_KEY_ENV = "DOCPARSE_LLM_API_KEY"
LOCAL_KEY_ENV = "DOCPARSE_LLM_LOCAL_API_KEY"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"job_store": "memory", "file_store": "memory"}
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def sent(monkeypatch) -> list[httpx.Request]:
    """拦 httpx 默认传输：记账请求并回一个合法的 Chat Completions 响应。

    回 200 + 合法 body（而不是抛 ConnectError），是为了让「开闸后确实打到端点」这条
    能一路走到响应解析，顺带把解析路径也覆盖上。
    """

    requests: list[httpx.Request] = []

    def _handle_request(self, request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = {"choices": [{"message": {"content": json.dumps({"value": "x"})}}]}
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _handle_request)
    return requests


# ---------------------------------------------------------------------------
# 档位解析


class TestEndpointResolution:
    def test_default_engine_is_local(self) -> None:
        """默认必须指内网（本地优先，#94）。翻默认值等于把出厂配置指回云。"""
        assert Settings().llm_engine == LOCAL_ENGINE

    def test_default_local_url_is_not_public(self) -> None:
        """默认地址得是**这台机器**：回环主机名，且不指向任何公网域名。"""
        url = Settings().llm_local_base_url
        host = urlparse(url).hostname or ""
        assert host in LOOPBACK_HOSTS, f"默认本地端点应指向回环地址，实际 {url}"

    def test_local_resolves_local_fields(self) -> None:
        endpoint = resolve_endpoint(
            _settings(
                llm_engine="local",
                llm_local_base_url="http://10.0.0.7:8000/v1/",
                llm_local_model="qwen3:4b",
            )
        )
        assert endpoint.base_url == "http://10.0.0.7:8000/v1/"
        assert endpoint.model == "qwen3:4b"
        assert endpoint.requires_key is False
        assert endpoint.key_env == LOCAL_KEY_ENV

    def test_cloud_resolves_cloud_fields(self) -> None:
        endpoint = resolve_endpoint(
            _settings(llm_engine="cloud", llm_base_url="https://api.openai.com/v1")
        )
        assert endpoint.base_url == "https://api.openai.com/v1"
        assert endpoint.requires_key is True
        assert endpoint.key_env == CLOUD_KEY_ENV

    def test_unknown_engine_falls_back_to_local(self) -> None:
        """档位写错（拼错 / 空）时倒向**不出网**那一档，不倒向云。"""
        for bogus in ("", "  ", "local ", "onprem", "typo"):
            assert resolve_endpoint(_settings(llm_engine=bogus)).requires_key is False

    def test_engine_is_case_insensitive(self) -> None:
        assert resolve_endpoint(_settings(llm_engine=CLOUD_ENGINE.upper())).requires_key is True

    def test_url_is_the_chat_completions_endpoint(self) -> None:
        """换服务端不改协议：两档都落在 `/chat/completions`（#96 §5.1、§8）。"""
        local = resolve_endpoint(_settings(llm_engine="local"))
        cloud = resolve_endpoint(_settings(llm_engine="cloud"))
        assert local.url.endswith("/v1/chat/completions")
        assert cloud.url.endswith("/v1/chat/completions")


# ---------------------------------------------------------------------------
# 与 #100 共用的开关：关着不发，开了才发


class TestGateSharedWith100:
    def test_local_off_does_not_send(self, sent: list[httpx.Request]) -> None:
        """本地档同样过 #100 的闸：没显式开闸就一次请求都不发。"""
        client = OpenAICompatClient(_settings(llm_engine="local", allow_cloud=False))
        with pytest.raises(LLMNotConfiguredError, match=CLOUD_SWITCH):
            client.complete_json(system="s", user="u")
        assert sent == []

    def test_local_off_reports_switch_not_missing_key(self, sent: list[httpx.Request]) -> None:
        """报的必须是闸门，不能误报成「没配密钥」——本地档本来就不需要密钥。"""
        client = OpenAICompatClient(_settings(llm_engine="local", allow_cloud=False))
        with pytest.raises(LLMNotConfiguredError) as excinfo:
            client.complete_json(system="s", user="u")
        assert CLOUD_SWITCH in str(excinfo.value)
        assert LOCAL_KEY_ENV not in str(excinfo.value)

    def test_off_beats_missing_key_order_on_cloud(self, sent: list[httpx.Request]) -> None:
        """云端档没密钥 + 没开闸时，先报闸门——策略先于配置。"""
        client = OpenAICompatClient(
            _settings(llm_engine="cloud", llm_api_key="", allow_cloud=False)
        )
        with pytest.raises(LLMNotConfiguredError, match=CLOUD_SWITCH):
            client.complete_json(system="s", user="u")
        assert sent == []

    def test_local_sends_when_gate_open(self, sent: list[httpx.Request]) -> None:
        """开闸后本地档能对上一个内网 OpenAI 兼容端点跑通 complete_json。"""
        client = OpenAICompatClient(
            _settings(
                llm_engine="local",
                llm_local_base_url="http://127.0.0.1:11434/v1",
                llm_local_model="qwen3:4b",
                allow_cloud=True,
            )
        )
        result = client.complete_json(system="s", user="u")
        assert result == {"value": "x"}
        assert len(sent) == 1
        request = sent[0]
        assert str(request.url) == "http://127.0.0.1:11434/v1/chat/completions"
        assert json.loads(request.content)["model"] == "qwen3:4b"

    def test_local_omits_authorization_without_key(self, sent: list[httpx.Request]) -> None:
        """本地端点通常不鉴权：空密钥就不带 Authorization 头（vLLM 默认不校验）。"""
        client = OpenAICompatClient(
            _settings(llm_engine="local", llm_local_api_key="", allow_cloud=True)
        )
        client.complete_json(system="s", user="u")
        assert "authorization" not in sent[0].headers

    def test_local_carries_key_when_configured(self, sent: list[httpx.Request]) -> None:
        """配了本地密钥就带上——Ollama 要求非空但忽略内容，填了也不能丢。"""
        client = OpenAICompatClient(
            _settings(llm_engine="local", llm_local_api_key="local-token", allow_cloud=True)
        )
        client.complete_json(system="s", user="u")
        assert sent[0].headers["authorization"] == "Bearer local-token"

    def test_cloud_still_requires_key(self, sent: list[httpx.Request]) -> None:
        """云端档的密钥要求不变：开闸但没密钥，仍然不发请求。"""
        client = OpenAICompatClient(
            _settings(llm_engine="cloud", llm_api_key="", allow_cloud=True)
        )
        with pytest.raises(LLMNotConfiguredError, match=CLOUD_KEY_ENV):
            client.complete_json(system="s", user="u")
        assert sent == []

    def test_cloud_sends_with_key(self, sent: list[httpx.Request]) -> None:
        client = OpenAICompatClient(
            _settings(
                llm_engine="cloud",
                llm_base_url="https://api.openai.com/v1",
                llm_api_key="sk-not-a-real-key",
                allow_cloud=True,
            )
        )
        client.complete_json(system="s", user="u")
        assert len(sent) == 1
        assert str(sent[0].url) == "https://api.openai.com/v1/chat/completions"
        assert sent[0].headers["authorization"] == "Bearer sk-not-a-real-key"


# ---------------------------------------------------------------------------
# 守门：本 Issue 不改抽取行为


class TestNoLlmExtractorEnabled:
    def test_no_field_uses_llm_extractor(self) -> None:
        """本 Issue 只换端点，不加 `llm` extractor——字段抽取行为与 #101 前一致。

        真要启用 LLM 抽字段是 #26 / #27 的事，且要先另评本地模型质量（#101 验收）。
        """
        schema = load_schema()
        enabled = [
            spec.name
            for spec in [*schema.head, *schema.fields]
            if "llm" in spec.extractors
        ]
        assert enabled == [], f"#101 不该启用任何 llm extractor，实际启用了 {enabled}"
