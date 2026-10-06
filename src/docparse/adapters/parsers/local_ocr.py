"""本地 OCR：PaddleOCR PP-OCRv6 small + doc-ori 方向分类（#110 选型，#99 接入）。

实现 `OcrClient` 协议（`read_image(bytes, filename) -> OcrOutcome`），下游
`pdf.py` / `image.py` / `ocr_layout.py`(#62) / 规则链**一行都不用动**——这是 #99
的全部意义：换引擎只在这一处。

坐标约定（与 TextIn 路径一致，`ocr.py` 的 docstring 是同一条约定）：
**先按方向分类的判定角度把整页转正，再喂识别**。所以

- `OcrLine` 的 bbox 以**正立图**为参照系；
- `OcrOutcome.width` / `height` 是**转正后**的宽高；
- 判定/施加的角度记进 `angle`，由 `pdf.py` / `image.py` 经 `angle_note` 留档进 warnings。

`angle` 的语义是「转正所需的**逆时针**角度」，与 `benchmarks/ocr/samples.py` 的
`rotation_truth`、`benchmarks/ocr/local_engines.rotate_image_ccw` 同一约定。

失败路径对齐 TextIn 无密钥的行为：引擎 / 权重不可用时**只出 warning、不崩**，
`lines` 为空、`width` / `height` 为 0，文档照常进下游（后续 needs_review），
**不编文字**。

依赖是可选重依赖（paddleocr / pillow，`pip install -e ".[local-ocr]"`）：一律懒
import，没装时不抛 ImportError，只把引擎标成不可用并给出安装命令——本机不装
`local-ocr` extra 也能跑 pytest / ruff。

> 与评测台 [benchmarks/ocr/local_engines.py](../../../../benchmarks/ocr/local_engines.py)
> 的关系：#108 的装置要跑多档位 / A-B-C 归因 / 显存采样，是**评估**用的；本文件是
> **生产**路径，只固定跑 #110 选定的 `PP-OCRv6 small` + `doc-ori`。两者共用同一套
> PaddleOCR 返回结构假设，解析逻辑各留一份（刻意不在 src 里 import benchmarks，
> 交付时不该把装置一起打包）。改动其中一处时请对照另一处，见本文件 §返回值解析 注释。
"""

from __future__ import annotations

import importlib.util
import io
import os
import tempfile
from typing import Any

from docparse.adapters.parsers.ocr import OcrLine, OcrOutcome
from docparse.config import Settings, get_settings

# #110 选型：PP-OCRv6 small（官方默认档）+ PP-LCNet_x1_0_doc_ori 整页方向分类。
DET_MODEL = "PP-OCRv6_small_det"
REC_MODEL = "PP-OCRv6_small_rec"
ORI_MODEL = "PP-LCNet_x1_0_doc_ori"

LOCAL_OCR_HINT = 'pip install -e ".[local-ocr]"'
JPEG_QUALITY = 90

# doc-ori 的类别下标 → 逆时针转正角度（官方顺序，见 #96 §3.2 / #108）。
DOC_ORI_CLASS_ORDER: tuple[int, ...] = (0, 90, 180, 270)


# ---------------------------------------------------------------------------
# 依赖探测：声明式，不 import 重依赖（import paddle 要好几秒）


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def dependency_status() -> tuple[bool, str]:
    """(本地引擎是否可用, 说明)。缺哪个依赖、装哪条命令都写在说明里。"""

    missing = []
    if not _installed("paddleocr"):
        missing.append("paddleocr")
    if not _installed("PIL"):
        missing.append("pillow")
    if missing:
        return False, f"未安装 {' / '.join(missing)}；{LOCAL_OCR_HINT}"
    return True, "可用"


# ---------------------------------------------------------------------------
# 纯函数：返回值解析（单测用固定 payload 覆盖，不需要装 Paddle）
#
# 与 benchmarks/ocr/local_engines.py 的 parse_* 是同一条假设：PaddleOCR 3.x 一个
# image 返回一个 dict-like，键名在小版本之间动过，按候选键名兜底；全都没有就抛错，
# 不静默出空结果。改这里时请对照那两处。


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


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        return value.tolist()
    return list(value)


def _page_dicts(payload: Any) -> list[dict]:
    """把 predict 的返回摊平成「每页一个 dict」；摊不动就抛错。"""

    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, (list, tuple)):
        pages: list[dict] = []
        for entry in payload:
            if isinstance(entry, dict):
                pages.append(entry)
            elif hasattr(entry, "json"):
                data = entry.json
                pages.append(data.get("res", data) if isinstance(data, dict) else data)
        return pages
    raise ValueError(f"PaddleOCR 返回了无法识别的类型：{type(payload).__name__}")


def parse_paddle_lines(payload: Any) -> list[OcrLine]:
    """PaddleOCR 3.x `predict` 的返回 → OcrLine（bbox 为喂进去那张图的参照系）。"""

    lines: list[OcrLine] = []
    for page in _page_dicts(payload):
        if not isinstance(page, dict):
            raise ValueError(f"PaddleOCR 页结果不是 dict：{type(page).__name__}")
        texts = _first_key(page, "rec_texts", "texts")
        scores = _first_key(page, "rec_scores", "scores")
        polys = _first_key(page, "rec_polys", "dt_polys", "rec_boxes", "boxes")
        if texts is None or polys is None:
            raise ValueError(
                "未能从 PaddleOCR 结果中解析出文本行；"
                f"实际 keys={sorted(page.keys())}。"
                "可能是 PaddleOCR 小版本改了返回结构，核对 parse_paddle_lines。"
            )
        texts = _as_list(texts)
        scores = _as_list(scores) or [None] * len(texts)
        polys = _as_list(polys)
        for text, score, poly in zip(texts, scores, polys, strict=False):
            snippet = str(text).strip()
            if not snippet:
                continue
            x0, y0, x1, y1 = _poly_to_bbox(poly)
            lines.append(
                OcrLine(
                    text=snippet,
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    score=float(score) if score is not None else None,
                )
            )
    return lines


def parse_orientation(payload: Any) -> tuple[int, float | None]:
    """doc-ori 的返回 → (逆时针转正角度, 置信度)。

    `label_names` 可能是 "90" 或 "rot90"，统一取数字；只给 `class_ids`（类别下标）
    时按官方顺序映回角度，不把下标当角度用。
    """

    label = class_id = score = None
    if isinstance(payload, dict):
        labels = _first_key(payload, "label_names", "labels")
        scores = _first_key(payload, "scores")
        ids = _first_key(payload, "class_ids")
    else:
        labels = getattr(payload, "label_names", None)
        if labels is None:
            labels = getattr(payload, "labels", None)
        scores = getattr(payload, "scores", None)
        ids = getattr(payload, "class_ids", None)
    labels = _as_list(labels)
    scores = _as_list(scores)
    ids = _as_list(ids)
    if labels:
        label = labels[0]
    elif ids:
        class_id = int(ids[0])
    if scores:
        score = float(scores[0])

    if label is not None:
        digits = "".join(ch for ch in str(label) if ch.isdigit())
        if not digits:
            raise ValueError(f"方向分类标签里没有角度数字：{label!r}")
        return int(digits) % 360, score
    if class_id is not None:
        if not 0 <= class_id < len(DOC_ORI_CLASS_ORDER):
            raise ValueError(f"方向分类类别下标越界：{class_id}")
        return DOC_ORI_CLASS_ORDER[class_id], score
    raise ValueError(f"未能从方向分类结果中解析出标签：{payload!r}")


# ---------------------------------------------------------------------------
# 图片转正 + 格式归一化（只有它需要 PIL）


def _suffix_for(image: bytes) -> str | None:
    """引擎能直接吃、后缀如实的两种：PNG / JPEG。其它格式返回 None。"""

    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if image[:3] == b"\xff\xd8\xff":
        return ".jpg"
    return None


def prepare_image(image: bytes, deg: int) -> tuple[bytes, int, int, str]:
    """按**逆时针** deg 度转正并归一化；返回 (bytes, 宽, 高, 临时文件后缀)。

    宽高是**转正后**的，正是 OcrOutcome.width / height 要报的那个数。`deg % 360 == 0`
    且原图已是 PNG / JPEG 时**原样返回**（不二次压缩）；tif / webp / bmp 在此并成 JPEG。
    后缀如实给——引擎的临时文件是 `.jpg` 还是 `.png` 以真实内容为准，不拿假后缀糊引擎。
    """

    from PIL import Image

    with Image.open(io.BytesIO(image)) as handle:
        handle.load()
        if deg % 360 == 0:
            suffix = _suffix_for(image)
            if suffix is not None:
                return image, handle.width, handle.height, suffix
            buffer = io.BytesIO()
            handle.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY)
            return buffer.getvalue(), handle.width, handle.height, ".jpg"
        rotated = handle.convert("RGB").rotate(
            deg % 360, expand=True, resample=Image.BILINEAR, fillcolor="white"
        )
        buffer = io.BytesIO()
        rotated.save(buffer, format="JPEG", quality=JPEG_QUALITY)
        return buffer.getvalue(), rotated.width, rotated.height, ".jpg"


# ---------------------------------------------------------------------------
# 引擎构造（懒 import + 懒构造，权重只在第一次识别时加载）


def resolve_device(device: str) -> str:
    """auto → 有 CUDA 用 gpu，否则 cpu；显式给的 cpu / gpu 原样返回。"""

    if device != "auto":
        return device
    try:
        import paddle  # noqa: PLC0415

        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() >= 1:
            return "gpu"
    except Exception:  # noqa: BLE001 —— 探测失败就当没 GPU，退回 CPU
        pass
    return "cpu"


def cpu_kwargs(device: str, cpu_threads: int | None = None) -> dict[str, Any]:
    """CPU 上跑 PaddleOCR 要加的公共参数（#98 实测，不是猜）。

    Paddle 3.3.1 上 CPU 的静态图预测器开 MKL-DNN 会抛
    `NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support ...`，
    实测只有 `enable_mkldnn=False` 能跑通（详见 #98 / capacity-benchmark §局限）。
    代价：CPU 数字是不开 MKL-DNN 的下限。GPU 路径不传这些。
    """

    if device != "cpu":
        return {}
    kwargs: dict[str, Any] = {"enable_mkldnn": False}
    if cpu_threads:
        kwargs["cpu_threads"] = cpu_threads
    return kwargs


def _predict(engine: Any, path: str) -> Any:
    try:
        return engine.predict(input=path)
    except TypeError:  # 小版本签名差异：老一点的接位置参数
        return engine.predict(path)


def _run_with_temp_file(image: bytes, suffix: str, call: Any) -> Any:
    """把图落临时文件再喂引擎：绕开 ndarray 的 BGR/RGB 通道歧义。

    后缀由调用方按真实内容给（见 `prepare_image`），别写死 `.jpg`——PNG 输入得给
    `.png`，否则等于拿一个后缀不实的文件糊引擎。
    """

    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        handle.write(image)
        handle.close()
        return call(handle.name)
    finally:
        try:
            os.unlink(handle.name)
        except OSError:  # pragma: no cover —— 临时文件已被引擎删掉之类
            pass


class LocalOcrClient:
    """本地 OCR client：方向分类转正 → PP-OCRv6 small 识别（#110 选型）。

    `engine` / `ori` 供单测注入替身（本机不装 Paddle）；生产路径两者都为 None，
    走懒构造的真实 PaddleOCR。
    """

    def __init__(
        self,
        *,
        device: str = "auto",
        cpu_threads: int | None = None,
        engine: Any = None,
        ori: Any = None,
    ) -> None:
        self.device = device
        self.cpu_threads = cpu_threads
        self._engine = engine
        self._ori = ori

    def available(self) -> tuple[bool, str]:
        """引擎是否可用。注入了 engine 就算可用，不看本机装没装重依赖。"""

        if self._engine is not None:
            return True, "可用（已注入）"
        return dependency_status()

    def read_image(self, data: bytes, *, filename: str) -> OcrOutcome:
        ok, reason = self.available()
        if not ok:
            return OcrOutcome(warnings=[f"本地 OCR 引擎不可用（{filename}）：{reason}"])

        warnings: list[str] = []
        try:
            engine = self._get_engine()
        except Exception as exc:  # noqa: BLE001 —— 权重缺失 / 下载失败都在此，降级不崩
            return OcrOutcome(warnings=[f"本地 OCR 引擎加载失败（{filename}）：{exc}"])

        angle = self._detect_angle(data, filename, warnings)
        try:
            upright, width, height, suffix = prepare_image(data, angle)
        except Exception as exc:  # noqa: BLE001
            return OcrOutcome(warnings=[f"本地 OCR 图片读取失败（{filename}）：{exc}"])
        try:
            payload = _run_with_temp_file(
                upright, suffix, lambda path: _predict(engine, path)
            )
            lines = parse_paddle_lines(payload)
        except Exception as exc:  # noqa: BLE001
            return OcrOutcome(warnings=[f"本地 OCR 识别失败（{filename}）：{exc}"])
        return OcrOutcome(
            lines=lines, angle=angle, width=width, height=height, warnings=warnings
        )

    def _detect_angle(self, data: bytes, filename: str, warnings: list[str]) -> int:
        """方向分类判定转正角；分类模型不可用或判失败一律按 0° 并留 warning。"""

        try:
            ori = self._get_ori()
        except Exception as exc:  # noqa: BLE001 —— 方向层是可选的，别拖垮识别
            warnings.append(f"方向分类模型加载失败（{filename}）：{exc}，整页按 0° 处理。")
            return 0
        if ori is None:
            warnings.append("方向分类模型不可用，整页按 0° 处理。")
            return 0
        try:
            probe, _width, _height, suffix = prepare_image(data, 0)
            payload = _run_with_temp_file(probe, suffix, lambda path: _predict(ori, path))
            if isinstance(payload, (list, tuple)) and payload:
                payload = payload[0]
            if hasattr(payload, "json") and isinstance(payload.json, dict):
                payload = payload.json.get("res", payload.json)
            angle, score = parse_orientation(payload)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"方向分类判定失败（{filename}）：{exc}，整页按 0° 处理。")
            return 0
        warnings.append(f"整页方向分类判定 {angle}°（置信度 {score}）。")
        return angle

    def _get_engine(self) -> Any:
        if self._engine is None:
            from paddleocr import PaddleOCR  # noqa: PLC0415 —— 懒 import

            device = resolve_device(self.device)
            self._engine = PaddleOCR(
                text_detection_model_name=DET_MODEL,
                text_recognition_model_name=REC_MODEL,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device=device,
                **cpu_kwargs(device, self.cpu_threads),
            )
        return self._engine

    def _get_ori(self) -> Any:
        if self._ori is None:
            from paddleocr import (  # noqa: PLC0415
                DocImgOrientationClassification,
            )

            device = resolve_device(self.device)
            self._ori = DocImgOrientationClassification(
                model_name=ORI_MODEL,
                device=device,
                **cpu_kwargs(device, self.cpu_threads),
            )
        return self._ori


_clients: dict[tuple[str, int | None], LocalOcrClient] = {}


def get_local_ocr_client(settings: Settings | None = None) -> LocalOcrClient:
    """按设备档位取共享 client——模型加载很贵，必须复用同一个实例。"""

    resolved = settings or get_settings()
    key = (resolved.local_ocr_device, resolved.local_ocr_cpu_threads)
    if key not in _clients:
        _clients[key] = LocalOcrClient(device=key[0], cpu_threads=key[1])
    return _clients[key]
