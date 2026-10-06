from __future__ import annotations

import json
from typing import Any

import httpx

from docparse.adapters.cloud_gate import cloud_blocked_reason
from docparse.config import Settings, get_settings


class LLMNotConfiguredError(RuntimeError):
    pass


class OpenAICompatClient:
    """OpenAI 兼容 Chat Completions。换供应商只改 base_url / model。

    硬闸（#100）：`complete_json` 第一件事就是查 `DOCPARSE_ALLOW_CLOUD`，未显式
    启用时**连 payload / headers 都不构造**就抛 `LLMNotConfiguredError`。调用方
    （`extraction/fields.py`）本来就把这个异常当「没配就不调」，字段保持 missing，
    流水线不崩。密钥判断排在闸门之后：闸门是策略，密钥是配置，先看策略。
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
        if not self.settings.llm_api_key:
            raise LLMNotConfiguredError(
                "未配置 DOCPARSE_LLM_API_KEY，规则抽不到的字段将保持 missing"
            )

        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=60) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError(f"LLM 未返回对象: {schema_name}")
        return parsed
