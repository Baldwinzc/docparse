from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from docparse.adapters.parsers.registry import parse_bytes
from docparse.pipeline.runner import Pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docparse")
    sub = parser.add_subparsers(dest="command", required=True)

    parse_cmd = sub.add_parser("parse", help="解析本地文件并打印任务 JSON")
    parse_cmd.add_argument("path", type=Path)

    layout_cmd = sub.add_parser("layout", help="只打印解析 IR 的键值和表，不做字段映射")
    layout_cmd.add_argument("path", type=Path)

    args = parser.parse_args(argv)
    if args.command == "parse":
        return _parse(args.path)
    if args.command == "layout":
        return _layout(args.path)
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


if __name__ == "__main__":
    raise SystemExit(main())
