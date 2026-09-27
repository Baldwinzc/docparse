"""本地 OCR 引擎适配器：PaddleOCR / RapidOCR / 整页方向分类（#108，父 #97）。

与 engines.py 的云引擎共用 `OcrResult` 出口，run.py 不按来源分叉。

三条设计约束（对齐 #108）：

1. **依赖是可选重依赖**。paddleocr / rapidocr 一律懒 import，没装时不抛
   ImportError，而是把引擎标成 unavailable 并给出**具体安装命令**；本机不装
   `local-ocr` extra 也能跑 pytest / ruff。
2. **坐标参照系**。本地引擎的 bbox 以**喂进去的那张图**为参照系。方向处理统一
   由 `RotatingEngine` 在喂之前做掉（#108 的 `--rotate-mode`），所以
   `OcrResult.boxes` 的参照系是旋转后的图，旋转角度记在 `rotate_deg` 上。
3. **返回结构按官方文档写、未在本机验证**。本机（macOS/arm64）不装 Paddle，
   第一次在服务器上跑请先 `python -m benchmarks.ocr.run local-list --probe`；
   解析失败会抛出带**实际 keys** 的 EngineError，不静默出空结果。

显存峰值：PP-OCRv6 官方没有显存表（#96 已核实），只能自测，见 `VramSampler`。
"""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from benchmarks.ocr.engines import EngineError, OcrBox, OcrResult

# ---------------------------------------------------------------------------
# 依赖探测：声明式，不 import 重依赖


@dataclass(frozen=True)
class Dependency:
    module: str
    package: str
    hint: str


LOCAL_OCR_HINT = 'pip install -e ".[local-ocr]"'

DEPENDENCIES: dict[str, Dependency] = {
    "paddleocr": Dependency("paddleocr", "paddleocr", LOCAL_OCR_HINT),
    "rapidocr": Dependency("rapidocr", "rapidocr", LOCAL_OCR_HINT),
    "PIL": Dependency("PIL", "pillow", 'pip install -e ".[bench]"'),
}


def dependency_status(module: str) -> tuple[bool, str]:
    """(是否可用, 说明)。只探 spec，不 import——import paddle 要好几秒。"""

    dep = DEPENDENCIES.get(module, Dependency(module, module, f"pip install {module}"))
    try:
        found = importlib.util.find_spec(dep.module) is not None
    except (ImportError, ValueError):
        found = False
    return (True, "已安装") if found else (False, f"未安装 {dep.package}；{dep.hint}")


def missing_hint(modules: tuple[str, ...]) -> str:
    reasons = [dependency_status(m)[1] for m in modules if not dependency_status(m)[0]]
    return "；".join(reasons)


# ---------------------------------------------------------------------------
# PaddleOCR 档位表（数据，不是代码；对齐 docs/local-models-survey.md §2.1）


@dataclass(frozen=True)
class PaddleTier:
    key: str
    label: str
    det: str
    rec: str


PADDLE_TIERS: list[PaddleTier] = [
    PaddleTier("v6-tiny", "PP-OCRv6 tiny（最省档对照）", "PP-OCRv6_tiny_det", "PP-OCRv6_tiny_rec"),
    PaddleTier(
        "v6-small", "PP-OCRv6 small（官方默认档）", "PP-OCRv6_small_det", "PP-OCRv6_small_rec"
    ),
    PaddleTier(
        "v6-medium", "PP-OCRv6 medium（精度上限对照）", "PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"
    ),
    PaddleTier(
        "v5-mobile", "PP-OCRv5 mobile（旧基线）", "PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec"
    ),
    PaddleTier(
        "v5-server", "PP-OCRv5 server（旧基线精度档）", "PP-OCRv5_server_det", "PP-OCRv5_server_rec"
    ),
]


@dataclass(frozen=True)
class RapidTier:
    key: str
    label: str
    params: dict[str, str]


RAPID_TIERS: list[RapidTier] = [
    RapidTier(
        "v6-tiny",
        "RapidOCR v6 tiny（ONNX）",
        {"Det.model_type": "tiny", "Rec.model_type": "tiny"},
    ),
    RapidTier(
        "v6-small",
        "RapidOCR v6 small（ONNX）",
        {"Det.model_type": "small", "Rec.model_type": "small"},
    ),
    RapidTier(
        "v6-medium",
        "RapidOCR v6 medium（ONNX）",
        {"Det.model_type": "medium", "Rec.model_type": "medium"},
    ),
]

# doc_ori 标签 → 需要施加的「逆时针」角度。
# PaddleOCR 官方文档给的标签就是 0/90/180/270 四类，本表按「标签即回转度数」写。
# 方向搞反（90 转成 270）是 #97 归因方法里列明的失败来源之一，所以给 --ori-invert
# 开关，让 #110 的 C 组能在不改代码的前提下试两个方向——**哪个对由实测定，不靠猜**。
DOC_ORI_LABEL_TO_CCW: dict[int, int] = {0: 0, 90: 90, 180: 180, 270: 270}

# 官方 `class_ids` 是**类别下标**，不是角度；只给下标时按官方顺序映回角度。
DOC_ORI_CLASS_ORDER: tuple[int, ...] = (0, 90, 180, 270)


# ---------------------------------------------------------------------------
# 纯函数：返回值解析（单测用固定 payload 覆盖，不需要装 Paddle）


def _poly_to_bbox(poly: Any) -> tuple[float, float, float, float]:
    points: list[float] = []
    if hasattr(poly, "tolist"):
        poly = poly.tolist()
    for point in poly or []:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            points.extend([float(point[0]), float(point[1])])
        elif isinstance(point, dict):
            points.extend([float(point.get("x", 0)), float(point.get("y", 0))])
    if len(points) < 8:
        return 0.0, 0.0, 0.0, 0.0
    xs, ys = points[0::2], points[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def _first_key(payload: dict, *names: str) -> Any:
    for name in names:
        value = payload.get(name)
        if value is not None:
            return value
    return None


def parse_paddle_result(payload: Any) -> list[OcrBox]:
    """PaddleOCR 3.x `predict` 的返回 → OcrBox。

    3.x 一个 image 返回一个 dict-like（OCRResult），键名在不同小版本里动过，
    所以这里按候选键名兜底；全都没有就把实际 keys 抛出来，别静默出空结果。
    """

    if isinstance(payload, dict):
        pages = [payload]
    elif isinstance(payload, (list, tuple)):
        pages = []
        for entry in payload:
            if isinstance(entry, dict):
                pages.append(entry)
            elif hasattr(entry, "json"):
                data = entry.json
                pages.append(data.get("res", data) if isinstance(data, dict) else data)
    else:
        raise EngineError(f"PaddleOCR 返回了无法识别的类型：{type(payload).__name__}")

    boxes: list[OcrBox] = []
    for page in pages:
        if not isinstance(page, dict):
            raise EngineError(f"PaddleOCR 页结果不是 dict：{type(page).__name__}")
        texts = _first_key(page, "rec_texts", "texts")
        scores = _first_key(page, "rec_scores", "scores")
        polys = _first_key(page, "rec_polys", "dt_polys", "rec_boxes", "boxes")
        if texts is None or polys is None:
            raise EngineError(
                "未能从 PaddleOCR 结果中解析出文本行；"
                f"实际 keys={sorted(page.keys())}。"
                "可能是 PaddleOCR 小版本改了返回结构，核对 parse_paddle_result。"
            )
        if hasattr(texts, "tolist"):
            texts = texts.tolist()
        if scores is None:
            scores = [None] * len(texts)
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        if hasattr(polys, "tolist"):
            polys = polys.tolist()
        for text, score, poly in zip(texts, scores, polys, strict=False):
            x0, y0, x1, y1 = _poly_to_bbox(poly)
            boxes.append(
                OcrBox(
                    text=str(text),
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    confidence=float(score) if score is not None else None,
                )
            )
    return boxes


def parse_rapidocr_result(payload: Any) -> list[OcrBox]:
    """RapidOCR 3.x 的 RapidOCROutput（属性式）→ OcrBox。"""

    boxes_attr = getattr(payload, "boxes", None)
    txts = getattr(payload, "txts", None)
    scores = getattr(payload, "scores", None)
    if boxes_attr is None or txts is None:
        raise EngineError(
            "未能从 RapidOCR 结果中解析出文本行；"
            f"实际属性={sorted(a for a in dir(payload) if not a.startswith('_'))[:30]}。"
            "可能是 rapidocr 小版本改了返回结构，核对 parse_rapidocr_result。"
        )
    if hasattr(boxes_attr, "tolist"):
        boxes_attr = boxes_attr.tolist()
    if hasattr(txts, "tolist"):
        txts = txts.tolist()
    if scores is None:
        scores = [None] * len(txts)
    if hasattr(scores, "tolist"):
        scores = scores.tolist()
    boxes: list[OcrBox] = []
    for text, score, poly in zip(txts, scores, boxes_attr, strict=False):
        x0, y0, x1, y1 = _poly_to_bbox(poly)
        boxes.append(
            OcrBox(
                text=str(text),
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                confidence=float(score) if score is not None else None,
            )
        )
    return boxes


def parse_doc_ori_result(payload: Any) -> tuple[int, float | None]:
    """整页方向分类的返回 → (逆时针角度, 置信度)。

    官方四类 0/90/180/270。`label_names` 可能是 "90" 或 "rot90"，统一取数字；
    只给 `class_ids`（类别下标）时按官方顺序映回角度，不把下标当角度用。
    """

    label = None
    class_id = None
    score = None
    if isinstance(payload, dict):
        labels = _first_key(payload, "label_names", "labels")
        scores = _first_key(payload, "scores")
        ids = _first_key(payload, "class_ids")
        if labels is not None and len(labels):
            label = labels[0]
        elif ids is not None and len(ids):
            class_id = int(ids[0])
        if scores is not None and len(scores):
            score = float(scores[0])
    else:
        labels = getattr(payload, "label_names", None)
        if labels is None:
            labels = getattr(payload, "labels", None)
        scores = getattr(payload, "scores", None)
        ids = getattr(payload, "class_ids", None)
        if labels is not None and len(labels):
            label = labels[0]
        elif ids is not None and len(ids):
            class_id = int(ids[0])
        if scores is not None and len(scores):
            score = float(scores[0])

    if label is not None:
        digits = "".join(ch for ch in str(label) if ch.isdigit())
        if not digits:
            raise EngineError(f"方向分类标签里没有角度数字：{label!r}")
        return int(digits) % 360, score
    if class_id is not None:
        if not 0 <= class_id < len(DOC_ORI_CLASS_ORDER):
            raise EngineError(f"方向分类类别下标越界：{class_id}")
        return DOC_ORI_CLASS_ORDER[class_id], score
    raise EngineError(f"未能从方向分类结果中解析出标签：{payload!r}")


# ---------------------------------------------------------------------------
# 图片旋转（只有它需要 PIL）


def rotate_image_ccw(image: bytes, deg: int) -> bytes:
    """把图按**逆时针** deg 度转正，白底补边，重编码 JPEG。

    方向约定与 fixtures.py 的 rot90/rot180/rot270 一致（同一个 PIL.rotate）。
    """

    if deg % 360 == 0:
        return image
    from PIL import Image

    with Image.open(io.BytesIO(image)) as handle:
        handle.load()
        rotated = handle.convert("RGB").rotate(
            deg % 360, expand=True, resample=Image.BILINEAR, fillcolor="white"
        )
        buffer = io.BytesIO()
        rotated.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# 引擎基类


class LocalEngine:
    """本地引擎的公共外壳：可用性探测 + 名称。"""

    name = "local:base"
    label = "本地引擎基类"
    is_cloud = False
    requires: tuple[str, ...] = ()

    def available(self) -> tuple[bool, str]:
        for module in self.requires:
            ok, reason = dependency_status(module)
            if not ok:
                return False, reason
        return True, "可用"

    def recognize(self, image: bytes) -> OcrResult:  # pragma: no cover - 抽象
        raise NotImplementedError


def _to_temp_path(image: bytes) -> str:
    """落临时文件再喂引擎：绕开 ndarray 的 BGR/RGB 通道歧义，代价是这点磁盘 I/O。"""

    handle = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    try:
        handle.write(image)
    finally:
        handle.close()
    return handle.name


def _run_with_temp_file(image: bytes, call: Any) -> Any:
    """把图写成临时文件交给 `call(path)`，无论成败都删掉。"""

    path = _to_temp_path(image)
    try:
        return call(path)
    finally:
        os.unlink(path)


def _paddle_predict(engine: Any, path: str) -> Any:
    try:
        return engine.predict(input=path)
    except TypeError:  # 小版本签名差异：老一点的接位置参数
        return engine.predict(path)


class PaddleOcrEngine(LocalEngine):
    """PaddleOCR 3.x，PP-OCRv6 / PP-OCRv5 各档。"""

    requires = ("paddleocr",)

    def __init__(self, tier: PaddleTier, device: str = "gpu") -> None:
        self.tier = tier
        self.device = device
        self.name = f"local:paddle-{tier.key}"
        self.label = f"PaddleOCR {tier.label}"
        self._engine: Any = None

    def _build(self) -> Any:
        if self._engine is None:
            from paddleocr import (  # noqa: PLC0415 —— 懒 import，本机不装也能 import 本模块
                PaddleOCR,
            )

            self._engine = PaddleOCR(
                text_detection_model_name=self.tier.det,
                text_recognition_model_name=self.tier.rec,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device=self.device,
            )
        return self._engine

    def recognize(self, image: bytes) -> OcrResult:
        engine = self._build()
        start = time.monotonic()
        payload = _run_with_temp_file(image, lambda path: _paddle_predict(engine, path))
        elapsed = int((time.monotonic() - start) * 1000)
        return OcrResult(engine=self.name, boxes=parse_paddle_result(payload), elapsed_ms=elapsed)


class RapidOcrEngine(LocalEngine):
    """RapidOCR：同一批 Paddle 权重转 ONNX，不装 PaddlePaddle。

    进首轮的理由是「装不上 Paddle 系」时的等价退路，**必须与 PaddleOCR 原版
    做输出一致性实测对照**（#96 §1.2），不能靠推理宣称等价。
    """

    requires = ("rapidocr",)

    def __init__(self, tier: RapidTier) -> None:
        self.tier = tier
        self.name = f"local:rapidocr-{tier.key}"
        self.label = tier.label
        self._engine: Any = None

    def _build(self) -> Any:
        if self._engine is None:
            from rapidocr import RapidOCR  # noqa: PLC0415

            self._engine = RapidOCR(params=dict(self.tier.params))
        return self._engine

    def recognize(self, image: bytes) -> OcrResult:
        engine = self._build()
        start = time.monotonic()
        payload = _run_with_temp_file(image, engine)
        elapsed = int((time.monotonic() - start) * 1000)
        return OcrResult(engine=self.name, boxes=parse_rapidocr_result(payload), elapsed_ms=elapsed)


class DocOriEngine(LocalEngine):
    """整页方向分类 PP-LCNet_x1_0_doc_ori：0/90/180/270 四类（#96 §3.2）。

    **不单独出 CER**——它不是 OCR 引擎，只出判定角度，供 `--rotate-mode auto`
    和 #110 的归因实验用。
    """

    requires = ("paddleocr",)
    name = "local:doc-ori"
    label = "PP-LCNet_x1_0_doc_ori 整页方向分类"
    model_name = "PP-LCNet_x1_0_doc_ori"

    def __init__(self, device: str = "gpu", invert: bool = False) -> None:
        self.device = device
        self.invert = invert
        self._engine: Any = None

    def _build(self) -> Any:
        if self._engine is None:
            from paddleocr import DocImgOrientationClassification  # noqa: PLC0415

            self._engine = DocImgOrientationClassification(
                model_name=self.model_name, device=self.device
            )
        return self._engine

    def detect(self, image: bytes) -> tuple[int, float | None]:
        engine = self._build()
        payload = _run_with_temp_file(image, lambda path: _paddle_predict(engine, path))
        if isinstance(payload, (list, tuple)) and payload:
            payload = payload[0]
        if hasattr(payload, "json") and isinstance(payload.json, dict):
            payload = payload.json.get("res", payload.json)
        label, score = parse_doc_ori_result(payload)
        return self.apply_invert(label), score

    def apply_invert(self, deg: int) -> int:
        """方向搞反（90 ↔ 270）是 #97 列明的失败来源之一，用开关试，不靠猜。"""

        if not self.invert:
            return deg
        return {0: 0, 90: 270, 180: 180, 270: 90}.get(deg % 360, deg % 360)

    def recognize(self, image: bytes) -> OcrResult:
        raise EngineError("local:doc-ori 是方向分类，不是 OCR 引擎；用 --rotate-mode auto 挂它")


class RotatingEngine(LocalEngine):
    """给任意引擎加一层方向处理——#97 归因方法的 A/B/C 三组靠它。

    | 模式 | 语义 | 对应 #97 的组 |
    |---|---|---|
    | `off` | 不判方向，喂什么读什么（配已人工转正的样本即 A 组） | A |
    | `auto` | 走方向分类自己判（端到端真实表现） | B |
    | `force` | 跳过判定，用人为指定的角度（只隔离「方向模型判错」） | C |
    """

    def __init__(
        self,
        inner: Any,
        *,
        mode: str,
        force_deg: int = 0,
        ori: DocOriEngine | None = None,
    ) -> None:
        if mode not in {"auto", "force"}:
            raise ValueError(f"RotatingEngine 只接 auto / force；off 不该包进来（收到 {mode!r}）")
        self.inner = inner
        self.mode = mode
        self.force_deg = force_deg % 360
        self.ori = ori
        suffix = "auto" if mode == "auto" else f"force{self.force_deg}"
        self.name = f"{inner.name}@{suffix}"
        self.label = f"{inner.label} · 方向 {suffix}"
        self.requires = getattr(inner, "requires", ())
        # 云引擎包了方向层还是云引擎——隐私闸必须照样拦得住，否则 --rotate-mode
        # 就成了绕过真机不外呼的口子。
        self.is_cloud = getattr(inner, "is_cloud", False)

    def available(self) -> tuple[bool, str]:
        probe = getattr(self.inner, "available", None)
        ok, reason = probe() if probe is not None else (True, "可用")
        if not ok:
            return ok, reason
        if self.mode == "auto" and self.ori is not None:
            return self.ori.available()
        return True, "可用"

    def recognize(self, image: bytes) -> OcrResult:
        deg = self.force_deg
        source = "force"
        warnings: list[str] = []
        if self.mode == "auto":
            source = "auto"
            if self.ori is None:
                deg = 0
                warnings.append("--rotate-mode auto 但没有可用的方向分类模型，已按 0° 处理")
            else:
                deg, score = self.ori.detect(image)
                warnings.append(f"方向分类判定 {deg}°（置信度 {score}）")
        rotated = rotate_image_ccw(image, deg)
        result = self.inner.recognize(rotated)
        result.engine = self.name
        result.rotate_deg = deg
        result.rotate_source = source
        result.warnings = warnings + list(getattr(result, "warnings", []))
        return result


# ---------------------------------------------------------------------------
# 显存峰值采样（#97 要求「显存 / 内存峰值」；PP-OCRv6 官方没有显存表，只能自测）


@dataclass
class VramReading:
    peak_mb: float | None = None
    source: str = "unavailable"
    note: str = ""


class VramSampler:
    """跑一次引擎前后的显存峰值。

    优先 Paddle 自己的 CUDA 计数器（只算本进程），退到 `nvidia-smi` 轮询
    （**算整卡，含别的进程**，note 里会写明）。两者都不可用时记 None——
    宁可不写，也不拿社区数字顶替。
    """

    POLL_INTERVAL = 0.2

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._peak: float | None = None
        self._paddle_ok = False

    @staticmethod
    def _paddle_cuda() -> Any | None:
        paddle = sys.modules.get("paddle")
        if paddle is None:
            return None
        try:
            if not paddle.device.is_compiled_with_cuda() or paddle.device.cuda.device_count() < 1:
                return None
        except Exception:  # noqa: BLE001 —— 探测失败就当没有，不影响主流程
            return None
        return paddle

    def start(self) -> None:
        self._peak = None
        self._stop.clear()
        paddle = self._paddle_cuda()
        if paddle is not None:
            self._paddle_ok = True
            try:
                paddle.device.cuda.reset_peak_memory_allocated()
            except Exception:  # noqa: BLE001
                self._paddle_ok = False
        if nvidia_smi_path() is not None:
            self._thread = threading.Thread(target=self._poll, daemon=True)
            self._thread.start()

    def _poll(self) -> None:
        while not self._stop.is_set():
            value = read_nvidia_smi_used_mb()
            if value is not None:
                self._peak = value if self._peak is None else max(self._peak, value)
            self._stop.wait(self.POLL_INTERVAL)

    def stop(self) -> VramReading:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        paddle = self._paddle_cuda()
        if self._paddle_ok and paddle is not None:
            try:
                peak = paddle.device.cuda.max_memory_allocated() / (1024 * 1024)
                return VramReading(
                    peak_mb=round(float(peak), 1),
                    source="paddle",
                    note="paddle.device.cuda.max_memory_allocated()，只算本进程",
                )
            except Exception:  # noqa: BLE001
                pass
        if self._peak is not None:
            return VramReading(
                peak_mb=round(float(self._peak), 1),
                source="nvidia-smi",
                note="nvidia-smi 轮询，整卡口径（含同卡其他进程）",
            )
        return VramReading(
            peak_mb=None,
            source="unavailable",
            note="本机既无 Paddle CUDA 也无 nvidia-smi，读不到显存峰值",
        )


def nvidia_smi_path() -> str | None:
    for candidate in ("/usr/bin/nvidia-smi", "/usr/local/bin/nvidia-smi"):
        if os.path.exists(candidate):
            return candidate
    from shutil import which

    return which("nvidia-smi")


def read_nvidia_smi_used_mb() -> float | None:
    path = nvidia_smi_path()
    if path is None:
        return None
    try:
        out = subprocess.run(
            [path, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    values = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    if not values:
        return None
    try:
        return max(float(value) for value in values)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 注册表


@dataclass
class LocalBuildOptions:
    device: str = "gpu"
    ori_invert: bool = False


@dataclass
class LocalRegistryEntry:
    key: str
    label: str
    requires: tuple[str, ...]
    factory: Any
    kind: str = "ocr"  # "ocr" | "orientation"


def local_registry() -> list[LocalRegistryEntry]:
    entries = [
        LocalRegistryEntry(
            key=f"local:paddle-{tier.key}",
            label=f"PaddleOCR {tier.label}",
            requires=PaddleOcrEngine.requires,
            factory=lambda opts, tier=tier: PaddleOcrEngine(tier, device=opts.device),
        )
        for tier in PADDLE_TIERS
    ]
    entries += [
        LocalRegistryEntry(
            key=f"local:rapidocr-{tier.key}",
            label=tier.label,
            requires=RapidOcrEngine.requires,
            factory=lambda opts, tier=tier: RapidOcrEngine(tier),
        )
        for tier in RAPID_TIERS
    ]
    entries.append(
        LocalRegistryEntry(
            key=DocOriEngine.name,
            label=DocOriEngine.label,
            requires=DocOriEngine.requires,
            factory=lambda opts: DocOriEngine(device=opts.device, invert=opts.ori_invert),
            kind="orientation",
        )
    )
    return entries


def build_local_engines(
    names: list[str] | None = None, options: LocalBuildOptions | None = None
) -> list[Any]:
    """按 key 建本地引擎；`names` 为空则全建。找不到的 key 直接报错，不静默跳过。"""

    opts = options or LocalBuildOptions()
    registry = {entry.key: entry for entry in local_registry()}
    if names is None:
        selected = [entry for entry in local_registry() if entry.kind == "ocr"]
    else:
        missing = [name for name in names if name not in registry]
        if missing:
            raise KeyError(f"未知本地引擎：{'、'.join(missing)}")
        selected = [registry[name] for name in names]
    return [entry.factory(opts) for entry in selected]


@dataclass
class LocalEngineStatus:
    key: str
    label: str
    kind: str
    available: bool
    reason: str
    requires: tuple[str, ...] = field(default_factory=tuple)


def local_engine_status(options: LocalBuildOptions | None = None) -> list[LocalEngineStatus]:
    opts = options or LocalBuildOptions()
    rows: list[LocalEngineStatus] = []
    for entry in local_registry():
        engine = entry.factory(opts)
        ok, reason = engine.available()
        rows.append(
            LocalEngineStatus(
                key=entry.key,
                label=entry.label,
                kind=entry.kind,
                available=ok,
                reason=reason,
                requires=entry.requires,
            )
        )
    return rows


def probe_engine(engine: Any) -> tuple[bool, str]:
    """真构造一次并在白底小图上跑一遍——第一次上服务器时先验 API 用。"""

    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        return False, missing_hint(("PIL",))
    buffer = io.BytesIO()
    Image.new("RGB", (320, 160), "white").save(buffer, format="JPEG", quality=90)
    try:
        result = engine.recognize(buffer.getvalue())
    except Exception as exc:  # noqa: BLE001 —— probe 的用处就是把异常原样报出来
        return False, f"{type(exc).__name__}: {exc}"
    return True, f"跑通，{result.elapsed_ms}ms，识别 {len(result.boxes)} 行（白底图预期 0 行）"


def probe_orientation(engine: Any) -> tuple[bool, str]:
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        return False, missing_hint(("PIL",))
    buffer = io.BytesIO()
    Image.new("RGB", (320, 160), "white").save(buffer, format="JPEG", quality=90)
    try:
        deg, score = engine.detect(buffer.getvalue())
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    return True, f"跑通，判定 {deg}°（置信度 {score}）"
