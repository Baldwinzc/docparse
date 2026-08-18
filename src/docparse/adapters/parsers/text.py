from uuid import uuid4

from docparse.domain.ir import DocumentIR, Page, TextBlock


def parse_text(data: bytes, *, file_id: str, filename: str) -> DocumentIR:
    text = data.decode("utf-8", errors="replace")
    blocks = [
        TextBlock(block_id=f"p1-b{i}", text=line)
        for i, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    return DocumentIR(
        document_id=uuid4().hex,
        file_id=file_id,
        filename=filename,
        media_type="text/plain",
        pages=[Page(page_number=1, blocks=blocks)],
        raw_text=text,
    )
