"""云端外呼硬闸（#100）：未显式启用，云 client 不发 HTTP。

生产侧的**策略闸**。与评测台的 #108 隐私闸同形——`benchmarks/ocr/run.py` 的
`cloud_gate()` 也是「返回跳过原因 / None 放行」，那边管的是「真机样本不喂云引擎」，
这边管的是「云 client 默认不出网」；两条闸都由一个**显式开关**放行，不靠自觉。

判定只看 `DOCPARSE_ALLOW_CLOUD`（默认 false），**不看端点地址**：内网地址
（#101 的 vLLM / Ollama）同样要显式开闸——闸门语义是「默认零外呼」，
不是「猜这个地址算不算公网」。地址判定有误判风险，且不属于本闸的职责。

约束的唯一出处是 CLAUDE.md 的「已对齐的产品约束」；本文件只是它在代码里的落点。
新增任何一个会出网的 client，都在发请求之前调 `cloud_blocked_reason()`。
"""

from __future__ import annotations

CLOUD_SWITCH = "DOCPARSE_ALLOW_CLOUD"


def cloud_blocked_reason(*, allow_cloud: bool) -> str | None:
    """云外呼是否被闸住：被闸住返回原因，None 表示放行。

    只吃一个 bool 不吃 `Settings`——TextIn client 从构造参数拿、LLM client 从
    settings 拿，两条路都能直接调，不必为了闸门把 Settings 塞进 client。
    """

    if allow_cloud:
        return None
    return f"云端外呼未显式启用（{CLOUD_SWITCH} 未设为 true），已跳过，未发出任何请求。"
