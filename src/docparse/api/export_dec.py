"""合单信封。对眼页继续吃 Job；本层只改出口，不解析。"""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from docparse.domain.models import Job, JobStatus
from docparse.schema.loader import Schema, load_schema

OK_CODE = 0
FAIL_CODE = 2
OK_MSG = "操作成功"
FAIL_MSG = "解析失败"
_META_KEY = "_meta"
_SOURCE_KEY = "_source"
_CODES_KEY = "codes"


def to_dec_envelope(job: Job, schema: Schema | None = None) -> dict:
    """Job → Demo `{code, msg, result, dec_results}`。有单就交；只有解析失败不交。"""
    schema = schema or load_schema()
    if job.status == JobStatus.FAILED:
        return _envelope(FAIL_CODE, job.error or FAIL_MSG, False, None)
    declaration = job.result.declaration if job.result is not None else None
    if not declaration:
        return _envelope(FAIL_CODE, FAIL_MSG, False, None)
    return _envelope(OK_CODE, OK_MSG, True, public_declaration(declaration, schema))


def public_declaration(declaration: dict, schema: Schema | None = None) -> dict:
    """剥对眼键，码写进字段，补合单常量。不改传入对象。"""
    schema = schema or load_schema()
    policy = schema.declare_export
    payload = deepcopy(declaration)
    meta = payload.pop(_META_KEY, {}) or {}
    codes = meta.get(_CODES_KEY) or {}
    _apply_codes(payload, codes, schema.goods_array)
    goods = payload.get(schema.goods_array) or []
    for item in goods:
        item.pop(_SOURCE_KEY, None)
        if policy.goods_id:
            item["id"] = str(uuid4())
    payload[schema.goods_array] = goods
    for name, value in policy.constants.items():
        payload[name] = value
    for alias, source in policy.aliases.items():
        payload[alias] = payload.get(source, "")
    return payload


def _apply_codes(payload: dict, codes: dict, goods_array: str) -> None:
    goods = payload.get(goods_array) or []
    for path, code in codes.items():
        text = str(code or "").strip()
        if not text:
            continue
        if path.startswith(f"{goods_array}[") and "." in path:
            index_text, name = path[len(goods_array) + 1 :].split("].", 1)
            try:
                index = int(index_text)
            except ValueError:
                continue
            if 0 <= index < len(goods):
                goods[index][name] = text
            continue
        payload[path] = text


def _envelope(code: int, msg: str, ok: bool, dec_results: dict | None) -> dict:
    return {
        "code": code,
        "msg": msg,
        "result": ok,
        "dec_results": dec_results,
    }
