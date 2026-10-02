"""容量与规格实测装置（#98，父 #94）：并发 / 显存 / 时延 → 采购换算。

#97 / #110 回答「哪个准」，本装置回答「买什么机器」。同一批样本、同一引擎
（默认第一期选型 `PP-OCRv6 small` + `doc-ori`），在 CPU 与 GPU 上各跑一遍并发
档位（默认 1/2/4/8），给出**页/秒、票/秒、显存峰值、单页与单票 P50/P95**。

## 并发怎么建模（不是随便开线程）

**一个并发档 = N 个进程，每进程一个引擎实例、自己那一份票（整票不拆）**：

- PaddleOCR 的 predictor 不是线程安全的，GPU 上也靠进程才能真正并行；**进程模型 =
  上线时的部署模型**（一张卡上跑 N 个 worker），读出来的显存才是可用的水位。
- **按票分，不按页分**：一票（= 一份原件 PDF）整个交给一个 worker，票级时延才有
  定义（否则一票的页散在几个 worker 上，票级时延要另定义成 pipeline 窗口，不是
  采购要看的那个数）。分片用轮转（`ticket_index % N == worker_id`），票数够多时均衡。
- 每个 worker **单独进程**跑，是为了显存读数干净：同进程里前一个引擎的模型不释放，
  会把后一个的峰值读虚高（#110 已踩过）。

## 时序怎么定（父进程只编排，不加载模型）

父进程**不建引擎**（否则自己的 CUDA 上下文会污染整卡读数）。它只：备图 → 起 N 个
worker → 等全部 `ready` → 记基线显存 → 落 `go` → 采样 → 收尾。

worker 侧：建引擎（`load_ms`，不计入）→ 预热 `--warmup` 页（不计入）→ 落
`w<N>.ready` → 等 `go` → `t0 = time.time()` → 跑自己分到的票 → `t1`。

- **吞吐**用 makespan：`页/秒 = 总页数 / (max(t1) - go_time)`。t0/t1 是墙钟
  （`time.time()`），跨进程可比；父进程记 `go_time`。预热与模型加载都被排除。
- **时延**用 worker 逐次记的 `elapsed_ms`（单页）与逐票墙钟（单票），父进程合起来算分位。

## 显存两个口径都要报

- **整卡**（`nvidia-smi` 轮询，父进程采）：24 GB 的可用水位与余量看这个——它是
  **含同卡其它进程**的（#110 实测 1 号卡常被别人占着），所以同时记**基线**，报告里
  给「峰值 - 基线」的增量，并注明是否有别人在用卡。
- **进程**（`paddle.device.cuda.max_memory_allocated()`）：N 个 worker 各报一个，
  是模型本体的净占用（不含显存碎片与其它进程）；N 个相加 = 模型侧下限。

## 隐私

只接 `local:*` 引擎，**构造阶段就拒绝云引擎名**——这条链路一次 HTTP 都不发，
与 #108 的隐私闸同一个立场（真机样本是客户数据）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from benchmarks.ocr import local_engines as local
from benchmarks.ocr import metrics
from benchmarks.ocr import samples as sample_mod

OUT_DIR = Path(__file__).resolve().parent / "out" / "capacity"

DEFAULT_ENGINE = "local:paddle-v6-small"
DEFAULT_CONCURRENCY = (1, 2, 4, 8)
DEFAULT_CPU_THREADS = 8
READY_TIMEOUT_SECONDS = 600.0
GO_TIMEOUT_SECONDS = 600.0
POLL_INTERVAL_SECONDS = 0.2


# ---------------------------------------------------------------------------
# 批次模型：票 = 一份原件；一票多页（横放件的页序就是原件页序）


@dataclass
class PageRef:
    id: str
    path: str


@dataclass
class TicketRef:
    id: str
    pages: list[PageRef] = field(default_factory=list)


@dataclass
class Manifest:
    engine: str
    device: str
    rotate_mode: str
    force_deg: int
    tickets: list[TicketRef]
    warmup_pages: list[str] = field(default_factory=list)
    page_count: int = 0
    ticket_count: int = 0

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "device": self.device,
            "rotate_mode": self.rotate_mode,
            "force_deg": self.force_deg,
            "tickets": [asdict(ticket) for ticket in self.tickets],
            "warmup_pages": list(self.warmup_pages),
            "page_count": self.page_count,
            "ticket_count": self.ticket_count,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> Manifest:
        return cls(
            engine=payload["engine"],
            device=payload["device"],
            rotate_mode=payload["rotate_mode"],
            force_deg=int(payload.get("force_deg", 0)),
            tickets=[
                TicketRef(
                    id=ticket["id"],
                    pages=[PageRef(id=page["id"], path=page["path"]) for page in ticket["pages"]],
                )
                for ticket in payload["tickets"]
            ],
            warmup_pages=list(payload.get("warmup_pages", [])),
            page_count=int(payload.get("page_count", 0)),
            ticket_count=int(payload.get("ticket_count", 0)),
        )


def group_tickets(samples: list) -> list[TicketRef]:
    """把扁平样本按原件（= 一票）分组，保持原件出现顺序与页序。

    一票 = 一份原件 PDF（半岛 2 页、镇发 6 页）。`load_samples("real")` 出来的
    base 变体顺序就是页序，直接 append 即可。
    """

    tickets: dict[str, TicketRef] = {}
    order: list[str] = []
    for sample in samples:
        spec = sample.spec
        ticket_id = spec.origin
        if ticket_id not in tickets:
            tickets[ticket_id] = TicketRef(id=ticket_id, pages=[])
            order.append(ticket_id)
        tickets[ticket_id].pages.append(PageRef(id=spec.key, path=""))
    return [tickets[ticket_id] for ticket_id in order]


def expand_batch(tickets: list[TicketRef], repeat: int) -> list[TicketRef]:
    """把一票复制 repeat 份凑样本量：票 id 加 `#r{i}`，避免同名覆盖。"""

    if repeat < 1:
        raise ValueError(f"repeat 必须 >= 1（收到 {repeat}）")
    batch: list[TicketRef] = []
    for index in range(repeat):
        for ticket in tickets:
            batch.append(
                TicketRef(
                    id=f"{ticket.id}#r{index}",
                    pages=[PageRef(id=page.id, path=page.path) for page in ticket.pages],
                )
            )
    return batch


def shard_tickets(tickets: list[TicketRef], worker_id: int, workers: int) -> list[TicketRef]:
    """把票分给 worker：**整票给一个 worker**，且按页数贪心配平（LPT）。

    为什么不是简单轮转：一票的页数不等（半岛 2 页、镇发 6 页），纯轮转在高并发档会把
    短票和长票分开，让 makespan 由拿到长票的 worker 决定——并发越高吞吐反而被算得越低，
    正好把「加并发有没有用」这个采购问题答错。贪心（每次把票丢给当前累计页数最少的
    worker，同分取小号，保证确定性）在页数不齐时也均衡，页数齐时退化成轮转。
    """

    if workers < 1:
        raise ValueError(f"workers 必须 >= 1（收到 {workers}）")
    if not 0 <= worker_id < workers:
        raise ValueError(f"worker_id 越界：{worker_id} / {workers}")
    # LPT 要**先按页数降序**再贪心，否则先到的长票会把某一桶撑爆；同页数按原始下标，
    # 保证「同一批票 → 同一份分片」，可复现。
    order = sorted(range(len(tickets)), key=lambda index: (-len(tickets[index].pages), index))
    buckets: list[list[tuple[int, TicketRef]]] = [[] for _ in range(workers)]
    loads = [0] * workers
    for index in order:
        ticket = tickets[index]
        target = min(range(workers), key=lambda worker: (loads[worker], worker))
        buckets[target].append((index, ticket))
        loads[target] += len(ticket.pages)
    # 每桶按原始票序还原，报告里读起来和清单一致
    return [ticket for _index, ticket in sorted(buckets[worker_id])]


def parse_concurrency(text: str) -> list[int]:
    """`"1,2,4,8"` → `[1, 2, 4, 8]`；去重、升序、去非正数。"""

    values: list[int] = []
    for piece in str(text).split(","):
        piece = piece.strip()
        if not piece:
            continue
        value = int(piece)
        if value < 1:
            raise ValueError(f"并发档必须 >= 1（收到 {value}）")
        if value not in values:
            values.append(value)
    if not values:
        raise ValueError("并发档为空：至少给一个，如 --concurrency 1,2,4")
    return sorted(values)


# ---------------------------------------------------------------------------
# 汇总口径（纯函数，本机不装 paddle 也能测）


@dataclass
class LevelSummary:
    """一个 (设备, 并发档) 的一行结果。"""

    device: str
    engine: str
    concurrency: int
    makespan_ms: float
    page_count: int
    ticket_count: int
    pages_per_sec: float
    tickets_per_sec: float
    page_latency: dict
    ticket_latency: dict
    vram_card_peak_mb: float | None
    vram_card_baseline_mb: float | None
    vram_process_peak_mb: float | None
    vram_process_sum_mb: float | None
    vram_note: str
    errors: int
    nproc: int | None
    cpu_threads: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def summarize_level(
    *,
    device: str,
    engine: str,
    concurrency: int,
    makespan_ms: float,
    pages: list[float],
    tickets: list[float],
    page_count: int,
    ticket_count: int,
    vram_card_peak_mb: float | None = None,
    vram_card_baseline_mb: float | None = None,
    vram_process_peak_mb: float | None = None,
    vram_process_sum_mb: float | None = None,
    vram_note: str = "",
    errors: int = 0,
    nproc: int | None = None,
    cpu_threads: int | None = None,
) -> LevelSummary:
    """把一次并发档的原始量合成一行。

    `makespan_ms` 为 0（全部 worker 没跑起来）时报 None 吞吐——**不拿 0 顶替**，
    宁可写「样本不足」。
    """

    seconds = makespan_ms / 1000.0
    pages_per_sec = (page_count / seconds) if seconds > 0 else None
    tickets_per_sec = (ticket_count / seconds) if seconds > 0 else None
    return LevelSummary(
        device=device,
        engine=engine,
        concurrency=concurrency,
        makespan_ms=round(float(makespan_ms), 1),
        page_count=page_count,
        ticket_count=ticket_count,
        pages_per_sec=round(pages_per_sec, 4) if pages_per_sec is not None else None,
        tickets_per_sec=round(tickets_per_sec, 6) if tickets_per_sec is not None else None,
        page_latency=metrics.latency_percentiles(pages),
        ticket_latency=metrics.latency_percentiles(tickets),
        vram_card_peak_mb=vram_card_peak_mb,
        vram_card_baseline_mb=vram_card_baseline_mb,
        vram_process_peak_mb=vram_process_peak_mb,
        vram_process_sum_mb=vram_process_sum_mb,
        vram_note=vram_note,
        errors=errors,
        nproc=nproc,
        cpu_threads=cpu_threads,
    )


# ---------------------------------------------------------------------------
# 引擎构造（只接本地；拒绝云引擎名）


def build_engine(
    name: str,
    *,
    device: str,
    rotate_mode: str,
    force_deg: int = 0,
    ori_invert: bool = False,
    cpu_threads: int | None = None,
):
    """按 key 建引擎并（可选）包方向层。**云引擎一律拒绝**（这条链路不出网）。"""

    if not name.startswith("local:"):
        raise ValueError(
            f"容量压测只接本地引擎（local:*），拒绝 {name!r}——真机样本不得外呼（#108）"
        )
    options = local.LocalBuildOptions(
        device=device, ori_invert=ori_invert, cpu_threads=cpu_threads
    )
    engine = local.build_local_engines([name], options)[0]
    if isinstance(engine, local.DocOriEngine):
        raise ValueError("local:doc-ori 是方向分类，不是 OCR 引擎；用 --rotate-mode auto 挂它")
    if rotate_mode == "off":
        return engine
    ori = local.DocOriEngine(device=device, invert=ori_invert, cpu_threads=cpu_threads)
    return local.RotatingEngine(engine, mode=rotate_mode, force_deg=force_deg, ori=ori)


# ---------------------------------------------------------------------------
# 备图与清单


def prepare_batch(
    *,
    run_dir: Path,
    scope: str,
    repeat: int,
    engine: str,
    device: str,
    rotate_mode: str,
    force_deg: int,
    warmup: int,
) -> Manifest:
    """取图落盘（父进程一次渲染，N 个 worker 读同一批文件）+ 写 manifest.json。"""

    samples = sample_mod.load_samples(scope)
    tickets = expand_batch(group_tickets(samples), repeat)
    # 页图按原始页 id 存一份，票里存相对路径——repeat 只复制清单项，不复制文件。
    pages_dir = run_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_by_key: dict[str, str] = {}
    for sample in samples:
        key = sample.spec.key
        if key in page_by_key:
            continue
        rel = f"pages/{key}.jpg"
        (run_dir / rel).write_bytes(sample.image)
        page_by_key[key] = rel
    for ticket in tickets:
        for page in ticket.pages:
            page.path = page_by_key[page.id]
    warmup_pages = [page_by_key[sample.spec.key] for sample in samples[: max(warmup, 0)]]
    manifest = Manifest(
        engine=engine,
        device=device,
        rotate_mode=rotate_mode,
        force_deg=force_deg,
        tickets=tickets,
        warmup_pages=warmup_pages,
        page_count=sum(len(ticket.pages) for ticket in tickets),
        ticket_count=len(tickets),
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


# ---------------------------------------------------------------------------
# worker：一个进程，一个引擎，自己那份票


def _wait_for(path: Path, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return False


def _process_vram_mb() -> float | None:
    """本进程 Paddle 的显存峰值；CPU 跑 / 没卡时返回 None。"""

    paddle = sys.modules.get("paddle")
    if paddle is None:
        return None
    try:
        if not paddle.device.is_compiled_with_cuda() or paddle.device.cuda.device_count() < 1:
            return None
        return round(float(paddle.device.cuda.max_memory_allocated()) / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 —— 读不到就写读不到，不拿社区数字顶替
        return None


def run_worker(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    manifest = Manifest.from_dict(json.loads((run_dir / "manifest.json").read_text("utf-8")))
    shard = shard_tickets(manifest.tickets, args.worker_id, args.workers)
    worker_dir = run_dir / f"w{args.worker_id}"
    worker_dir.mkdir(parents=True, exist_ok=True)

    payload: dict = {
        "worker_id": args.worker_id,
        "workers": args.workers,
        "tickets_assigned": [ticket.id for ticket in shard],
        "pages": [],
        "tickets": [],
        "load_ms": None,
        "error": None,
        "vram_process_mb": None,
        "nproc": os.cpu_count(),
    }

    build_start = time.time()
    try:
        engine = build_engine(
            manifest.engine,
            device=manifest.device,
            rotate_mode=manifest.rotate_mode,
            force_deg=manifest.force_deg,
            ori_invert=args.ori_invert,
            cpu_threads=args.cpu_threads,
        )
        probe = getattr(engine, "available", None)
        ok, reason = probe() if probe is not None else (True, "可用")
        if not ok:
            raise RuntimeError(reason)
    except Exception as exc:  # noqa: BLE001 —— 起不来要如实落盘，父进程据此报错
        payload["error"] = f"{type(exc).__name__}: {exc}"
        (worker_dir / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (worker_dir / "ready").touch()
        return

    # 预热：模型加载 + 首批推理，不计入吞吐与时延
    try:
        for rel in manifest.warmup_pages:
            engine.recognize((run_dir / rel).read_bytes())
    except Exception as exc:  # noqa: BLE001 —— 预热失败视为引擎不可用
        payload["error"] = f"预热失败 {type(exc).__name__}: {exc}"
    payload["load_ms"] = int((time.time() - build_start) * 1000)

    (worker_dir / "ready").touch()
    if payload["error"]:
        (worker_dir / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return

    if not _wait_for(run_dir / "go", GO_TIMEOUT_SECONDS):
        payload["error"] = f"等 go 超时（{GO_TIMEOUT_SECONDS}s）"
        (worker_dir / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return

    t0 = time.time()
    for ticket in shard:
        ticket_start = time.time()
        for page in ticket.pages:
            try:
                result = engine.recognize((run_dir / page.path).read_bytes())
                payload["pages"].append(
                    {
                        "ticket": ticket.id,
                        "page": page.id,
                        "elapsed_ms": result.elapsed_ms,
                        "boxes": len(result.boxes),
                        "error": result.error,
                        "rotate_deg": result.rotate_deg,
                    }
                )
            except Exception as exc:  # noqa: BLE001 —— 一页失败不该毁掉整个档
                payload["pages"].append(
                    {
                        "ticket": ticket.id,
                        "page": page.id,
                        "elapsed_ms": None,
                        "boxes": 0,
                        "error": f"{type(exc).__name__}: {exc}",
                        "rotate_deg": None,
                    }
                )
        payload["tickets"].append(
            {
                "id": ticket.id,
                "pages": len(ticket.pages),
                "wall_ms": round((time.time() - ticket_start) * 1000, 1),
            }
        )
    payload["t0"] = t0
    payload["t1"] = time.time()
    payload["vram_process_mb"] = _process_vram_mb()
    (worker_dir / "result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 父进程：一个并发档


def run_level(
    *,
    run_dir: Path,
    manifest: Manifest,
    concurrency: int,
    python: str,
    ori_invert: bool,
    cpu_threads: int | None = None,
    log: bool = True,
) -> LevelSummary:
    level_dir = run_dir / f"c{concurrency}"
    level_dir.mkdir(parents=True, exist_ok=True)
    # 先把 worker 要读的东西备齐（清单 + 页图），再起进程——顺序反了 worker 会先撞空文件。
    # go 文件必须先删掉：重跑同一个 run_dir 时残留的 go 会让 worker 抢跑。
    (level_dir / "go").unlink(missing_ok=True)
    shutil.copyfile(run_dir / "manifest.json", level_dir / "manifest.json")
    pages_link = level_dir / "pages"
    if not pages_link.exists():
        try:
            pages_link.symlink_to((run_dir / "pages").resolve(), target_is_directory=True)
        except OSError:
            shutil.copytree(run_dir / "pages", pages_link)

    processes: list[subprocess.Popen] = []
    for worker_id in range(concurrency):
        worker_dir = level_dir / f"w{worker_id}"
        worker_dir.mkdir(parents=True, exist_ok=True)
        (worker_dir / "ready").unlink(missing_ok=True)
        (worker_dir / "result.json").unlink(missing_ok=True)
        command = [
            python,
            "-m",
            "benchmarks.ocr.capacity",
            "worker",
            "--run-dir",
            str(level_dir.resolve()),
            "--worker-id",
            str(worker_id),
            "--workers",
            str(concurrency),
        ]
        if ori_invert:
            command.append("--ori-invert")
        if cpu_threads:
            command += ["--cpu-threads", str(cpu_threads)]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path.cwd()) + os.pathsep + env.get("PYTHONPATH", "")
        processes.append(
            subprocess.Popen(
                command,
                cwd=str(Path.cwd()),
                env=env,
                stdout=subprocess.DEVNULL if not log else None,
                stderr=subprocess.DEVNULL if not log else None,
            )
        )

    ready_files = [level_dir / f"w{i}" / "ready" for i in range(concurrency)]
    ready_deadline = time.time() + READY_TIMEOUT_SECONDS
    while time.time() < ready_deadline:
        if all(path.exists() for path in ready_files):
            break
        if any(process.poll() is not None for process in processes):
            # 有 worker 没 ready 就退了：交给下面的收尾统一报错
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    # CPU 档不读显存：卡上的占用与本档无关，读出来只会是别人进程的数（#98 实测撞上过
    # ——没设 CUDA_VISIBLE_DEVICES 时 nvidia-smi 退路会报同一台机上另一张被占的卡）。
    on_gpu = manifest.device == "gpu"
    sampler = _CardSampler() if on_gpu else None
    baseline_mb = local.read_nvidia_smi_used_mb() if on_gpu else None
    if sampler is not None:
        sampler.start()
    go_time = time.time()
    (level_dir / "go").touch()

    for process in processes:
        process.wait()
    if sampler is not None:
        card_peak_mb, card_note = sampler.stop()
    else:
        card_peak_mb, card_note = None, "CPU 档不读显存（无关）"

    workers: list[dict] = []
    for worker_id in range(concurrency):
        result_path = level_dir / f"w{worker_id}" / "result.json"
        if result_path.exists():
            workers.append(json.loads(result_path.read_text("utf-8")))
    dead = [process.returncode for process in processes if process.returncode not in (0, None)]
    if len(workers) < concurrency or dead:
        print(
            f"  !! 并发 {concurrency}：{concurrency - len(workers)} 个 worker 没落结果，"
            f"非零退出码 {dead}——吞吐可能被算乐观，看 errors 列",
            flush=True,
        )

    ends = [worker["t1"] for worker in workers if worker.get("t1")]
    makespan_ms = (max(ends) - go_time) * 1000 if ends else 0.0
    page_latencies = [
        float(page["elapsed_ms"])
        for worker in workers
        for page in worker["pages"]
        if page["elapsed_ms"] is not None
    ]
    page_count = sum(len(worker["pages"]) for worker in workers)
    ticket_latencies = [
        float(ticket["wall_ms"]) for worker in workers for ticket in worker["tickets"]
    ]
    ticket_count = len(ticket_latencies)
    errors = sum(
        1 for worker in workers for page in worker["pages"] if page["error"]
    ) + sum(1 for worker in workers if worker.get("error"))
    process_peaks = [
        worker["vram_process_mb"] for worker in workers if worker.get("vram_process_mb")
    ]
    nproc = next((worker.get("nproc") for worker in workers if worker.get("nproc")), None)

    return summarize_level(
        device=manifest.device,
        engine=manifest.engine,
        concurrency=concurrency,
        makespan_ms=makespan_ms,
        pages=page_latencies,
        tickets=ticket_latencies,
        page_count=page_count,
        ticket_count=ticket_count,
        vram_card_peak_mb=card_peak_mb,
        vram_card_baseline_mb=baseline_mb,
        vram_process_peak_mb=max(process_peaks) if process_peaks else None,
        vram_process_sum_mb=round(sum(process_peaks), 1) if process_peaks else None,
        vram_note=card_note,
        errors=errors,
        nproc=nproc,
        cpu_threads=cpu_threads,
    )


class _CardSampler:
    """父进程侧轮询整卡显存：24 GB 的可用水位看这个（含同卡其它进程，note 里写明）。"""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._peak: float | None = None
        self._available = local.nvidia_smi_path() is not None

    def start(self) -> None:
        if not self._available:
            return
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def _poll(self) -> None:
        while not self._stop.is_set():
            value = local.read_nvidia_smi_used_mb()
            if value is not None:
                self._peak = value if self._peak is None else max(self._peak, value)
            self._stop.wait(POLL_INTERVAL_SECONDS)

    def stop(self) -> tuple[float | None, str]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if not self._available:
            return None, "本机无 nvidia-smi，读不到整卡显存"
        if self._peak is None:
            return None, "nvidia-smi 有但没采到值"
        gpu_id = local.visible_gpu_id()
        scope = f"仅卡 {gpu_id}" if gpu_id is not None else "整机最大值（未固定单卡）"
        return round(float(self._peak), 1), f"nvidia-smi 轮询，{scope}，含同卡其它进程"


# ---------------------------------------------------------------------------
# 报告


def _fmt(value, digits: int = 4, dash: str = "-") -> str:
    if value is None:
        return dash
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _fmt_ms(value) -> str:
    return "-" if value is None else f"{value:.0f}"


def format_table(levels: list[LevelSummary], title: str) -> str:
    lines = [f"### {title}", ""]
    header = (
        "| 并发 | 页/秒 | 票/秒 | 单页 P50/P95 (ms) | 单票 P50/P95 (ms) "
        "| 整卡峰值 (MB) | 进程峰值/合计 (MB) | 失败 |"
    )
    lines.append(header)
    lines.append("|---|---|---|---|---|---|---|---|")
    for level in levels:
        cells = [
            str(level.concurrency),
            _fmt(level.pages_per_sec),
            _fmt(level.tickets_per_sec, 6),
            f"{_fmt_ms(level.page_latency.get('p50'))}/{_fmt_ms(level.page_latency.get('p95'))}",
            f"{_fmt_ms(level.ticket_latency.get('p50'))}/{_fmt_ms(level.ticket_latency.get('p95'))}",
            _fmt_ms(level.vram_card_peak_mb),
            f"{_fmt_ms(level.vram_process_peak_mb)}/{_fmt_ms(level.vram_process_sum_mb)}",
            str(level.errors),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def cmd_report(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    level_files = sorted(run_dir.glob("c*/level.json"))
    if not level_files:
        print(f"没找到结果：{run_dir}（先跑 run 子命令）")
        sys.exit(2)
    levels = [
        LevelSummary(**json.loads(path.read_text("utf-8"))) for path in level_files
    ]
    by_device: dict[str, list[LevelSummary]] = {}
    for level in levels:
        by_device.setdefault(level.device, []).append(level)
    chunks: list[str] = []
    for device, rows in by_device.items():
        rows.sort(key=lambda item: item.concurrency)
        chunks.append(format_table(rows, f"设备 {device}（引擎 {rows[0].engine}）"))
    text = "\n".join(chunks)
    print(text)
    (run_dir / "report.md").write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI


def _add_engine_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--engine", default=DEFAULT_ENGINE, help="本地引擎名（local:*）")
    parser.add_argument("--device", default="gpu", choices=["gpu", "cpu"])
    parser.add_argument(
        "--rotate-mode",
        default="auto",
        choices=["off", "auto", "force"],
        help="生产配置是 auto（挂 doc-ori）；off/force 只作对照",
    )
    parser.add_argument("--force-deg", type=int, default=90)
    parser.add_argument("--ori-invert", action="store_true")
    parser.add_argument(
        "--cpu-threads",
        type=int,
        default=DEFAULT_CPU_THREADS,
        help=(
            f"CPU 上每个 worker 的 Paddle 线程数（默认 {DEFAULT_CPU_THREADS}，GPU 上忽略）；"
            "48 核机器上 8 线程/worker 在并发 6 之后开始超订，报告里按这个口径读"
        ),
    )


def cmd_run(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = prepare_batch(
        run_dir=run_dir,
        scope=args.scope,
        repeat=args.repeat,
        engine=args.engine,
        device=args.device,
        rotate_mode=args.rotate_mode,
        force_deg=args.force_deg,
        warmup=args.warmup,
    )
    print(
        f"批次：{manifest.ticket_count} 票 / {manifest.page_count} 页，"
        f"引擎 {manifest.engine}，设备 {manifest.device}，方向 {manifest.rotate_mode}"
    )
    levels: list[LevelSummary] = []
    for concurrency in parse_concurrency(args.concurrency):
        print(f"→ 并发 {concurrency} ……", flush=True)
        summary = run_level(
            run_dir=run_dir,
            manifest=manifest,
            concurrency=concurrency,
            python=args.python,
            ori_invert=args.ori_invert,
            cpu_threads=args.cpu_threads,
            log=args.verbose,
        )
        (run_dir / f"c{concurrency}" / "level.json").write_text(
            json.dumps(summary.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        levels.append(summary)
        print(
            f"  {summary.pages_per_sec} 页/秒，{summary.tickets_per_sec} 票/秒，"
            f"整卡 {summary.vram_card_peak_mb} MB，失败 {summary.errors}"
        )
    print()
    print(format_table(levels, f"设备 {manifest.device}（引擎 {manifest.engine}）"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benchmarks.ocr.capacity")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="跑一个设备的全部并发档（父进程编排）")
    _add_engine_options(run)
    run.add_argument("--scope", default="real", choices=list(sample_mod.SCOPES))
    run.add_argument("--repeat", type=int, default=4, help="整票重复份数，用来凑样本量")
    run.add_argument(
        "--concurrency",
        default=",".join(str(value) for value in DEFAULT_CONCURRENCY),
        help="逗号分隔的并发档，如 1,2,4,8",
    )
    run.add_argument("--warmup", type=int, default=2, help="每 worker 预热页数（不计入）")
    run.add_argument("--run-dir", default=str(OUT_DIR / "latest"))
    run.add_argument("--python", default=sys.executable, help="起 worker 用的解释器")
    run.add_argument("--verbose", action="store_true", help="透出 worker 的 stdout/stderr")
    run.set_defaults(func=cmd_run)

    worker = sub.add_parser("worker", help="内部用：一个并发 worker（父进程起它）")
    worker.add_argument("--run-dir", required=True)
    worker.add_argument("--worker-id", type=int, required=True)
    worker.add_argument("--workers", type=int, required=True)
    worker.add_argument("--ori-invert", action="store_true")
    worker.add_argument("--cpu-threads", type=int, default=DEFAULT_CPU_THREADS)
    worker.set_defaults(func=run_worker)

    report = sub.add_parser("report", help="把各档 level.json 汇成表")
    report.add_argument("--run-dir", default=str(OUT_DIR / "latest"))
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
