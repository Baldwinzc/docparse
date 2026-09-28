"""评测编排 CLI。

用法（在仓库根目录，用 .venv 解释器）：

    python -m benchmarks.ocr.run samples             # 样本清单：几份 / 能否外呼 / 真实角度
    python -m benchmarks.ocr.run fixtures            # 渲染夹具 + GT 到 out/
    python -m benchmarks.ocr.run real-render         # 渲染真机样本页到 out/（本地）
    python -m benchmarks.ocr.run local-list          # 本地引擎清单 + 依赖状态
    python -m benchmarks.ocr.run local-list --probe  # 再真跑一张白底图，验 API
    python -m benchmarks.ocr.run call --engine cloud --scope fixtures
    python -m benchmarks.ocr.run call --engine local --scope fixtures
    python -m benchmarks.ocr.run call --engine local:paddle-v6-small --scope fixtures
    python -m benchmarks.ocr.run report              # 汇总指标到 out/report.md

样本从 `samples.py` 的固定清单取（#109）：跑哪些页、哪页算旋转页、A 组要喂哪份转正图，
全部读清单的 `rotation_truth`，不靠 key 里的字符串猜。`--scope` 分
`fixtures` / `real`（原件页）/ `real-derived`（真机派生件）/ `all`，再可用 `--sample`
按 key 通配挑。

方向处理（#97 归因方法的 A/B/C 三组）：

    --rotate-mode off                     不判方向，喂什么读什么（配已转正的样本 = A 组）
    --rotate-mode auto                    走方向分类自己判（= B 组）
    --rotate-mode force --force-deg 90    跳过判定用指定角度（= C 组）

`--force-deg` 要敲几，直接读 `samples` 清单的「真实角度」——每份样本一个数，不用猜。
三种模式的产物落在**不同目录**（引擎名带 `@auto` / `@force90` 后缀），互不覆盖。

隐私红线（#108）：真机样本（半岛 / 镇发）是客户真实数据，**云引擎默认不发请求**，
只有显式 `--allow-cloud-on-real` 才放行，且会在结果与报告里留痕。

密钥环境变量见 benchmarks/ocr/README.md。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from benchmarks.ocr import engines as eng
from benchmarks.ocr import fixtures as fx
from benchmarks.ocr import local_engines as local
from benchmarks.ocr import metrics
from benchmarks.ocr import real as real_mod
from benchmarks.ocr import samples as sample_mod
from benchmarks.ocr.visualize import draw_boxes

OUT_DIR = Path(__file__).resolve().parent / "out"
CALL_INTERVAL_SECONDS = 1.2
MAX_RETRIES = 2

CLOUD_NAMES = {cls.name for cls in eng.ALL_ENGINES}


@dataclass
class Target:
    """一张待识别的图 + 它的样本档位。

    kind 决定隐私闸：`synthetic`（夹具，程序渲染）可上云；`real`（真机原件）
    默认只走本地引擎。

    `rotation_truth` / `sample_kind` 来自样本清单（#109）：前者是这页的转正角
    （= C 组 `--force-deg`），`rotation` 就是「转正角不为 0」的结论。
    """

    key: str
    image: bytes
    kind: str = "synthetic"
    rotation: bool = False
    rotation_truth: int = 0
    sample_kind: str = "flat"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_rotation_key(key: str, extra: tuple[str, ...] = ()) -> bool:
    """清单**之外**的临时样本才走这里：按 `--rotation-key` 手动点名。

    清单里的样本一律以 `rotation_truth` 为准（#109）——命名法测不出镇发 p1 这种
    「内容转了但名字里没有 rotXX」的页，也会把 `zhenfa-p1-rot90`（转正件，其实是正立的）
    误判成旋转页。
    """

    return key in extra


# ---------------------------------------------------------------------------
# 样本清单（#109）


def cmd_samples(args: argparse.Namespace) -> None:
    """打印固定样本清单：几份、来源、能否外呼、类型、参照、真实角度、未覆盖类。"""

    print(sample_mod.format_listing())
    if args.json:
        payload = {
            "demo_dir": str(sample_mod.demo_dir()),
            "missing_origins": list(sample_mod.missing_origin_keys()),
            "uncovered": [
                {"key": item.key, "label": item.label, "why": item.why, "how": item.how}
                for item in sample_mod.UNCOVERED
            ],
            "rotation_cases": [asdict(case) for case in sample_mod.rotation_cases()],
            "coverage": [asdict(row) for row in sample_mod.coverage_matrix()],
            "samples": [asdict(spec) for spec in sample_mod.sample_specs()],
        }
        path = OUT_DIR / "samples.json"
        _write_json(path, payload)
        print(f"\n机器可读清单 → {path}")


# ---------------------------------------------------------------------------
# 准备样本


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
    """真机页出图到 out/real/。取哪几页读 `samples.py` 的清单，不再硬编码路径。"""

    keys = tuple(args.sample or ())
    samples = sample_mod.load_samples("real", keys)
    if not samples:
        print(f"未找到真机样本，检查 DOCPARSE_OCR_DEMO_DIR：{sample_mod.demo_dir()}")
        print("清单：python -m benchmarks.ocr.run samples")
        return
    for sample in samples:
        spec = sample.spec
        out_path = OUT_DIR / "real" / f"{spec.key}.jpg"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(sample.image)
        print(f"{spec.key} 第{spec.page}页 真实角度{spec.rotation_truth} → {out_path}")

    if args.derived:
        for sample in sample_mod.load_samples("real-derived", keys):
            spec = sample.spec
            out_path = OUT_DIR / "real-derived" / f"{spec.key}.jpg"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(sample.image)
            print(f"{spec.key} 第{spec.page}页 真实角度{spec.rotation_truth} → {out_path}")

    _write_reference_json()


def _write_reference_json() -> None:
    """把清单登记的参照写一份到 out/real/（只有登记了 reference_json 的原件有）。"""

    for origin in sample_mod.origins():
        if not origin.reference_json:
            continue
        ref_path = sample_mod.demo_dir() / origin.reference_json
        if not ref_path.exists():
            print(f"清单登记了参照但文件不在盘上：{ref_path}")
            continue
        reference = real_mod.load_reference_json(ref_path)
        if origin.reference == "peninsula-head-goods":
            payload = {
                "fields": real_mod.peninsula_reference_fields(reference),
                "goods": real_mod.peninsula_goods_summary(reference),
            }
        else:
            payload = reference
        _write_json(OUT_DIR / "real" / f"{origin.key}-reference.json", payload)


# ---------------------------------------------------------------------------
# 本地引擎清单


def cmd_local_list(args: argparse.Namespace) -> None:
    options = local.LocalBuildOptions(device=args.device, ori_invert=args.ori_invert)
    rows = local.local_engine_status(options)
    print(f"{'引擎':<34} {'类型':<12} {'状态':<6} 说明")
    print("-" * 100)
    for row in rows:
        state = "可用" if row.available else "缺依赖"
        print(f"{row.key:<34} {row.kind:<12} {state:<6} {row.reason}")
    print()
    print(f"装本地依赖：{local.LOCAL_OCR_HINT}")
    print("GPU 机器请先按 Paddle 官方装 paddlepaddle-gpu，再装上面的 extra。")
    if args.probe:
        _probe_local_engines(options)


def _probe_local_engines(options: local.LocalBuildOptions) -> None:
    print()
    print("== probe：真构造 + 白底小图跑一遍（第一次上服务器时用它验 API）==")
    for entry in local.local_registry():
        engine = entry.factory(options)
        ok, reason = engine.available()
        if not ok:
            print(f"  [跳过] {entry.key}：{reason}")
            continue
        if entry.kind == "orientation":
            passed, detail = local.probe_orientation(engine)
        else:
            passed, detail = local.probe_engine(engine)
        mark = "OK  " if passed else "失败"
        print(f"  [{mark}] {entry.key}：{detail}")


# ---------------------------------------------------------------------------
# 调用


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


def cloud_gate(engine, target: Target, *, allow_cloud_on_real: bool) -> str | None:
    """返回跳过原因；None 表示可以调。

    真机样本是客户真实数据，云引擎默认一律不发请求（#108 隐私闸）。
    """

    if not getattr(engine, "is_cloud", False):
        return None
    if target.kind != "real":
        return None
    if allow_cloud_on_real:
        return None
    return "真机样本不外呼（隐私红线）：要放行须显式 --allow-cloud-on-real"


def _viz_image(engine, target: Target, result: eng.OcrResult) -> bytes:
    """画框要画在**引擎实际看到的那张图**上：方向层转过就得跟着转。"""

    if not result.rotate_deg:
        return target.image
    try:
        return local.rotate_image_ccw(target.image, result.rotate_deg)
    except Exception:  # noqa: BLE001 —— 画图失败不该拖垮跑数
        return target.image


def _run_engine_on(engine, targets: list[Target], *, allow_cloud_on_real: bool) -> int:
    error_count = 0
    for target in targets:
        skipped = cloud_gate(engine, target, allow_cloud_on_real=allow_cloud_on_real)
        if skipped:
            print(f"  [{engine.name}] {target.key} 跳过：{skipped}")
            continue
        sampler = local.VramSampler()
        sampler.start()
        result = _call_with_retry(engine, target.image)
        vram = sampler.stop()
        if result.error:
            error_count += 1
            print(f"  [{engine.name}] {target.key} 失败：{result.error}")
        normalized = {
            "engine": engine.name,
            "key": target.key,
            "kind": target.kind,
            "rotation": target.rotation,
            "rotation_truth": target.rotation_truth,
            "sample_kind": target.sample_kind,
            "elapsed_ms": result.elapsed_ms,
            "error": result.error,
            "rotate_deg": result.rotate_deg,
            "rotate_source": result.rotate_source,
            "warnings": result.warnings,
            "vram_peak_mb": vram.peak_mb,
            "vram_source": vram.source,
            "vram_note": vram.note,
            "cloud_override": bool(
                allow_cloud_on_real and getattr(engine, "is_cloud", False) and target.kind == "real"
            ),
            "boxes": [asdict(box) for box in result.boxes],
            "fields": result.fields,
            "items": result.items,
            "text": result.text(),
        }
        _write_json(OUT_DIR / "results" / engine.name / f"{target.key}.json", normalized)
        if result.raw is not None:
            _write_json(OUT_DIR / "raw" / engine.name / f"{target.key}.json", result.raw)
        if result.boxes and not result.error:
            viz_path = OUT_DIR / "viz" / engine.name / f"{target.key}.png"
            try:
                draw_boxes(_viz_image(engine, target, result), result.boxes, viz_path)
            except Exception as exc:  # noqa: BLE001 —— 画图是给人看的，失败不该毁掉整批跑数
                print(f"  [{engine.name}] {target.key} 画框失败（不影响指标）：{exc}")
        vram_text = f"{vram.peak_mb}MB/{vram.source}" if vram.peak_mb is not None else vram.source
        print(
            f"  [{engine.name}] {target.key} {result.elapsed_ms}ms "
            f"boxes={len(result.boxes)} 显存={vram_text}"
        )
        time.sleep(CALL_INTERVAL_SECONDS)
    return error_count


def _targets(args: argparse.Namespace) -> list[Target]:
    """待识别目标全部来自样本清单（#109）。

    「哪页算旋转页」读清单的 `rotation_truth`——真机横放页（镇发 p1 / p6）名字里没有
    `rotXX`，按命名猜会漏；而 `zhenfa-p1-rot90` 这种**转正件**名字里有 `rot90`，
    按命名猜又会误判成旋转页。`--rotation-key` 只作手动兜底。
    """

    extra_rotation_keys = tuple(args.rotation_key or ())
    targets: list[Target] = []
    for sample in sample_mod.load_samples(args.scope, tuple(args.sample or ())):
        spec = sample.spec
        targets.append(
            Target(
                key=spec.key,
                image=sample.image,
                kind=spec.target_kind,
                rotation=spec.is_rotation or _is_rotation_key(spec.key, extra_rotation_keys),
                rotation_truth=spec.rotation_truth,
                sample_kind=spec.kind,
            )
        )
    return targets


def _resolve_names(args: argparse.Namespace) -> tuple[list | None, list[str] | None]:
    """把 `--engine` 展开成（云引擎实例, 本地引擎 key 列表）。

    `cloud` = 五朵云；`local` = 全部本地 OCR 档位；`all` = 两者；其余按逗号拆具体名。
    """

    raw = args.engine.strip()
    if raw == "all":
        return eng.build_engines(None), None
    if raw == "cloud":
        return eng.build_engines(None), []
    if raw == "local":
        return [], None
    names = [piece.strip() for piece in raw.split(",") if piece.strip()]
    cloud_names = [name for name in names if not name.startswith("local:")]
    local_names = [name for name in names if name.startswith("local:")]
    unknown = [name for name in cloud_names if name not in CLOUD_NAMES]
    if unknown:
        print(f"未知云引擎：{'、'.join(unknown)}；可选 {'、'.join(sorted(CLOUD_NAMES))}")
        sys.exit(2)
    if not cloud_names and not local_names:
        print("--engine 没给出任何引擎名")
        sys.exit(2)
    if local.DocOriEngine.name in local_names:
        print(
            f"{local.DocOriEngine.name} 是整页方向分类，不是 OCR 引擎，不能直接当引擎跑；"
            "验它用 `local-list --probe`，用它跑数用 `--rotate-mode auto`"
            "（判定角度会记在每页的 rotate_deg 与 warnings 里）"
        )
        sys.exit(2)
    return eng.build_engines(cloud_names), local_names


def build_engine_list(args: argparse.Namespace):
    """展开 `--engine`，并按 `--rotate-mode` 决定要不要包方向层。"""

    cloud, local_names = _resolve_names(args)
    options = local.LocalBuildOptions(device=args.device, ori_invert=args.ori_invert)
    selected = list(cloud)
    if local_names is None or local_names:
        try:
            selected += local.build_local_engines(local_names, options)
        except KeyError as exc:
            print(str(exc))
            sys.exit(2)
    if args.rotate_mode == "off":
        return selected
    ori = local.DocOriEngine(device=args.device, invert=args.ori_invert)
    wrapped = []
    for engine in selected:
        if isinstance(engine, local.DocOriEngine):
            continue  # 方向分类自己不接受再包一层
        wrapped.append(
            local.RotatingEngine(engine, mode=args.rotate_mode, force_deg=args.force_deg, ori=ori)
        )
    return wrapped


def cmd_call(args: argparse.Namespace) -> None:
    engine_list = build_engine_list(args)
    if not engine_list:
        print("没有匹配的引擎")
        sys.exit(2)
    targets = _targets(args)
    if not targets:
        print(f"没有匹配的样本（--scope {args.scope}，--sample {args.sample or '不限'}）")
        print("清单：python -m benchmarks.ocr.run samples")
        sys.exit(2)
    if args.allow_cloud_on_real:
        print(
            "!! --allow-cloud-on-real 已开启：真机样本会发给云引擎。"
            "半岛 / 镇发原件出门即视为已授权，报告里会留痕。"
        )
    rotations = [target.key for target in targets if target.rotation]
    print(f"目标 {len(targets)} 张图，引擎 {[e.name for e in engine_list]}")
    if rotations:
        print(f"其中旋转页 {len(rotations)} 张（按清单 rotation_truth 判）：{'、'.join(rotations)}")
    failures = 0
    for engine in engine_list:
        probe = getattr(engine, "available", None)
        ok, reason = probe() if probe is not None else (True, "可用")
        if not ok:
            print(f"  [{engine.name}] 跳过：{reason}")
            continue
        try:
            failures += _run_engine_on(
                engine, targets, allow_cloud_on_real=args.allow_cloud_on_real
            )
        except eng.MissingCredentials as exc:
            print(f"  [{engine.name}] 跳过：{exc}")
    print(f"完成，失败 {failures} 次。结果在 {OUT_DIR / 'results'}")


# ---------------------------------------------------------------------------
# 汇总


def _load_gt() -> dict[str, fx.FixtureGt]:
    _images, gts = fx.build_all()
    return gts


def _read_results() -> list[dict]:
    results_dir = OUT_DIR / "results"
    if not results_dir.exists():
        return []
    rows: list[dict] = []
    for engine_dir in sorted(results_dir.iterdir()):
        if not engine_dir.is_dir():
            continue
        for path in sorted(engine_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("engine", engine_dir.name)
            rows.append(data)
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


def _fixture_rows() -> list[dict]:
    gts = _load_gt()
    specs = sample_mod.spec_by_key()
    rows: list[dict] = []
    for data in _read_results():
        engine = data.get("engine", "")
        key = data.get("key", "")
        spec = specs.get(key)
        if spec is None or spec.source != "fixture":
            continue
        gt = gts.get(spec.origin)
        base = {
            "engine": engine,
            "key": key,
            "rotation": bool(data.get("rotation")),
            "rotation_truth": data.get("rotation_truth", spec.rotation_truth),
            "elapsed_ms": data.get("elapsed_ms", 0),
            "vram_peak_mb": data.get("vram_peak_mb"),
            "error": data.get("error"),
        }
        if gt is None or data.get("error"):
            rows.append({**base, "cer": None, "field_hit": None})
            continue
        pred_text = data.get("text", "")
        if engine.startswith("textin-customs"):
            field_rows = metrics.field_cer(gt.fields, _textin_fields_for_gt(data))
            hit = 1 - (sum(cost for _, cost in field_rows) / len(field_rows)) if field_rows else 0.0
        else:
            hit = metrics.field_hit_rate(gt.fields, pred_text)
        rows.append(
            {
                **base,
                "cer": round(metrics.cer(gt.full_text(), pred_text), 4),
                "field_hit": round(hit, 4),
            }
        )
    return rows


def _real_rows() -> list[dict]:
    rows: list[dict] = []
    ref_path = OUT_DIR / "real" / "peninsula-reference.json"
    reference = None
    if ref_path.exists():
        reference = json.loads(ref_path.read_text(encoding="utf-8"))
    specs = sample_mod.spec_by_key()
    for data in _read_results():
        key = data.get("key", "")
        spec = specs.get(key)
        # 「对采购系统识别结果的表」只收登记了半岛参照的页
        if spec is None or spec.reference != "peninsula-head-goods":
            continue
        base = {
            "engine": data.get("engine", ""),
            "key": key,
            "rotation": bool(data.get("rotation")),
            "rotation_truth": data.get("rotation_truth", spec.rotation_truth),
            "elapsed_ms": data.get("elapsed_ms", 0),
            "vram_peak_mb": data.get("vram_peak_mb"),
            "cloud_override": bool(data.get("cloud_override")),
        }
        if data.get("error"):
            rows.append({**base, "error": data["error"]})
            continue
        if reference:
            hits = metrics.field_hits(reference["fields"], data.get("text", ""))
            rows.append(
                {
                    **base,
                    "field_hit": round(sum(1 for _, _, hit in hits if hit) / len(hits), 4),
                    "misses": [label for label, _, hit in hits if not hit],
                }
            )
        else:
            rows.append(base)
    return rows


def _goods_rows(region: tuple[float, float, float, float] | None) -> list[dict]:
    """半岛商品行结构：行数对不对、每行的 HS / 单价 / 原产国是不是落在同一行带。"""

    ref_path = OUT_DIR / "real" / "peninsula-reference.json"
    if not ref_path.exists():
        return []
    reference = json.loads(ref_path.read_text(encoding="utf-8"))
    goods = reference.get("goods") or []
    if not goods:
        return []
    rows: list[dict] = []
    specs = sample_mod.spec_by_key()
    for data in _read_results():
        spec = specs.get(data.get("key", ""))
        if spec is None or spec.reference != "peninsula-head-goods" or data.get("error"):
            continue
        stats = metrics.goods_row_structure(
            goods,
            metrics.text_boxes_from_dicts(data.get("boxes", [])),
            anchor_key="codeTs",
            mate_keys=("declPrice", "cusOriginCountry"),
            region=region,
        )
        rows.append({"engine": data.get("engine", ""), "key": data["key"], **stats.as_dict()})
    return rows


def _fmt(value, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _fmt_ms(value) -> str:
    return "-" if value is None else f"{value:.0f}"


def _summary_table(rows: list[dict], title: str, lines: list[str]) -> None:
    """按引擎聚合 CER / 字段命中 / 时延 P50 P95 / 显存峰值。

    调用方负责先把旋转页剔掉——#103 明确要求旋转页不得混进平均分。
    """

    by_engine: dict[str, dict] = {}
    for row in rows:
        if row.get("cer") is None:
            continue
        stat = by_engine.setdefault(row["engine"], {"cer": [], "hit": [], "ms": [], "vram": []})
        stat["cer"].append(row["cer"])
        stat["hit"].append(row["field_hit"])
        stat["ms"].append(row["elapsed_ms"])
        if row.get("vram_peak_mb") is not None:
            stat["vram"].append(row["vram_peak_mb"])

    lines.append("")
    lines.append(f"## {title}")
    if not by_engine:
        lines.append("_（无数据）_")
        return
    lines.append("| 引擎 | 平均CER | 平均字段命中 | 时延P50ms | 时延P95ms | 显存峰值MB | 样本数 |")
    lines.append("|---|---|---|---|---|---|---|")
    for engine, stat in sorted(by_engine.items()):
        latency = metrics.latency_percentiles(stat["ms"])
        vram = max(stat["vram"]) if stat["vram"] else None
        lines.append(
            f"| {engine} | {sum(stat['cer']) / len(stat['cer']):.4f} "
            f"| {sum(stat['hit']) / len(stat['hit']):.4f} "
            f"| {_fmt_ms(latency['p50'])} | {_fmt_ms(latency['p95'])} "
            f"| {_fmt(vram, 1)} | {latency['n']} |"
        )
    lines.append("")
    lines.append(
        "时延分位按各引擎自己的样本数算（n 见上表），样本少时**不要当 SLA 读**；"
        "显存取该引擎全部样本的峰值。"
    )


def cmd_report(args: argparse.Namespace) -> None:
    fixture_rows = _fixture_rows()
    real_rows = _real_rows()
    region = _parse_region(args.goods_region)
    goods_rows = _goods_rows(region)

    lines: list[str] = ["# OCR 实测指标（生成物，验收报告见 docs/）", ""]
    lines.append(f"生成时间（本地）：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(
        f"商品行结构评估区域：{region}（页面像素）"
        if region
        else "商品行结构评估区域：**未指定**（`--goods-region`），行带数按整页算，只能当参考值"
    )
    summary = sample_mod.coverage_summary()
    lines.append(
        f"样本：清单 {summary['samples']} 份"
        f"（真机 {summary['real']} / 夹具 {summary['fixture']}），"
        f"旋转原件页 {summary['rotation_pages']} 张，未覆盖类 {summary['uncovered']} 条"
        "（列清单：`python -m benchmarks.ocr.run samples`）"
    )

    flat = [row for row in fixture_rows if not row.get("rotation")]
    rotated = [row for row in fixture_rows if row.get("rotation")]

    lines.append("")
    lines.append("## 夹具逐图")
    lines.append("| 引擎 | 图 | 真实角度 | CER | 字段命中 | 耗时ms | 显存MB | 错误 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in fixture_rows:
        lines.append(
            f"| {row['engine']} | {row['key']} | {row.get('rotation_truth', 0)} "
            f"| {_fmt(row['cer'])} | {_fmt(row['field_hit'])} "
            f"| {row['elapsed_ms']} | {_fmt(row.get('vram_peak_mb'), 1)} "
            f"| {row.get('error') or ''} |"
        )

    _summary_table(flat, "夹具汇总（平放页；旋转变体已剔到下一张表）", lines)
    _summary_table(rotated, "旋转页单列（#103：不混进上一张表的平均分）", lines)

    lines.append("")
    lines.append("## 半岛真机（对采购系统识别结果）")
    if real_rows:
        lines.append("| 引擎 | 页 | 真实角度 | 字段命中 | 耗时ms | 显存MB | 未命中 |")
        lines.append("|---|---|---|---|---|---|---|")
        for row in real_rows:
            truth = row.get("rotation_truth", 0)
            if row.get("error"):
                lines.append(
                    f"| {row['engine']} | {row.get('key')} | {truth} "
                    f"| - | - | - | {row['error']} |"
                )
            else:
                misses = "、".join(row.get("misses", []))
                lines.append(
                    f"| {row['engine']} | {row.get('key')} | {truth} "
                    f"| {_fmt(row.get('field_hit'))} "
                    f"| {row.get('elapsed_ms')} | {_fmt(row.get('vram_peak_mb'), 1)} | {misses} |"
                )
    else:
        lines.append("_（无数据；out/results 下没有半岛参照页的结果）_")

    lines.append("")
    lines.append("## 半岛商品行结构（行数对不对、每行归属哪一件）")
    if goods_rows:
        lines.append(
            "| 引擎 | 页 | 参照行 | 有锚行 | 识别行带 | 行带比 "
            "| 锚命中 | 行被并 | 归属正确 | 归属率 |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for row in goods_rows:
            lines.append(
                f"| {row['engine']} | {row['key']} | {row['ref_rows']} | {row['anchor_rows']} "
                f"| {row['pred_rows']} | {_fmt(row['row_count_ratio'])} | {row['anchor_found']} "
                f"| {row['merged_rows']} | {row['attached']} | {_fmt(row['attach_rate'])} |"
            )
    else:
        lines.append("_（无数据；需要先跑 real-render 与 call --scope real）_")

    overrides = [row for row in real_rows if row.get("cloud_override")]
    lines.append("")
    lines.append("## 云引擎放行留痕（隐私红线）")
    if overrides:
        lines.append("以下真机样本被**显式** `--allow-cloud-on-real` 放行过，核对是否知情：")
        lines.append("")
        lines.append("| 引擎 | 页 |")
        lines.append("|---|---|")
        for row in overrides:
            lines.append(f"| {row['engine']} | {row['key']} |")
    else:
        lines.append("真机样本上没有任何云引擎调用。")

    report_path = OUT_DIR / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"报告生成：{report_path}")


def _parse_region(text: str | None) -> tuple[float, float, float, float] | None:
    if not text:
        return None
    parts = [piece.strip() for piece in text.split(",")]
    if len(parts) != 4:
        raise SystemExit("--goods-region 需要 4 个数：x0,y0,x1,y1")
    return tuple(float(piece) for piece in parts)  # type: ignore[return-value]


def _add_engine_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--engine",
        default="all",
        help="cloud（五朵云）/ local（全部本地 OCR 档位）/ all / 逗号分隔的具体引擎名",
    )
    parser.add_argument(
        "--rotate-mode",
        default="off",
        choices=["off", "auto", "force"],
        help="方向处理：off（A 组）/ auto（B 组）/ force（C 组，配 --force-deg）",
    )
    parser.add_argument("--force-deg", type=int, default=90, help="force 模式下施加的逆时针角度")
    parser.add_argument(
        "--ori-invert",
        action="store_true",
        help="把方向分类的 90/270 对调（#97 归因：方向搞反是失败来源之一，用开关试）",
    )
    parser.add_argument("--device", default="gpu", help="本地引擎设备：gpu / cpu")
    parser.add_argument(
        "--allow-cloud-on-real",
        action="store_true",
        help="放行真机样本上的云引擎调用（默认拦；隐私红线，见 #108）",
    )
    parser.add_argument(
        "--rotation-key",
        action="append",
        default=[],
        help="强行把某个 key 标为旋转页（清单的 rotation_truth 已自动判；这里只是手动兜底）",
    )
    parser.add_argument(
        "--sample",
        action="append",
        default=[],
        help=(
            "只跑匹配的样本，fnmatch 通配、可重复：--sample 'zhenfa-p*'、--sample zhenfa-p1-rot90"
            "（不带通配符就是精确匹配，`zhenfa-p1` 不会把派生件一起带上）"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benchmarks.ocr.run")
    sub = parser.add_subparsers(dest="command", required=True)

    samples_parser = sub.add_parser("samples", help="列样本清单与覆盖矩阵（#109）")
    samples_parser.add_argument(
        "--json", action="store_true", help="同时把机器可读清单写到 out/samples.json"
    )
    samples_parser.set_defaults(func=cmd_samples)

    sub.add_parser("fixtures").set_defaults(func=cmd_fixtures)

    real_render = sub.add_parser("real-render", help="真机页出图到 out/real/（本地）")
    real_render.add_argument("--derived", action="store_true", help="连真机派生件一起出图")
    real_render.add_argument("--sample", action="append", default=[], help="按 key 通配挑样本")
    real_render.set_defaults(func=cmd_real_render)

    local_list = sub.add_parser("local-list", help="列本地引擎清单与依赖状态")
    local_list.add_argument("--probe", action="store_true", help="真构造并跑一张白底图，验 API")
    local_list.add_argument("--device", default="gpu")
    local_list.add_argument("--ori-invert", action="store_true")
    local_list.set_defaults(func=cmd_local_list)

    call = sub.add_parser("call")
    _add_engine_options(call)
    call.add_argument("--scope", default="all", choices=list(sample_mod.SCOPES))
    call.set_defaults(func=cmd_call)

    report = sub.add_parser("report")
    report.add_argument(
        "--goods-region",
        default=None,
        help="商品行结构的评估区域 x0,y0,x1,y1（页面像素）；不给则按整页行带算",
    )
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
