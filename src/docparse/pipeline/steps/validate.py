from docparse.extraction.validate import review_reasons, validate_fields
from docparse.pipeline.context import PipelineContext


def validate_step(ctx: PipelineContext) -> None:
    # 已组装的报关单由 #20 闸 Declaration；旧锚点路径仍走字段级骨架校验。
    if ctx.declaration is not None:
        return
    ctx.package.fields = validate_fields(ctx.package.fields, schema=ctx.schema)
    ctx.package.review_reasons.extend(review_reasons(ctx.package.fields))
