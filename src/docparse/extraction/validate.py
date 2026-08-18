from __future__ import annotations

import re

from docparse.domain.fields import ExtractedField, FieldStatus
from docparse.schema.loader import Schema, load_schema

REVIEW_THRESHOLD = 0.8


def validate_fields(
    fields: list[ExtractedField],
    schema: Schema | None = None,
) -> list[ExtractedField]:
    schema = schema or load_schema()
    by_name = {item.name: item for item in fields}
    for spec in schema.fields:
        field = by_name.get(spec.name)
        if field is None:
            continue
        if field.value is None:
            if spec.required:
                field.status = FieldStatus.MISSING
                field.validation_errors.append("必填字段缺失")
            continue
        if spec.pattern and not re.fullmatch(spec.pattern, field.normalized_value or field.value):
            field.status = FieldStatus.INVALID
            field.validation_errors.append(f"不符合格式: {spec.pattern}")
            continue
        if not field.evidence:
            field.status = FieldStatus.NEEDS_REVIEW
            field.validation_errors.append("缺少原文证据")
            continue
        if field.confidence < REVIEW_THRESHOLD:
            field.status = FieldStatus.NEEDS_REVIEW
            field.validation_errors.append("置信度低于阈值")
    return fields


def review_reasons(fields: list[ExtractedField]) -> list[str]:
    reasons: list[str] = []
    for field in fields:
        if field.status in {FieldStatus.NEEDS_REVIEW, FieldStatus.INVALID, FieldStatus.CONFLICT}:
            detail = "; ".join(field.validation_errors) or field.status.value
            reasons.append(f"{field.display_name or field.name}: {detail}")
        if field.status == FieldStatus.MISSING and field.validation_errors:
            reasons.append(f"{field.display_name or field.name}: {field.validation_errors[0]}")
    return reasons
