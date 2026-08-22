from __future__ import annotations

import re
from collections import defaultdict

from docparse.adapters.llm.openai_compat import LLMNotConfiguredError, OpenAICompatClient
from docparse.domain.fields import ExtractedField, FieldStatus
from docparse.domain.ir import DocumentIR, Evidence
from docparse.extraction.head_map import map_document_head
from docparse.schema.loader import FieldSpec, Schema, load_schema


def extract_fields(
    documents: list[DocumentIR],
    schema: Schema | None = None,
    llm: OpenAICompatClient | None = None,
) -> list[ExtractedField]:
    schema = schema or load_schema()
    client = llm or OpenAICompatClient()
    mapped: list[ExtractedField] = []
    for document in documents:
        mapped.extend(map_document_head(document, schema))
    by_name: dict[str, list[ExtractedField]] = defaultdict(list)
    for field in mapped:
        by_name[field.name].append(field)
    used_sheet_kv = any(
        sheet.key_values for document in documents for sheet in document.sheets
    )
    results: list[ExtractedField] = []
    for spec in schema.fields:
        hits = by_name.get(spec.name)
        if hits:
            results.extend(hits)
            continue
        if used_sheet_kv and spec.group == "head":
            results.append(
                ExtractedField(
                    name=spec.name,
                    display_name=spec.display_name,
                    status=FieldStatus.MISSING,
                )
            )
            continue
        results.append(_extract_one(spec, documents, client))
    return results


def _extract_one(
    spec: FieldSpec,
    documents: list[DocumentIR],
    llm: OpenAICompatClient,
) -> ExtractedField:
    preferred = [doc for doc in documents if doc.document_type in spec.sources] or documents
    if "rule" in spec.extractors:
        hit = _rule_extract(spec, preferred)
        if hit is not None:
            return hit
    if "llm" in spec.extractors:
        hit = _llm_extract(spec, preferred, llm)
        if hit is not None:
            return hit
    return ExtractedField(
        name=spec.name,
        display_name=spec.display_name,
        status=FieldStatus.MISSING,
    )


def _rule_extract(spec: FieldSpec, documents: list[DocumentIR]) -> ExtractedField | None:
    for document in documents:
        for page in document.pages:
            for block in page.blocks:
                value = _value_near_anchor(block.text, spec)
                if value:
                    return _accepted(
                        spec,
                        value,
                        document,
                        quote=block.text,
                        page=page.page_number,
                        block_id=block.block_id,
                    )
        for sheet in document.sheets:
            by_addr = {cell.address: cell for cell in sheet.cells}
            for cell in sheet.cells:
                if any(anchor in cell.value for anchor in spec.anchors):
                    neighbor = _right_cell(cell, sheet.cells)
                    candidate = neighbor.value if neighbor else _value_near_anchor(cell.value, spec)
                    if candidate:
                        quote = f"{sheet.name}!{cell.address}:{cell.value}"
                        return _accepted(
                            spec,
                            candidate,
                            document,
                            quote=quote,
                            cell=(neighbor.address if neighbor else cell.address),
                        )
            # 同一行：表头单元格右侧
            for cell in sheet.cells:
                if neighbor := _header_neighbor(cell, by_addr, spec):
                    return _accepted(
                        spec,
                        neighbor.value,
                        document,
                        quote=f"{sheet.name}!{cell.address}/{neighbor.address}",
                        cell=neighbor.address,
                    )
    return None


def _header_neighbor(cell, by_addr: dict, spec: FieldSpec):
    if not any(anchor in cell.value for anchor in spec.anchors):
        return None
    if cell.row is None or cell.column is None:
        return None
    # 尝试右侧一格
    for other in by_addr.values():
        if other.row == cell.row and other.column == (cell.column + 1):
            return other
    return None


def _right_cell(cell, cells):
    if cell.row is None or cell.column is None:
        return None
    same_row = [
        item
        for item in cells
        if item.row == cell.row and item.column and item.column > cell.column
    ]
    same_row.sort(key=lambda item: item.column or 0)
    return same_row[0] if same_row else None


def _value_near_anchor(text: str, spec: FieldSpec) -> str | None:
    for anchor in spec.anchors:
        if anchor not in text:
            continue
        after = text.split(anchor, 1)[1]
        after = after.lstrip(" ：:　")
        token = re.split(r"[\s,，;；。]", after, maxsplit=1)[0].strip()
        if spec.pattern and token and re.fullmatch(spec.pattern, token):
            return token
        if token and not spec.pattern:
            return token
        if spec.pattern:
            match = re.search(spec.pattern, text)
            if match:
                return match.group(0)
    if spec.pattern:
        match = re.search(spec.pattern, text)
        if match and any(anchor in text for anchor in spec.anchors):
            return match.group(0)
    return None


def _llm_extract(
    spec: FieldSpec,
    documents: list[DocumentIR],
    llm: OpenAICompatClient,
) -> ExtractedField | None:
    snippets = []
    for document in documents:
        text = document.iter_text()
        if not text.strip():
            continue
        snippets.append(f"# {document.filename} ({document.document_type})\n{text[:4000]}")
    if not snippets:
        return None
    system = (
        "你是单据字段抽取器。只根据给定文本抽取，找不到就返回 null。"
        "禁止编造。输出 JSON："
        '{"value": string|null, "quote": string|null, "filename": string|null}'
    )
    user = (
        f"字段: {spec.display_name} ({spec.name})\n"
        f"锚点: {', '.join(spec.anchors)}\n\n" + "\n\n".join(snippets)
    )
    try:
        payload = llm.complete_json(system=system, user=user, schema_name=spec.name)
    except LLMNotConfiguredError:
        return None
    except Exception:
        return None
    value = payload.get("value")
    if not value:
        return None
    match = payload.get("filename")
    document = next((item for item in documents if item.filename == match), documents[0])
    return _accepted(
        spec,
        str(value),
        document,
        quote=str(payload.get("quote") or value),
        method="llm",
        confidence=0.75,
    )


def _accepted(
    spec: FieldSpec,
    value: str,
    document: DocumentIR,
    *,
    quote: str,
    page: int | None = None,
    block_id: str | None = None,
    cell: str | None = None,
    method: str = "rule",
    confidence: float = 0.9,
) -> ExtractedField:
    return ExtractedField(
        name=spec.name,
        display_name=spec.display_name,
        value=value,
        normalized_value=value.strip(),
        confidence=confidence,
        status=FieldStatus.ACCEPTED,
        extraction_method=method,
        source_document_id=document.document_id,
        evidence=[
            Evidence(
                document_id=document.document_id,
                file_id=document.file_id,
                filename=document.filename,
                page=page,
                block_id=block_id,
                cell=cell,
                quote=quote[:500],
            )
        ],
    )
