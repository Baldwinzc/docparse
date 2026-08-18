from docparse.extraction.fields import extract_fields
from docparse.pipeline.context import PipelineContext


def extract_fields_step(ctx: PipelineContext) -> None:
    ctx.package.fields = extract_fields(ctx.documents, schema=ctx.schema, llm=ctx.llm)
