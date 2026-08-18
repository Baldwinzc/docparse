from docparse.extraction.validate import review_reasons, validate_fields
from docparse.pipeline.context import PipelineContext


def validate_step(ctx: PipelineContext) -> None:
    ctx.package.fields = validate_fields(ctx.package.fields, schema=ctx.schema)
    ctx.package.review_reasons.extend(review_reasons(ctx.package.fields))
