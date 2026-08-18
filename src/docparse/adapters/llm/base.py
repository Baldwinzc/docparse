from typing import Any, Protocol


class LLMClient(Protocol):
    """云 API 客户端。本阶段只走远程，不加载本地权重。"""

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str = "result",
    ) -> dict[str, Any]: ...
