from collections import defaultdict

from docparse.domain.fields import FieldStatus
from docparse.pipeline.context import PipelineContext


def reconcile_step(ctx: PipelineContext) -> None:
    """同一压缩包内，同名字段出现多个不同值则标冲突。

    已组装的一张单里货行会重复 gname / gqty，不能按字段名对账。
    zip 多文件拼单以后改 assemble，不在这里按扁列表对。
    """
    if ctx.declaration is not None:
        return
    grouped: dict[str, set[str]] = defaultdict(set)
    for field in ctx.package.fields:
        if field.normalized_value:
            grouped[field.name].add(field.normalized_value)
    for name, values in grouped.items():
        if len(values) > 1:
            ctx.package.conflicts.append(f"{name}: {sorted(values)}")
            for field in ctx.package.fields:
                if field.name == name:
                    field.status = FieldStatus.CONFLICT
                    field.validation_errors.append("跨文件取值不一致")
            ctx.package.review_reasons.append(f"{name} 跨文件不一致")
