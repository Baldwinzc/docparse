"""评测编排 CLI。

用法（在仓库根目录，用 .venv 解释器）：

    python -m benchmarks.ocr.run fixtures          # 渲染夹具 + GT 到 out/
    python -m benchmarks.ocr.run real-render       # 渲染真机样本页到 out/（本地）
    python -m benchmarks.ocr.run call --engine all # 调引擎（fixtures + real）
    python -m benchmarks.ocr.run report            # 汇总指标到 out/report.md

密钥环境变量见 benchmarks/ocr/README.md。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from benchmarks.ocr import engines as eng
from benchmarks.ocr import fixtures as fx
from benchmarks.ocr import metrics
from benchmarks.ocr import real as real_mod
from benchmarks.ocr.visualize import draw_boxes

OUT_DIR = Path(__file__).resolve().parent / "out"
CALL_INTERVAL_SECONDS = 1.2
MAX_RETRIES = 2


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_fixtures(args: argparse.Namespace) -> None:
    images, gts = fx.build_all()
    for image in images:
        out_path = OUT_DIR / "fixtures" / f"{image.key}-{image.variant}.jpg"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(image.image)
    for key, gt in gts.items():
        gt_dict = {
            "key": key,
            "fields": gt.fields,
            "goods": gt.goods,
            "lines": [asdict(line) for line in gt.lines],
        }
        _write_json(OUT_DIR / "gt" / f"{key}.json", gt_dict)
    print(f"夹具：{len(images)} 张图 → {OUT_DIR / 'fixtures'}，GT → {OUT_DIR / 'gt'}")


def cmd_real_render(args: argparse.Namespace) -> None:
    samples = real_mod.load_real_samples()
    if not samples:
        print(f"未找到真机样本，检查 DOCPARSE_OCR_DEMO_DIR：{real_mod.demo_dir()}")
        return
    for sample in samples:
        for page in sample.pages:
            out_path = OUT_DIR / "real" / f"{page.key}.jpg"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(page.image)
            print(f"{page.key} {page.pdf_name} 第{page.page_number}页 → {out_path}")
        if sample.reference:
            fields = real_mod.peninsula_reference_fields(sample.reference)
            goods = real_mod.peninsula_goods_summary(sample.reference)
            _write_json(OUT_DIR / "real" / "peninsula-reference.json", {
                "fields": fields,
                "goods": goods,
            })


def _call_with_retry(engine, image: bytes) -> eng.OcrResult:
    last_error: Exception | None = None
    for _ in range(MAX_RETRIES + 1):
        try:
            return engine.recognize(image)
        except eng.RateLimited as exc:
            last_error = exc
            time.sleep(5.0)
        except eng.MissingCredentials:
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(3.0)
    return eng.OcrResult(engine=engine.name, error=f"重试{MAX_RETRIES}次后仍失败：{last_error}")


def _run_engine_on(engine, targets: list[tuple[str, bytes]]) -> int:
    error_count = 0
    for key, image in targets:
        result = _call_with_retry(engine, image)
        if result.error:
            error_count += 1
            print(f"  [{engine.name}] {key} 失败：{result.error}")
        normalized = {
            "engine": engine.name,
            "key": key,
            "elapsed_ms": result.elapsed_ms,
            "error": result.error,
            "boxes": [asdict(box) for box in result.boxes],
            "fields": result.fields,
            "items": result.items,
            "text": result.text(),
        }
        _write_json(OUT_DIR / "results" / engine.name / f"{key}.json", normalized)
        if result.raw is not None:
            _write_json(OUT_DIR / "raw" / engine.name / f"{key}.json", result.raw)
        if result.boxes and not result.error:
            viz_path = OUT_DIR / "viz" / engine.name / f"{key}.png"
            draw_boxes(image, result.boxes, viz_path)
        print(f"  [{engine.name}] {key} {result.elapsed_ms}ms boxes={len(result.boxes)}")
        time.sleep(CALL_INTERVAL_SECONDS)
    return error_count


def _targets(args: argparse.Namespace) -> list[tuple[str, bytes]]:
    targets: list[tuple[str, bytes]] = []
    if args.scope in {"fixtures", "all"}:
        images, _ = fx.build_all()
        targets.extend((f"{img.key}-{img.variant}", img.image) for img in images)
    if args.scope in {"real", "all"}:
        for sample in real_mod.load_real_samples():
            targets.extend((page.key, page.image) for page in sample.pages)
    return targets


def cmd_call(args: argparse.Namespace) -> None:
    names = None if args.engine == "all" else [name.strip() for name in args.engine.split(",")]
    engine_list = eng.build_engines(names)
    if not engine_list:
        print("没有匹配的引擎")
        sys.exit(2)
    targets = _targets(args)
    print(f"目标 {len(targets)} 张图，引擎 {[e.name for e in engine_list]}")
    failures = 0
    for engine in engine_list:
        try:
            failures += _run_engine_on(engine, targets)
        except eng.MissingCredentials as exc:
            print(f"  [{engine.name}] 跳过：{exc}")
    print(f"完成，失败 {failures} 次。结果在 {OUT_DIR / 'results'}")


def _load_gt() -> dict[str, fx.FixtureGt]:
    _images, gts = fx.build_all()
    return gts


def _report_fixtures() -> list[dict]:
    gts = _load_gt()
    rows: list[dict] = []
    results_dir = OUT_DIR / "results"
    if not results_dir.exists():
        return rows
    for engine_dir in sorted(results_dir.iterdir()):
        engine = engine_dir.name
        for path in sorted(engine_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            key = data.get("key", "")
            if not key.startswith(("a-", "b-")):
                continue
            fixture_key, variant = key.split("-", 1)
            gt = gts.get(fixture_key)
            if gt is None or data.get("error"):
                rows.append(
                    {
                        "engine": engine,
                        "key": key,
                        "cer": None,
                        "field_hit": None,
                        "elapsed_ms": data.get("elapsed_ms", 0),
                        "error": data.get("error"),
                    }
                )
                continue
            pred_text = data.get("text", "")
            if engine == "textin-customs":
                textin_fields = _textin_fields_for_gt(data)
                field_rows = metrics.field_cer(gt.fields, textin_fields)
                hit = 1 - (sum(c for _, c in field_rows) / len(field_rows)) if field_rows else 0.0
            else:
                hit = metrics.field_hit_rate(gt.fields, pred_text)
            rows.append(
                {
                    "engine": engine,
                    "key": key,
                    "cer": round(metrics.cer(gt.full_text(), pred_text), 4),
                    "field_hit": round(hit, 4),
                    "elapsed_ms": data.get("elapsed_ms", 0),
                    "error": None,
                }
            )
    return rows


def _textin_fields_for_gt(data: dict) -> dict[str, str]:
    from benchmarks.ocr.gt_field_map import GT_TO_TEXTIN

    fields = data.get("fields", {})
    mapped = {}
    for gt_label, textin_key in GT_TO_TEXTIN.items():
        value = fields.get(textin_key)
        if value is not None:
            mapped[gt_label] = str(value)
    return mapped


def _report_real() -> list[dict]:
    rows: list[dict] = []
    ref_path = OUT_DIR / "real" / "peninsula-reference.json"
    reference = None
    if ref_path.exists():
        reference = json.loads(ref_path.read_text(encoding="utf-8"))
    results_dir = OUT_DIR / "results"
    if not results_dir.exists():
        return rows
    for engine_dir in sorted(results_dir.iterdir()):
        engine = engine_dir.name
        for path in sorted(engine_dir.glob("peninsula-*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("error"):
                rows.append({"engine": engine, "key": data["key"], "error": data["error"]})
                continue
            pred_text = data.get("text", "")
            if reference:
                hits = metrics.field_hits(reference["fields"], pred_text)
                hit_rate = sum(1 for _, _, hit in hits if hit) / len(hits)
                rows.append(
                    {
                        "engine": engine,
                        "key": data["key"],
                        "field_hit": round(hit_rate, 4),
                        "elapsed_ms": data.get("elapsed_ms", 0),
                        "misses": [label for label, _, hit in hits if not hit],
                    }
                )
            else:
                rows.append(
                    {"engine": engine, "key": data["key"], "elapsed_ms": data.get("elapsed_ms", 0)}
                )
    return rows


def _fmt(value, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def cmd_report(args: argparse.Namespace) -> None:
    fixture_rows = _report_fixtures()
    real_rows = _report_real()
    lines: list[str] = ["# OCR 实测指标（生成物，验收报告见 docs/ocr-benchmark.md）", ""]

    lines.append("## 夹具逐图")
    lines.append("| 引擎 | 图 | CER | 字段命中 | 耗时ms | 错误 |")
    lines.append("|---|---|---|---|---|---|")
    for row in fixture_rows:
        lines.append(
            f"| {row['engine']} | {row['key']} | {_fmt(row['cer'])} | {_fmt(row['field_hit'])} "
            f"| {row['elapsed_ms']} | {row.get('error') or ''} |"
        )

    by_engine: dict[str, dict] = {}
    for row in fixture_rows:
        if row.get("cer") is None:
            continue
        stat = by_engine.setdefault(row["engine"], {"cer": [], "hit": [], "ms": []})
        stat["cer"].append(row["cer"])
        stat["hit"].append(row["field_hit"])
        stat["ms"].append(row["elapsed_ms"])

    lines.append("")
    lines.append("## 夹具汇总")
    lines.append("| 引擎 | 平均CER | 平均字段命中 | 平均耗时ms | 样本数 |")
    lines.append("|---|---|---|---|---|")
    for engine, stat in sorted(by_engine.items()):
        cer_avg = sum(stat["cer"]) / len(stat["cer"])
        hit_avg = sum(stat["hit"]) / len(stat["hit"])
        ms_avg = sum(stat["ms"]) / len(stat["ms"])
        lines.append(
            f"| {engine} | {cer_avg:.4f} | {hit_avg:.4f} | {ms_avg:.0f} | {len(stat['cer'])} |"
        )

    lines.append("")
    lines.append("## 旋转鲁棒性（夹具，仅旋转变体）")
    lines.append("| 引擎 | 变体 | CER |")
    lines.append("|---|---|---|")
    for row in fixture_rows:
        variant = row["key"].split("-", 1)[-1]
        if variant in {"rot90", "rot180", "rot270"} and row.get("cer") is not None:
            lines.append(f"| {row['engine']} | {row['key']} | {_fmt(row['cer'])} |")

    if real_rows:
        lines.append("")
        lines.append("## 半岛真机（对采购系统识别结果）")
        lines.append("| 引擎 | 页 | 字段命中 | 耗时ms | 未命中 |")
        lines.append("|---|---|---|---|---|")
        for row in real_rows:
            if "error" in row and row.get("error"):
                lines.append(f"| {row['engine']} | {row.get('key')} | - | - | {row['error']} |")
            else:
                misses = "、".join(row.get("misses", []))
                lines.append(
                    f"| {row['engine']} | {row['key']} | {_fmt(row.get('field_hit'))} "
                    f"| {row.get('elapsed_ms')} | {misses} |"
                )

    report_path = OUT_DIR / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"报告生成：{report_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benchmarks.ocr.run")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("fixtures").set_defaults(func=cmd_fixtures)

    sub.add_parser("real-render").set_defaults(func=cmd_real_render)

    call = sub.add_parser("call")
    call.add_argument("--engine", default="all", help="all 或逗号分隔引擎名")
    call.add_argument("--scope", default="all", choices=["fixtures", "real", "all"])
    call.set_defaults(func=cmd_call)

    sub.add_parser("report").set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
