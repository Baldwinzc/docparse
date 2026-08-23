from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from docparse.adapters.parsers.registry import parse_bytes
from docparse.extraction.assemble import assemble_declaration, declaration_payload
from docparse.extraction.goods_map import map_document_goods, map_sheet_goods
from docparse.extraction.head_map import map_sheet_head
from docparse.pipeline.runner import Pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docparse")
    sub = parser.add_subparsers(dest="command", required=True)

    parse_cmd = sub.add_parser("parse", help="解析本地文件并打印任务 JSON")
    parse_cmd.add_argument("path", type=Path)

    layout_cmd = sub.add_parser("layout", help="只打印解析 IR 的键值和表，不做字段映射")
    layout_cmd.add_argument("path", type=Path)

    head_cmd = sub.add_parser("head", help="按 sheet 打印表头映射，不合并多 sheet")
    head_cmd.add_argument("path", type=Path)

    goods_cmd = sub.add_parser("goods", help="按 sheet 打印商品映射，并打出合并后的一张货表")
    goods_cmd.add_argument("path", type=Path)

    declare_cmd = sub.add_parser("declare", help="组装一张报关单 JSON，不另开第二张")
    declare_cmd.add_argument("path", type=Path)
    declare_cmd.add_argument("--agent-code", default="")
    declare_cmd.add_argument("--agent-name", default="")
    declare_cmd.add_argument("--agent-scc", default="")
    declare_cmd.add_argument("--agent-ciq-code", default="")

    args = parser.parse_args(argv)
    if args.command == "parse":
        return _parse(args.path)
    if args.command == "layout":
        return _layout(args.path)
    if args.command == "head":
        return _head(args.path)
    if args.command == "goods":
        return _goods(args.path)
    if args.command == "declare":
        return _declare(
            args.path,
            {
                "agentCode": args.agent_code,
                "agentName": args.agent_name,
                "agentScc": args.agent_scc,
                "agentCiqCode": args.agent_ciq_code,
            },
        )
    return 1


def _parse(path: Path) -> int:
    data = path.read_bytes()
    job = Pipeline().process(path.name, data)
    payload = job.model_dump(mode="json")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if job.status.value != "failed" else 2


def _layout(path: Path) -> int:
    document = parse_bytes(path.read_bytes(), file_id=uuid4().hex, filename=path.name)
    payload = {
        "filename": document.filename,
        "warnings": document.warnings,
        "sheets": [
            {
                "name": sheet.name,
                "role": sheet.role,
                "consume": sheet.consume,
                "role_confidence": sheet.role_confidence,
                "role_hits": sheet.role_hits,
                "cells": len(sheet.cells),
                "key_values": [item.model_dump() for item in sheet.key_values],
                "tables": [table.model_dump() for table in sheet.tables],
            }
            for sheet in document.sheets
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not document.warnings or document.sheets else 2


def _head(path: Path) -> int:
    document = parse_bytes(path.read_bytes(), file_id=uuid4().hex, filename=path.name)
    payload = {
        "filename": document.filename,
        "sheets": [
            {
                "name": sheet.name,
                "role": sheet.role,
                "consume": sheet.consume,
                "fields": [
                    {
                        "name": field.name,
                        "value": field.value,
                        "status": field.status.value,
                        "evidence": [item.model_dump() for item in field.evidence],
                    }
                    for field in map_sheet_head(sheet, document)
                ],
            }
            for sheet in document.sheets
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _goods(path: Path) -> int:
    document = parse_bytes(path.read_bytes(), file_id=uuid4().hex, filename=path.name)
    payload = {
        "filename": document.filename,
        "sheets": [
            {
                "name": sheet.name,
                "role": sheet.role,
                "consume": sheet.consume,
                "score": items[0].master_score if items else 0,
                "items": [_item_payload(item) for item in items],
            }
            for sheet in document.sheets
            for items in [map_sheet_goods(sheet, document)]
        ],
        "merged": [_item_payload(item) for item in map_document_goods(document)],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _declare(path: Path, agent: dict[str, str]) -> int:
    document = parse_bytes(path.read_bytes(), file_id=uuid4().hex, filename=path.name)
    declaration = assemble_declaration(document, agent=agent)
    print(json.dumps(declaration_payload(declaration), ensure_ascii=False, indent=2))
    return 0


def _item_payload(item) -> dict:
    return {
        "source_role": item.source_role,
        "source_sheet": item.source_sheet,
        "source_kind": item.source_kind,
        "master_score": item.master_score,
        "review_reasons": item.review_reasons,
        "fields": [
            {
                "name": field.name,
                "value": field.value,
                "status": field.status.value,
                "evidence": [ev.model_dump() for ev in field.evidence],
            }
            for field in item.fields.values()
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
