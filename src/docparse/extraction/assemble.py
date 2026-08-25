"""多摊表头 + 一张货表 → 一张报关单。按角色，不按公司。"""

from __future__ import annotations

from copy import deepcopy

from docparse.domain.fields import Declaration, ExtractedField, FieldStatus, GoodsItem
from docparse.domain.ir import DocumentIR, Evidence, Sheet
from docparse.domain.models import FieldReview, ReviewEvidence
from docparse.extraction.goods_map import map_document_goods
from docparse.extraction.head_map import map_sheet_head
from docparse.schema.loader import (
    Assembly,
    CodeTables,
    FieldSpec,
    LayoutVocab,
    Schema,
    load_code_tables,
    load_layout_vocab,
    load_schema,
)

_NET_FIELD = "netWt"
_GROSS_FIELD = "grossWt"
_SKIP_CONSUME = frozenset({"exclude"})


def assemble_declaration(
    document: DocumentIR,
    *,
    schema: Schema | None = None,
    codes: CodeTables | None = None,
    vocab: LayoutVocab | None = None,
    agent: dict[str, str] | None = None,
) -> Declaration:
    """有草单抄草单；无草单拼商业单据。辅助 / unknown 不读，不另开一张单。"""
    schema = schema or load_schema()
    codes = codes or load_code_tables()
    vocab = vocab or load_layout_vocab()
    policy = schema.assembly
    sheets = _ordered_sheets(document, policy)
    head = _merge_head(sheets, document, schema)
    _apply_defaults(head, schema)
    _apply_caller_overrides(head, schema, agent)
    _apply_weight_policy(head, schema)
    _reconcile_head(head, sheets, document, schema)
    _note_invoice_numbers(head, sheets, vocab, document, schema)
    _lookup_codes(head, schema, codes)
    _apply_agent(head, schema, agent)
    goods = _lookup_goods(map_document_goods(document, schema), schema, codes)
    reasons = _collect_reasons(head, goods, schema, sheets)
    return Declaration(
        head=head,
        goods=goods,
        review_reasons=reasons,
        has_draft=_has_master(sheets, policy),
        source_roles=[sheet.role for sheet in sheets],
    )


def declaration_payload(declaration: Declaration, schema: Schema | None = None) -> dict:
    """人眼验收用的一张报关单 JSON。缺的键空着，数组字段给 []。"""
    schema = schema or load_schema()
    payload: dict = {}
    for spec in schema.head:
        payload[spec.name] = _json_value(declaration.head.get(spec.name))
    for spec in schema.caller_params:
        payload[spec.name] = _json_value(declaration.head.get(spec.name))
    for spec in schema.empty_arrays:
        payload[spec.name] = []
    payload[schema.goods_array] = [_goods_payload(item, schema) for item in declaration.goods]
    payload["_meta"] = {
        "has_draft": declaration.has_draft,
        "source_roles": declaration.source_roles,
        "review_reasons": declaration.review_reasons,
        "head_status": {
            name: field.status.value for name, field in declaration.head.items() if field.value
        },
        "codes": _code_index(declaration, schema),
    }
    return payload


_REVIEW_STATUSES = {FieldStatus.NEEDS_REVIEW, FieldStatus.INVALID, FieldStatus.CONFLICT}


def declaration_reviews(
    declaration: Declaration, schema: Schema | None = None
) -> list[FieldReview]:
    """字段级复核清单。path 跟目录走；新字段进 YAML 后自动出现。"""
    schema = schema or load_schema()
    reviews: list[FieldReview] = []
    seen: set[str] = set()
    for name, field in declaration.head.items():
        item = _field_review(name, field)
        if item is None:
            continue
        reviews.append(item)
        seen.add(name)
    for index, goods in enumerate(declaration.goods):
        prefix = f"{schema.goods_array}[{index}]"
        for name, field in goods.fields.items():
            path = f"{prefix}.{name}"
            item = _field_review(path, field)
            if item is None:
                continue
            reviews.append(item)
            seen.add(path)
        if goods.review_reasons and prefix not in seen:
            reviews.append(
                FieldReview(
                    path=prefix,
                    status=FieldStatus.NEEDS_REVIEW.value,
                    reasons=list(goods.review_reasons),
                )
            )
            seen.add(prefix)
    for reason in declaration.review_reasons:
        name, sep, detail = reason.partition(":")
        if not sep or name in seen or name.startswith("goods["):
            continue
        reviews.append(
            FieldReview(
                path=name,
                status=FieldStatus.NEEDS_REVIEW.value,
                reasons=[detail],
            )
        )
        seen.add(name)
    return reviews


def _ordered_sheets(document: DocumentIR, policy: Assembly) -> list[Sheet]:
    eligible = [sheet for sheet in document.sheets if sheet.consume not in _SKIP_CONSUME]
    rank = {role: index for index, role in enumerate(policy.role_priority)}
    return sorted(eligible, key=lambda sheet: (rank.get(sheet.role, len(rank)), sheet.name))


def _overwrite_roles(policy: Assembly) -> frozenset[str]:
    """fill=overwrite 的角色当主源。draft 与 declaration_list 都在这里，不写死名字。"""
    names = {role for role, mode in policy.fill.items() if mode == "overwrite"}
    if policy.primary_role:
        names.add(policy.primary_role)
    return frozenset(names)


def _has_master(sheets: list[Sheet], policy: Assembly) -> bool:
    masters = _overwrite_roles(policy)
    return any(sheet.role in masters for sheet in sheets)


def _merge_head(
    sheets: list[Sheet],
    document: DocumentIR,
    schema: Schema,
) -> dict[str, ExtractedField]:
    policy = schema.assembly
    masters = _overwrite_roles(policy)
    has_draft = _has_master(sheets, policy)
    merged: dict[str, ExtractedField] = {}
    for sheet in sheets:
        mode = policy.fill.get(sheet.role, "fill")
        if mode == "ignore":
            continue
        for field in map_sheet_head(sheet, document, schema):
            skip_customs = (
                has_draft
                and sheet.role not in masters
                and field.name in policy.customs_only
            )
            if skip_customs:
                continue
            current = merged.get(field.name)
            if current is None or not (current.value or "").strip():
                merged[field.name] = deepcopy(field)
                continue
            if mode == "overwrite":
                merged[field.name] = deepcopy(field)
    return merged


def _apply_defaults(head: dict[str, ExtractedField], schema: Schema) -> None:
    for name, value in schema.assembly.defaults.items():
        if (head.get(name) and head[name].value) or not value:
            continue
        spec = schema.field(name)
        head[name] = ExtractedField(
            name=name,
            display_name=spec.display_name if spec else name,
            value=value,
            normalized_value=value,
            confidence=1.0,
            status=FieldStatus.ACCEPTED,
            extraction_method="assembly_default",
        )


def _apply_weight_policy(head: dict[str, ExtractedField], schema: Schema) -> None:
    """只有净重时视同重量，不把净重抄进毛重。"""
    policy = schema.assembly.weight
    if policy.copy_net_to_gross:
        return
    net = head.get(_NET_FIELD)
    gross = head.get(_GROSS_FIELD)
    if net is None or not (net.value or "").strip():
        return
    if gross is not None and (gross.value or "").strip():
        return
    if not policy.net_as_weight:
        return
    spec = schema.field(_GROSS_FIELD)
    head[_GROSS_FIELD] = ExtractedField(
        name=_GROSS_FIELD,
        display_name=spec.display_name if spec else _GROSS_FIELD,
        status=FieldStatus.NEEDS_REVIEW,
        extraction_method="assembly",
        validation_errors=["net_is_not_gross"],
    )


def _reconcile_head(
    head: dict[str, ExtractedField],
    sheets: list[Sheet],
    document: DocumentIR,
    schema: Schema,
) -> None:
    names = set(schema.assembly.reconcile)
    if not names:
        return
    by_name: dict[str, dict[str, str]] = {name: {} for name in names}
    for sheet in sheets:
        for field in map_sheet_head(sheet, document, schema):
            if field.name not in names:
                continue
            text = (field.value or "").strip()
            if text:
                by_name[field.name][sheet.name] = text
    for name, values in by_name.items():
        unique = {_fold_number(value) for value in values.values()}
        if len(unique) <= 1:
            continue
        field = head.get(name)
        if field is None:
            continue
        field.status = FieldStatus.NEEDS_REVIEW
        field.validation_errors = [*field.validation_errors, "head_mismatch"]
        field.evidence = [
            *field.evidence,
            Evidence(
                document_id=document.document_id,
                file_id=document.file_id,
                filename=document.filename,
                quote=f"{name}: {values}",
            ),
        ]


def _note_invoice_numbers(
    head: dict[str, ExtractedField],
    sheets: list[Sheet],
    vocab: LayoutVocab,
    document: DocumentIR,
    schema: Schema,
) -> None:
    """发票号目录无槽（#37）。对得上只记账；对不上复核，不塞进现有字段。"""
    vocab_id = schema.assembly.invoice_vocab
    found: dict[str, str] = {}
    for sheet in sheets:
        for pair in sheet.key_values:
            group = vocab.group_for_key(pair.key)
            if group is None or group.id != vocab_id:
                continue
            text = pair.value.strip()
            if text:
                found[sheet.name] = text
    if len({_fold_text(value) for value in found.values()}) <= 1:
        return
    head.setdefault(
        "_invoiceNo",
        ExtractedField(
            name="_invoiceNo",
            display_name="发票号",
            status=FieldStatus.NEEDS_REVIEW,
            extraction_method="assembly",
            source_document_id=document.document_id,
            validation_errors=["invoice_mismatch"],
            evidence=[
                Evidence(
                    document_id=document.document_id,
                    file_id=document.file_id,
                    filename=document.filename,
                    quote=str(found),
                )
            ],
        ),
    )


def _lookup_codes(
    head: dict[str, ExtractedField],
    schema: Schema,
    codes: CodeTables,
) -> None:
    for spec in schema.head:
        field = head.get(spec.name)
        if field is None or not (field.value or "").strip():
            continue
        if not spec.code_table:
            continue
        _apply_lookup(field, spec, codes)


def _lookup_goods(
    items: list[GoodsItem],
    schema: Schema,
    codes: CodeTables,
) -> list[GoodsItem]:
    mapped: list[GoodsItem] = []
    for item in items:
        clone = deepcopy(item)
        for spec in schema.goods:
            field = clone.fields.get(spec.name)
            if field is None or not (field.value or "").strip() or not spec.code_table:
                continue
            _apply_lookup(field, spec, codes)
        mapped.append(clone)
    return mapped


def _apply_lookup(field: ExtractedField, spec: FieldSpec, codes: CodeTables) -> None:
    table = spec.code_table or ""
    raw = (field.value or "").strip()
    try:
        code = codes.lookup(table, raw)
    except ValueError:
        field.status = FieldStatus.NEEDS_REVIEW
        field.validation_errors = [*field.validation_errors, f"code_table_pending:{table}"]
        return
    if code is None:
        field.status = FieldStatus.NEEDS_REVIEW
        field.validation_errors = [*field.validation_errors, f"unknown_code:{table}"]
        return
    # 展示留名称；code 只进 normalized_value，不覆盖格子原文。
    field.normalized_value = code


def _apply_caller_overrides(
    head: dict[str, ExtractedField],
    schema: Schema,
    caller: dict[str, str] | None,
) -> None:
    """覆盖组装默认值（如 cusIEFlag）。只吃 assembly.defaults 里的键，未知键忽略。"""
    values = caller or {}
    for name in schema.assembly.defaults:
        text = (values.get(name) or "").strip()
        if not text:
            continue
        spec = schema.field(name)
        head[name] = ExtractedField(
            name=name,
            display_name=spec.display_name if spec else name,
            value=text,
            normalized_value=text,
            confidence=1.0,
            status=FieldStatus.ACCEPTED,
            extraction_method="caller",
        )


def _field_review(path: str, field: ExtractedField) -> FieldReview | None:
    blocking = field.status in _REVIEW_STATUSES
    missing = field.status == FieldStatus.MISSING and bool(field.validation_errors)
    if not blocking and not missing:
        return None
    reasons = list(field.validation_errors) or [field.status.value]
    return FieldReview(
        path=path,
        status=field.status.value,
        reasons=reasons,
        evidence=[_review_evidence(item) for item in field.evidence],
    )


def _review_evidence(item: Evidence) -> ReviewEvidence:
    sheet = None
    cell = item.cell
    if cell and "!" in cell:
        sheet, cell = cell.split("!", 1)
    return ReviewEvidence(
        sheet=sheet,
        cell=cell,
        page=item.page,
        quote=item.quote,
        filename=item.filename,
    )


def _apply_agent(
    head: dict[str, ExtractedField],
    schema: Schema,
    agent: dict[str, str] | None,
) -> None:
    values = agent or {}
    for spec in schema.caller_params:
        text = (values.get(spec.name) or "").strip()
        if not text:
            continue
        head[spec.name] = ExtractedField(
            name=spec.name,
            display_name=spec.display_name,
            value=text,
            normalized_value=text,
            confidence=1.0,
            status=FieldStatus.ACCEPTED,
            extraction_method="caller",
        )


def _collect_reasons(
    head: dict[str, ExtractedField],
    goods: list[GoodsItem],
    schema: Schema,
    sheets: list[Sheet],
) -> list[str]:
    reasons: list[str] = []
    has_draft = _has_master(sheets, schema.assembly)
    if not has_draft:
        for name in schema.assembly.customs_only:
            field = head.get(name)
            if field is None or not (field.value or "").strip():
                reasons.append(f"{name}:customs_empty")
    for name, field in head.items():
        if field.status == FieldStatus.NEEDS_REVIEW:
            detail = ";".join(field.validation_errors) or field.status.value
            reasons.append(f"{name}:{detail}")
    for index, item in enumerate(goods, start=1):
        reasons.extend(f"goods[{index}]:{reason}" for reason in item.review_reasons)
        for name, field in item.fields.items():
            if field.status == FieldStatus.NEEDS_REVIEW:
                detail = ";".join(field.validation_errors) or field.status.value
                reasons.append(f"goods[{index}].{name}:{detail}")
    return reasons


def _code_index(declaration: Declaration, schema: Schema) -> dict[str, str]:
    """path → code。只收转成功的；展示值仍是名称。"""
    codes: dict[str, str] = {}
    for name, field in declaration.head.items():
        spec = schema.field(name)
        if spec is None or not spec.code_table:
            continue
        code = (field.normalized_value or "").strip()
        text = (field.value or "").strip()
        if code and code != text:
            codes[name] = code
    for index, item in enumerate(declaration.goods):
        for name, field in item.fields.items():
            spec = schema.field(name)
            if spec is None or not spec.code_table:
                continue
            code = (field.normalized_value or "").strip()
            text = (field.value or "").strip()
            if code and code != text:
                codes[f"{schema.goods_array}[{index}].{name}"] = code
    return codes


def _goods_payload(item: GoodsItem, schema: Schema) -> dict:
    payload: dict[str, str] = {}
    for spec in schema.goods:
        if spec.ignore:
            continue
        payload[spec.name] = _json_value(item.fields.get(spec.name))
    payload["_source"] = {
        "role": item.source_role,
        "sheet": item.source_sheet,
        "kind": item.source_kind,
        "review_reasons": item.review_reasons,
    }
    return payload


def _json_value(field: ExtractedField | None) -> str:
    if field is None or field.value is None:
        return ""
    return field.value


def _fold_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def _fold_number(text: str) -> str:
    compact = text.replace(",", "").strip()
    try:
        number = float(compact)
    except ValueError:
        return _fold_text(text)
    if number.is_integer():
        return str(int(number))
    return format(number, "g")
