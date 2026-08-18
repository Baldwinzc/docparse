from __future__ import annotations

import json
from typing import Any

import httpx

from docparse.config import Settings, get_settings


class LLMNotConfiguredError(RuntimeError):
    pass


class OpenAICompatClient:
    """OpenAI 兼容 Chat Completions。换供应商只改 base_url / model。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str = "result",
    ) -> dict[str, Any]:
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
