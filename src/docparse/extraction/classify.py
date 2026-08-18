from docparse.domain.ir import DocumentIR
from docparse.domain.models import DocumentType

_HINTS: list[tuple[DocumentType, tuple[str, ...]]] = [
    (
        DocumentType.CUSTOMS_DECLARATION,
        ("报关单", "海关编号", "境内收发货人", "中华人民共和国海关"),
    ),
    (DocumentType.INVOICE, ("发票号", "增值税发票", "invoice no", "invoice number")),
    (DocumentType.PACKING_LIST, ("装箱单", "packing list")),
    (DocumentType.BILL_OF_LADING, ("提单", "bill of lading", "b/l no")),
    (DocumentType.CONTRACT, ("合同协议号", "销售合同", "contract no")),
]


def classify_document(document: DocumentIR) -> DocumentIR:
    text = "\n".join([document.filename, document.iter_text()]).lower()
    best: DocumentType = DocumentType.UNKNOWN
    score = 0
    for doc_type, keywords in _HINTS:
        hits = sum(1 for word in keywords if word.lower() in text)
        if hits > score:
            best = doc_type
            score = hits
    document.document_type = best.value
    if score == 0:
        document.document_type_confidence = 0.2
    elif score == 1:
        document.document_type_confidence = 0.7
    else:
        document.document_type_confidence = 0.95
    return document
