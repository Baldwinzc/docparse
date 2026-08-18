from uuid import uuid4

from docparse.domain.ir import DocumentIR, Page, TextBlock


def parse_pdf(data: bytes, *, file_id: str, filename: str) -> DocumentIR:
    """文本型 PDF 占位解析。装了 pymupdf 就抽文本，否则只保留二进制提示。"""
    try:
        import fitz  # type: ignore
    except ImportError:
        return DocumentIR(
            document_id=uuid4().hex,
            file_id=file_id,
            filename=filename,
            media_type="application/pdf",
            warnings=["未安装 pymupdf，PDF 仅登记未抽文本。pip install 'docparse[pdf]'"],
            raw_text="",
        )

    doc = fitz.open(stream=data, filetype="pdf")
    pages: list[Page] = []
    texts: list[str] = []
    for index, page in enumerate(doc, start=1):
        blocks: list[TextBlock] = []
        for i, item in enumerate(page.get_text("blocks"), start=1):
            snippet = (item[4] or "").strip()
            if not snippet:
                continue
            blocks.append(TextBlock(block_id=f"p{index}-b{i}", text=snippet))
        pages.append(
            Page(
                page_number=index,
                width=float(page.rect.width),
                height=float(page.rect.height),
                blocks=blocks,
            )
        )
        texts.append(page.get_text())
    return DocumentIR(
        document_id=uuid4().hex,
        file_id=file_id,
        filename=filename,
        media_type="application/pdf",
        pages=pages,
        raw_text="\n".join(texts),
    )
