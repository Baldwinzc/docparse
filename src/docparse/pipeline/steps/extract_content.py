from docparse.adapters.parsers.ocr import get_ocr_client
from docparse.adapters.parsers.registry import parse_bytes
from docparse.pipeline.context import PipelineContext


def extract_content_step(ctx: PipelineContext) -> None:
    ocr = get_ocr_client(ctx.settings)
    documents = []
    for member in ctx.members:
        data = ctx.files.get(member.id)
        document = parse_bytes(data, file_id=member.id, filename=member.filename, ocr=ocr)
        documents.append(document)
    ctx.documents = documents
    ctx.package.documents = documents
