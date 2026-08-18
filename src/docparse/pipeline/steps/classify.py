from docparse.extraction.classify import classify_document
from docparse.pipeline.context import PipelineContext


def classify_step(ctx: PipelineContext) -> None:
    ctx.documents = [classify_document(document) for document in ctx.documents]
    ctx.package.documents = ctx.documents
