"""扫描件 OCR 的公共口：`OcrClient` 协议 + 云端 TextIn 实现（#22 / #60）。

本地优先、云端默认关（CLAUDE.md 约束 · #94）：`get_ocr_client` 按
`DOCPARSE_OCR_ENGINE` 选 client，**默认 local**（PaddleOCR PP-OCRv6 small +
doc-ori，见 `local_ocr.py` / #99）；`textin` 需显式选，且还要过 #100 的云侧硬闸。
本文件只放协议与云实现；本地实现按同一个协议接在 `local_ocr.py`，
`pdf.py` / `image.py` / `ocr_layout.py` / pipeline 零改动。

TextIn 密钥走 DOCPARSE_TEXTIN_APP_ID / DOCPARSE_TEXTIN_SECRET_CODE，无密钥不崩：
降级为 warning，文档照常进流水线（后续 needs_review），不编文字。

坐标约定：请求带 straighten=1，TextIn 返回的所有 bbox 均以**正立图**为
参照系（官方文档），OcrOutcome.width / height 也是正立后的宽高，
给 #62 版面重建直接用。本地引擎（local_ocr.py）遵同一条约定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import httpx

from docparse.config import Settings, get_settings
from docparse.domain.ir import BoundingBox, TextBlock

TEXTIN_RECOGNIZE_URL = "https://api.textin.com/ai/service/v2/recognize/multipage"
TEXTIN_TIMEOUT_SECONDS = 60.0
TEXTIN_QPS_CODE = 40306


@dataclass
class OcrLine:
    """一行识别结果，bbox 为正立图上的像素坐标。"""

    text: str
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    score: float | None = None


@dataclass
class OcrOutcome:
    """read_image 的统一返回。

    lines 与 width / height 均以正立图为参照系（angle 为 90/270 时
    相对输入图宽高已对调）。识别失败时 lines 为空、warnings 说明原因。
    """

    lines: list[OcrLine] = field(default_factory=list)
    angle: int = 0
    width: float = 0.0
    height: float = 0.0
    warnings: list[str] = field(default_factory=list)


class OcrClient(Protocol):
    def read_image(self, data: bytes, *, filename: str) -> OcrOutcome: ...


def _bbox_from_position(position: list) -> tuple[float, float, float, float]:
    """TextIn position 是四边形 8 个数（左上起顺时针），取外接矩形。"""
    if len(position) < 8:
        return 0.0, 0.0, 0.0, 0.0
    xs = position[0::2]
    ys = position[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def parse_textin_general(payload: dict) -> OcrOutcome:
    """TextIn recognize/multipage 响应 → OcrOutcome（straighten=1 语义）。"""
    result = payload.get("result") or {}
    outcome = OcrOutcome()
    lines: list[OcrLine] = []
    for page_no, page in enumerate(result.get("pages") or []):
        if page_no == 0:
            outcome.angle = int(page.get("angle") or 0) % 360
            # 官方 width / height 是输入图（未转正）的宽高
            raw_width = float(page.get("width") or 0)
            raw_height = float(page.get("height") or 0)
            if outcome.angle % 90 == 0 and outcome.angle % 180 != 0:
                raw_width, raw_height = raw_height, raw_width
            outcome.width, outcome.height = raw_width, raw_height
        for line in page.get("lines") or []:
            text = str(line.get("text") or "").strip()
            if not text:
                continue
            x0, y0, x1, y1 = _bbox_from_position(line.get("position") or [])
            score = line.get("score")
            lines.append(
                OcrLine(
                    text=text,
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    score=float(score) if score is not None else None,
                )
            )
    outcome.lines = lines
    return outcome


class TextinOcrClient:
    """TextIn 通用文字识别 client，自 benchmarks/ocr/engines.py 迁移（#60）。

    header 鉴权、octet-stream 传图、60s 超时；40306 QPS 限流按官方说明
    不重试、只告警。transport 供测试注入 MockTransport。
    """

    def __init__(
        self,
        app_id: str,
        secret_code: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.app_id = app_id
        self.secret_code = secret_code
        self._transport = transport

    def read_image(self, data: bytes, *, filename: str) -> OcrOutcome:
        if not self.app_id or not self.secret_code:
            return OcrOutcome(
                warnings=[
                    "未配置 TextIn 密钥（DOCPARSE_TEXTIN_APP_ID / "
                    f"DOCPARSE_TEXTIN_SECRET_CODE），{filename} 跳过 OCR。"
                ]
            )
        headers = {
            "x-ti-app-id": self.app_id,
            "x-ti-secret-code": self.secret_code,
            "content-type": "application/octet-stream",
        }
        try:
            with httpx.Client(transport=self._transport, timeout=TEXTIN_TIMEOUT_SECONDS) as client:
                response = client.post(
                    TEXTIN_RECOGNIZE_URL,
                    content=data,
                    headers=headers,
                    params={"straighten": 1},
                )
        except httpx.HTTPError as exc:
            return OcrOutcome(warnings=[f"TextIn 请求失败（{filename}）：{exc}"])
        try:
            payload = response.json()
        except ValueError:
            return OcrOutcome(
                warnings=[f"TextIn 返回非 JSON（{filename}）：HTTP {response.status_code}"]
            )
        code = payload.get("code")
        if code != 200:
            message = payload.get("message", "")
            if code == TEXTIN_QPS_CODE:
                return OcrOutcome(
                    warnings=[f"TextIn QPS 限流（{filename}），按官方说明不重试，本页跳过 OCR。"]
                )
            return OcrOutcome(
                warnings=[f"TextIn 识别失败（{filename}）：code={code} message={message}"]
            )
        return parse_textin_general(payload)


_clients: dict[tuple[str, str], TextinOcrClient] = {}


def get_ocr_client(settings: Settings | None = None) -> OcrClient:
    """扫描件用哪个 OCR client，按 DOCPARSE_OCR_ENGINE 选。

    默认 local（本地优先，#94）：出网零次；引擎/权重不可用时只告警、不崩。
    选 textin 时走云实现（密钥为空也返回，read_image 只告警不发请求；#100 再加
    显式开关的硬闸）。两个实现都遵同一个 OcrClient 协议，下游不感知。
    """
    resolved = settings or get_settings()
    if (resolved.ocr_engine or "local").strip().lower() == "textin":
        key = (resolved.textin_app_id, resolved.textin_secret_code)
        if key not in _clients:
            _clients[key] = TextinOcrClient(*key)
        return _clients[key]
    # 懒 import：local_ocr 反向依赖本模块的 OcrLine / OcrOutcome，模块级 import 会成环。
    from docparse.adapters.parsers.local_ocr import get_local_ocr_client

    return get_local_ocr_client(resolved)


def ocr_blocks(outcome: OcrOutcome, *, prefix: str, scale: float = 1.0) -> list[TextBlock]:
    """outcome.lines → IR 字块。scale 把 OCR 像素换算回页面 pt（如 1/zoom）。"""
    return [
        TextBlock(
            block_id=f"{prefix}{i}",
            text=line.text,
            bbox=BoundingBox(
                x0=line.x0 * scale,
                y0=line.y0 * scale,
                x1=line.x1 * scale,
                y1=line.y1 * scale,
            ),
            ocr_confidence=line.score,
        )
        for i, line in enumerate(outcome.lines, start=1)
    ]


def angle_note(outcome: OcrOutcome) -> str | None:
    """整页转正角度留档（写入 warnings），None 表示无需记录。"""
    if outcome.angle:
        return f"OCR 转正角度 angle={outcome.angle}，bbox 以正立图为参照系。"
    return None
