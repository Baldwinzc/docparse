"""给对眼页用的字段目录。名单只来自 fields.yaml。"""

from __future__ import annotations

from docparse.schema.loader import Schema, load_schema


def _field(spec) -> dict:
    return {
        "name": spec.name,
        "display_name": spec.display_name,
        "default": spec.default,
    }


def schema_catalog(schema: Schema | None = None) -> dict:
    schema = schema or load_schema()
    return {
        "goods_array": schema.goods_array,
        "head": [_field(spec) for spec in schema.head],
        "caller": [_field(spec) for spec in schema.caller_params],
        "goods": [_field(spec) for spec in schema.goods if not spec.ignore],
    }
