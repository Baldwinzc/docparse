from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from docparse.adapters.cloud_gate import cloud_blocked_reason
from docparse.config import Settings, get_settings

LOCAL_ENGINE = "local"
CLOUD_ENGINE = "cloud"


class LLMNotConfiguredError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMEndpoint:
    """一次调用要打的端点：地址 / 模型 / 密钥 / 是否强制密钥。

    本地档（内网 vLLM / Ollama）通常不鉴权，密钥允许为空；云端档必须配密钥，
    缺了就报「未配置」。两档的 payload 与响应结构完全一致，差别只在这几个字段。
    """

    base_url: str
    model: str
    api_key: str
    requires_key: bool
    key_env: str

    @property
    def url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"


def resolve_endpoint(settings: Settings) -> LLMEndpoint:
    """按 DOCPARSE_LLM_ENGINE 选端点。默认 local（本地优先，#94）。

    只看档位、不看地址——与 `cloud_gate` 同一条口径：不猜某个地址算不算内网，
    由配置显式声明。除 `cloud` 外的取值一律按 `local` 处理：档位写错时倒向
    **不出网**的那一档，而不是倒向云。
    """

    if (settings.llm_engine or LOCAL_ENGINE).strip().lower() == CLOUD_ENGINE:
        return LLMEndpoint(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            requires_key=True,
            key_env="DOCPARSE_LLM_API_KEY",
        )
    return LLMEndpoint(
        base_url=settings.llm_local_base_url,
        model=settings.llm_local_model,
        api_key=settings.llm_local_api_key,
        requires_key=False,
        key_env="DOCPARSE_LLM_LOCAL_API_KEY",
    )


class OpenAICompatClient:
    """OpenAI 兼容 Chat Completions。换端点只改档位与地址，协议不变。

    两个档位（#101）：`local`（默认，内网 vLLM / Ollama）与 `cloud`（云端口）。
    走哪档由 `resolve_endpoint` 定，对外仍是同一个
    `complete_json(system, user, schema_name)`——调用方（`extraction/fields.py`）
    不感知端点在哪。

    硬闸（#100）：`complete_json` 第一件事就是查 `DOCPARSE_ALLOW_CLOUD`，未显式
    启用时**连 payload / headers 都不构造**就抛 `LLMNotConfiguredError`。调用方
    本来就把这个异常当「没配就不调」，字段保持 missing，流水线不崩。两档共用这
    一套开关语义——本地端点同样要显式开闸，「本地」不等于「可以随便发请求」
    （#96 §5.3）。密钥判断排在闸门之后：闸门是策略，密钥是配置，先看策略。

    本地档不强制密钥：密钥为空就不带 `Authorization` 头。Ollama 要求非空但忽略
    内容，留空亦可用；vLLM 默认不校验。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str = "result",
    ) -> dict[str, Any]:
        blocked = cloud_blocked_reason(allow_cloud=self.settings.allow_cloud)
        if blocked:
            raise LLMNotConfiguredError(blocked)

        endpoint = resolve_endpoint(self.settings)
        if endpoint.requires_key and not endpoint.api_key:
            raise LLMNotConfiguredError(
                f"未配置 {endpoint.key_env}，规则抽不到的字段将保持 missing"
            )

        payload = {
            "model": endpoint.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if endpoint.api_key:
            headers["Authorization"] = f"Bearer {endpoint.api_key}"
        with httpx.Client(timeout=60) as client:
            response = client.post(endpoint.url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError(f"LLM 未返回对象: {schema_name}")
        return parsed
