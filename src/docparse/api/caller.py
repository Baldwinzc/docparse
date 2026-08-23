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


def collect_caller(
    form: dict[str, str],
    schema: Schema | None = None,
) -> dict[str, str]:
    """只收目录里的键；未知键忽略，空值丢掉。"""
    allowed = set(accepted_caller_keys(schema))
    collected: dict[str, str] = {}
    for key, value in form.items():
        if key in RESERVED_FORM_KEYS or key not in allowed:
            continue
        text = value.strip()
        if text:
            collected[key] = text
    return collected
