"""调用方参数名单跟 fields.yaml 走，不写死 agent*。"""

from __future__ import annotations

from docparse.schema.loader import Schema, load_schema

RESERVED_FORM_KEYS = frozenset({"file", "run"})


def accepted_caller_keys(schema: Schema | None = None) -> list[str]:
    """Form 里可以进组装的键：caller_params + assembly.defaults。"""
    schema = schema or load_schema()
    names = [spec.name for spec in schema.caller_params]
    for name in schema.assembly.defaults:
        if name not in names:
            names.append(name)
    return names


def caller_defaults(schema: Schema | None = None) -> dict[str, str]:
    """YAML 上标了 default 的调用方参数。换申报单位只改 fields.yaml。"""
    schema = schema or load_schema()
    values: dict[str, str] = {}
    for spec in schema.caller_params:
        text = (spec.default or "").strip()
        if text:
            values[spec.name] = text
    return values


def collect_caller(
    form: dict[str, str],
    schema: Schema | None = None,
) -> dict[str, str]:
    """请求里有的键用请求值（可显式传空）；没出现的键补 YAML default。未知键忽略。"""
    schema = schema or load_schema()
    allowed = set(accepted_caller_keys(schema))
    collected: dict[str, str] = {}
    for key, value in form.items():
        if key in RESERVED_FORM_KEYS or key not in allowed:
            continue
        collected[key] = value.strip()
    for key, value in caller_defaults(schema).items():
        collected.setdefault(key, value)
    return {key: value for key, value in collected.items() if value}
