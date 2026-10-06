from typing import Any, Protocol


class LLMClient(Protocol):
    """模型客户端协议：本地优先，云端默认关，显式配置才外呼（#94）。

    档位取值 `DOCPARSE_LLM_ENGINE`（与 `openai_compat.resolve_endpoint` 同一套语义）：
    `local` = 内网 vLLM / Ollama 的 OpenAI 兼容口（默认，不出网）；`cloud` = 云端
    OpenAI 兼容口（需密钥）。两个档位实现同一个协议，调用方不区分。
    """

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str = "result",
    ) -> dict[str, Any]: ...
