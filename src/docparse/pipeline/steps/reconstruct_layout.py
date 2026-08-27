from docparse.adapters.parsers.ocr_layout import reconstruct_document
from docparse.pipeline.context import PipelineContext


def reconstruct_layout_step(ctx: PipelineContext) -> None:
    """有 pages[].blocks 且无 sheets 时重建伪格子；xlsx 路径原样跳过。"""
    ctx.documents = [reconstruct_document(document) for document in ctx.documents]
    ctx.package.documents = ctx.documents
