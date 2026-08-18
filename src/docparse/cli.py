from __future__ import annotations

import argparse
import json
from pathlib import Path

from docparse.pipeline.runner import Pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docparse")
    sub = parser.add_subparsers(dest="command", required=True)

    parse_cmd = sub.add_parser("parse", help="解析本地文件并打印 JSON")
    parse_cmd.add_argument("path", type=Path)

    args = parser.parse_args(argv)
    if args.command == "parse":
        return _parse(args.path)
    return 1


def _parse(path: Path) -> int:
    data = path.read_bytes()
    job = Pipeline().process(path.name, data)
    payload = job.model_dump(mode="json")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if job.status.value != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
