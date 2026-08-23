from docparse.domain.fields import Declaration, ExtractedField
from docparse.domain.ir import DocumentIR
from docparse.extraction.assemble import assemble_declaration
from docparse.extraction.fields import extract_fields
from docparse.pipeline.context import PipelineContext


def extract_fields_step(ctx: PipelineContext) -> None:
    """有 sheet 的文档走组装；无 sheet（txt）保留旧锚点。"""
    primary = _primary_document(ctx.documents)
    if primary is not None and primary.sheets:
        declaration = assemble_declaration(
            primary,
            schema=ctx.schema,
            agent=ctx.caller,
        )
        ctx.declaration = declaration
        ctx.package.fields = _flatten_declaration(declaration)
        ctx.package.review_reasons.extend(declaration.review_reasons)
        return
    ctx.package.fields = extract_fields(ctx.documents, schema=ctx.schema, llm=ctx.llm)


def _primary_document(documents: list[DocumentIR]) -> DocumentIR | None:
    """本期一张单只吃主文档。zip 多文件拼单以后改这里，不改路由。"""
    for document in documents:
        if document.sheets:
            return document
    return documents[0] if documents else None


def _flatten_declaration(declaration: Declaration) -> list[ExtractedField]:
    fields = list(declaration.head.values())
    for item in declaration.goods:
        fields.extend(item.fields.values())
    return fields
