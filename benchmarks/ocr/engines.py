"""五个云 OCR 引擎适配器：TextIn 通用 / TextIn 报关单 / 百度 / 阿里云 / 腾讯云。

密钥一律走环境变量，不写入仓库、不落日志：
- TextIn：TEXTIN_APP_ID / TEXTIN_SECRET_CODE
- 百度：BAIDU_OCR_API_KEY / BAIDU_OCR_SECRET_KEY
- 阿里云：ALIBABA_CLOUD_ACCESS_KEY_ID / ALIBABA_CLOUD_ACCESS_KEY_SECRET
- 腾讯云：TENCENT_SECRET_ID / TENCENT_SECRET_KEY

只依赖 httpx 与标准库，不装任何厂商 SDK。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

TIMEOUT = httpx.Timeout(60.0)


class MissingCredentials(RuntimeError):
    pass


class EngineError(RuntimeError):
    pass


class RateLimited(EngineError):
    pass


@dataclass
class OcrBox:
    text: str
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    confidence: float | None = None


@dataclass
class OcrResult:
    engine: str
    boxes: list[OcrBox] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    items: list[dict[str, str]] = field(default_factory=list)
    elapsed_ms: int = 0
    error: str | None = None
    raw: dict[str, Any] | None = None

    def text(self) -> str:
        parts = [box.text for box in self.boxes]
        if self.fields:
            parts.extend(self.fields.values())
        if self.items:
            for row in self.items:
                parts.extend(str(v) for v in row.values())
        return "\n".join(parts)


def env_credential(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    raise MissingCredentials(f"缺少环境变量：{' / '.join(names)}")


def _bbox_from_points(points: list[float]) -> tuple[float, float, float, float]:
    xs = points[0::2]
    ys = points[1::2]
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# 签名：阿里云 ACS3-HMAC-SHA256 / 腾讯云 TC3-HMAC-SHA256


def acs3_authorization(
    access_key_id: str,
    access_key_secret: str,
    *,
    method: str,
    host: str,
    action: str,
    api_version: str,
    date: str,
    nonce: str,
    body: bytes = b"",
    content_type: str | None = None,
    canonical_query: str = "",
) -> dict[str, str]:
    headers: dict[str, str] = {
        "host": host,
        "x-acs-action": action,
        "x-acs-version": api_version,
        "x-acs-date": date,
        "x-acs-signature-nonce": nonce,
    }
    if content_type:
        headers["content-type"] = content_type
    payload_hash = hashlib.sha256(body).hexdigest()
    headers["x-acs-content-sha256"] = payload_hash

    signed = sorted(
        k for k in headers if k in {"host", "content-type"} or k.startswith("x-acs-")
    )
    canonical_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in signed)
    signed_headers = ";".join(signed)
    canonical_request = "\n".join(
        [method.upper(), "/", canonical_query, canonical_headers, signed_headers, payload_hash]
    )
    hashed_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = "ACS3-HMAC-SHA256\n" + hashed_request
    signature = hmac.new(
        access_key_secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    headers["Authorization"] = (
        f"ACS3-HMAC-SHA256 Credential={access_key_id},"
        f"SignedHeaders={signed_headers},Signature={signature}"
    )
    return headers


def tc3_authorization(
    secret_id: str,
    secret_key: str,
    *,
    host: str,
    service: str,
    action: str,
    api_version: str,
    timestamp: int,
    payload: str,
) -> dict[str, str]:
    content_type = "application/json; charset=utf-8"
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = (
        f"POST\n/\n\ncontent-type:{content_type}\nhost:{host}\n\ncontent-type;host\n{payload_hash}"
    )
    date = datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d")
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = (
        f"TC3-HMAC-SHA256\n{timestamp}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    secret_date = _hmac(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac(secret_date, service)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "Authorization": (
            f"TC3-HMAC-SHA256 Credential={secret_id}, SignedHeaders=content-type;host, "
            f"Signature={signature}"
        ),
        "Content-Type": content_type,
        "X-TC-Action": action,
        "X-TC-Version": api_version,
        "X-TC-Timestamp": str(timestamp),
        "Host": host,
    }


# ---------------------------------------------------------------------------
# 解析函数（纯函数，测试用固定 payload 覆盖）


def parse_textin_general(payload: dict[str, Any]) -> list[OcrBox]:
    boxes: list[OcrBox] = []
    result = payload.get("result") or {}
    for page in result.get("pages", []):
        for line in page.get("lines", []):
            pos = line.get("position") or []
            x0, y0, x1, y1 = _bbox_from_points(pos) if len(pos) >= 8 else (0.0, 0.0, 0.0, 0.0)
            boxes.append(
                OcrBox(
                    text=line.get("text", ""),
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    confidence=line.get("score"),
                )
            )
    return boxes


def _iter_customs_objects(node: Any):
    if isinstance(node, dict):
        details = node.get("details")
        if isinstance(details, dict):
            yield node
        for value in node.values():
            yield from _iter_customs_objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_customs_objects(value)


def parse_textin_customs(payload: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, str]]]:
    fields: dict[str, str] = {}
    items: list[dict[str, str]] = []
    for obj in _iter_customs_objects(payload.get("result") or {}):
        details = obj.get("details") or {}
        for key, value in details.items():
            if key == "item_list" and isinstance(value, list):
                for entry in value:
                    if not isinstance(entry, dict):
                        continue
                    row: dict[str, str] = {}
                    for item_key, item_value in entry.items():
                        if isinstance(item_value, dict) and "value" in item_value:
                            row[item_key] = str(item_value.get("value", ""))
                    if row:
                        items.append(row)
            elif isinstance(value, dict) and "value" in value:
                fields[key] = str(value.get("value", ""))
    return fields, items


def parse_baidu(payload: dict[str, Any]) -> list[OcrBox]:
    boxes: list[OcrBox] = []
    for entry in payload.get("words_result", []):
        location = entry.get("location") or {}
        boxes.append(
            OcrBox(
                text=entry.get("words", ""),
                x0=float(location.get("left", 0)),
                y0=float(location.get("top", 0)),
                x1=float(location.get("left", 0)) + float(location.get("width", 0)),
                y1=float(location.get("top", 0)) + float(location.get("height", 0)),
                confidence=entry.get("probability"),
            )
        )
    return boxes


def parse_tencent(payload: dict[str, Any]) -> list[OcrBox]:
    boxes: list[OcrBox] = []
    response = payload.get("Response") or {}
    if "Error" in response:
        err = response["Error"]
        raise EngineError(f"{err.get('Code')}: {err.get('Message')}")
    for entry in response.get("TextDetections", []):
        poly = entry.get("ItemPolygon") or {}
        boxes.append(
            OcrBox(
                text=entry.get("DetectedText", ""),
                x0=float(poly.get("X", 0)),
                y0=float(poly.get("Y", 0)),
                x1=float(poly.get("X", 0)) + float(poly.get("Width", 0)),
                y1=float(poly.get("Y", 0)) + float(poly.get("Height", 0)),
                confidence=entry.get("Confidence"),
            )
        )
    return boxes


def parse_aliyun(payload: dict[str, Any]) -> list[OcrBox]:
    if "Data" not in payload or not payload["Data"]:
        code = payload.get("Code") or payload.get("code")
        message = payload.get("Message") or payload.get("message")
        raise EngineError(f"{code}: {message}")
    data = json.loads(payload["Data"])
    boxes: list[OcrBox] = []
    for word in data.get("prism_wordsInfo", []):
        pos = word.get("pos") or []
        points: list[float] = []
        for point in pos:
            points.append(float(point.get("x", 0)))
            points.append(float(point.get("y", 0)))
        x0, y0, x1, y1 = _bbox_from_points(points) if points else (0.0, 0.0, 0.0, 0.0)
        boxes.append(
            OcrBox(
                text=word.get("word", ""),
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                confidence=word.get("prob"),
            )
        )
    return boxes


# ---------------------------------------------------------------------------
# 引擎


class TextinGeneralEngine:
    name = "textin-general"
    label = "TextIn 通用文字识别"
    url = "https://api.textin.com/ai/service/v2/recognize/multipage"

    def recognize(self, image: bytes) -> OcrResult:
        headers = {
            "x-ti-app-id": env_credential("TEXTIN_APP_ID"),
            "x-ti-secret-code": env_credential("TEXTIN_SECRET_CODE"),
            "content-type": "application/octet-stream",
        }
        start = time.monotonic()
        response = httpx.post(self.url, content=image, headers=headers, timeout=TIMEOUT)
        elapsed = int((time.monotonic() - start) * 1000)
        payload = response.json()
        result = OcrResult(engine=self.name, elapsed_ms=elapsed, raw=payload)
        if payload.get("code") != 200:
            result.error = f"code={payload.get('code')} message={payload.get('message')}"
            if payload.get("code") == 40306:
                raise RateLimited(result.error or "")
            return result
        result.boxes = parse_textin_general(payload)
        return result


class TextinCustomsEngine:
    name = "textin-customs"
    label = "TextIn 报关单专用"
    url = "https://api.textin.com/ai/service/v1/customs_declaration"

    def recognize(self, image: bytes) -> OcrResult:
        headers = {
            "x-ti-app-id": env_credential("TEXTIN_APP_ID"),
            "x-ti-secret-code": env_credential("TEXTIN_SECRET_CODE"),
            "content-type": "application/octet-stream",
        }
        start = time.monotonic()
        response = httpx.post(
            self.url,
            content=image,
            headers=headers,
            params={"split_price": 1, "split_product_info": 1},
            timeout=TIMEOUT,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        payload = response.json()
        result = OcrResult(engine=self.name, elapsed_ms=elapsed, raw=payload)
        if payload.get("code") != 200:
            result.error = f"code={payload.get('code')} message={payload.get('message')}"
            if payload.get("code") == 40306:
                raise RateLimited(result.error or "")
            return result
        result.fields, result.items = parse_textin_customs(payload)
        return result


class BaiduEngine:
    name = "baidu-general"
    label = "百度 通用文字识别标准版"
    token_url = "https://aip.baidubce.com/oauth/2.0/token"
    api_url = "https://aip.baidubce.com/rest/2.0/ocr/v1/general"

    def __init__(self) -> None:
        self._access_token: str | None = None

    def _get_token(self) -> str:
        if self._access_token is None:
            response = httpx.get(
                self.token_url,
                params={
                    "grant_type": "client_credentials",
                    "client_id": env_credential("BAIDU_OCR_API_KEY"),
                    "client_secret": env_credential("BAIDU_OCR_SECRET_KEY"),
                },
                timeout=TIMEOUT,
            )
            payload = response.json()
            if "access_token" not in payload:
                raise EngineError(f"百度获取 access_token 失败：{payload}")
            self._access_token = payload["access_token"]
        return self._access_token

    def recognize(self, image: bytes) -> OcrResult:
        start = time.monotonic()
        response = httpx.post(
            self.api_url,
            params={"access_token": self._get_token()},
            data={"image": base64.b64encode(image).decode("ascii")},
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=TIMEOUT,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        payload = response.json()
        result = OcrResult(engine=self.name, elapsed_ms=elapsed, raw=payload)
        if "words_result" not in payload:
            result.error = f"error_code={payload.get('error_code')} {payload.get('error_msg')}"
            return result
        result.boxes = parse_baidu(payload)
        return result


class AliyunEngine:
    name = "aliyun-general"
    label = "阿里云 通用文字识别"
    host = "ocr-api.cn-hangzhou.aliyuncs.com"
    action = "RecognizeGeneral"
    api_version = "2021-07-07"

    def recognize(self, image: bytes) -> OcrResult:
        headers = acs3_authorization(
            env_credential("ALIBABA_CLOUD_ACCESS_KEY_ID"),
            env_credential("ALIBABA_CLOUD_ACCESS_KEY_SECRET"),
            method="POST",
            host=self.host,
            action=self.action,
            api_version=self.api_version,
            date=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            nonce=uuid.uuid4().hex,
            body=image,
            content_type="application/octet-stream",
        )
        start = time.monotonic()
        response = httpx.post(
            f"https://{self.host}/",
            content=image,
            headers=headers,
            timeout=TIMEOUT,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        payload = response.json()
        result = OcrResult(engine=self.name, elapsed_ms=elapsed, raw=payload)
        try:
            result.boxes = parse_aliyun(payload)
        except EngineError as exc:
            result.error = str(exc)
        return result


class TencentEngine:
    name = "tencent-general"
    label = "腾讯云 通用印刷体识别"
    host = "ocr.tencentcloudapi.com"
    service = "ocr"
    action = "GeneralBasicOCR"
    api_version = "2018-11-19"

    def recognize(self, image: bytes) -> OcrResult:
        payload_body = json.dumps({"ImageBase64": base64.b64encode(image).decode("ascii")})
        headers = tc3_authorization(
            env_credential("TENCENT_SECRET_ID"),
            env_credential("TENCENT_SECRET_KEY"),
            host=self.host,
            service=self.service,
            action=self.action,
            api_version=self.api_version,
            timestamp=int(time.time()),
            payload=payload_body,
        )
        start = time.monotonic()
        response = httpx.post(
            f"https://{self.host}/",
            content=payload_body,
            headers=headers,
            timeout=TIMEOUT,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        payload = response.json()
        result = OcrResult(engine=self.name, elapsed_ms=elapsed, raw=payload)
        try:
            result.boxes = parse_tencent(payload)
        except EngineError as exc:
            result.error = str(exc)
        return result


ALL_ENGINES = [
    TextinGeneralEngine,
    TextinCustomsEngine,
    BaiduEngine,
    AliyunEngine,
    TencentEngine,
]


def build_engines(names: list[str] | None = None) -> list[Any]:
    engines = [cls() for cls in ALL_ENGINES]
    if names:
        engines = [engine for engine in engines if engine.name in names]
    return engines
