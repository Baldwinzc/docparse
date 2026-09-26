from typing import Any, Protocol


class LLMClient(Protocol):
    """模型客户端协议：本地优先，云端默认关，显式配置才外呼（#94）。

    本地端点（内网 vLLM / Ollama，#101）与云端 OpenAI 兼容口实现同一个协议，
    调用方不区分；未显式配置端点时由实现方跳过，不发请求。
    """

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str = "result",
    ) -> dict[str, Any]: ...
