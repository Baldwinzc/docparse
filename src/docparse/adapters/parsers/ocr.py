"""云 OCR：TextIn 通用文字识别（#60 实测选型，docs/ocr-benchmark.md）。

模型只走云 API（CLAUDE.md 约束），不装本地引擎。密钥走
DOCPARSE_TEXTIN_APP_ID / DOCPARSE_TEXTIN_SECRET_CODE，无密钥不崩：
降级为 warning，文档照常进流水线（后续 needs_review），不编文字。

坐标约定：请求带 straighten=1，TextIn 返回的所有 bbox 均以**正立图**为
参照系（官方文档），OcrOutcome.width / height 也是正立后的宽高，
给 #62 版面重建直接用。
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


def get_ocr_client(settings: Settings | None = None) -> TextinOcrClient:
    """按密钥取共享 client；密钥为空也返回（read_image 只告警不出网）。"""
    resolved = settings or get_settings()
    key = (resolved.textin_app_id, resolved.textin_secret_code)
    if key not in _clients:
        _clients[key] = TextinOcrClient(*key)
    return _clients[key]


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
