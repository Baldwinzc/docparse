"""评测指标：归一化、字符错误率（CER）、字段命中、商品行结构、时延分位。仅标准库。

为保证与 #60 云基线**同表可比**，`normalize` / `cer` / `field_hit_rate` 的算法保持
原样不动；#108 新增的部分一律另起函数，不改老口径。
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

_PUNCT_MAP = str.maketrans(
    {
        "。": ".",
        "，": ",",
        "、": ",",
        "：": ":",
        "；": ";",
        "！": "!",
        "？": "?",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
)
_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """NFKC 全角转半角 + 中文标点转英文 + 去全部空白 + 大写。"""

    unified = unicodedata.normalize("NFKC", text)
    translated = unified.translate(_PUNCT_MAP)
    compact = _WS_RE.sub("", translated)
    return compact.upper()


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def cer(gt: str, pred: str) -> float:
    """归一化后的字符错误率；gt 为空时返回 0.0。"""

    norm_gt = normalize(gt)
    norm_pred = normalize(pred)
    if not norm_gt:
        return 0.0
    return levenshtein(norm_gt, norm_pred) / len(norm_gt)


def field_hits(fields: dict[str, str], pred_text: str) -> list[tuple[str, str, bool]]:
    """字段值是否出现在识别全文里（两边都归一化）。"""

    norm_pred = normalize(pred_text)
    results: list[tuple[str, str, bool]] = []
    for label, value in fields.items():
        norm_value = normalize(value)
        hit = bool(norm_value) and norm_value in norm_pred
        results.append((label, value, hit))
    return results


def field_hit_rate(fields: dict[str, str], pred_text: str) -> float:
    results = field_hits(fields, pred_text)
    if not results:
        return 0.0
    return sum(1 for _, _, hit in results if hit) / len(results)


def field_cer(gt_fields: dict[str, str], pred_fields: dict[str, str]) -> list[tuple[str, float]]:
    """同名字段逐一算 CER；引擎没返回的字段记 1.0。"""

    rows: list[tuple[str, float]] = []
    for label, value in gt_fields.items():
        pred = pred_fields.get(label)
        rows.append((label, 1.0 if pred is None else cer(value, pred)))
    return rows


# ---------------------------------------------------------------------------
# 时延分位（#97：只报均值会被长尾掩盖）


def percentile(values: Sequence[float], p: float) -> float | None:
    """线性插值分位，p 取 0–100。

    空序列返回 None——样本数少的时候要**如实写「样本不足」**，不拿 0 顶替。
    """

    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * (p / 100.0)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[int(position)]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def latency_percentiles(values: Sequence[float]) -> dict[str, float | int | None]:
    """{"n": 样本量, "p50": ..., "p95": ...}；结果里必须带上 n，防止读者误以为是全量。"""

    return {
        "n": len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
    }


# ---------------------------------------------------------------------------
# 商品行结构正确率（#97：决定 #62 伪格子与规则链能不能复用）


class BoxLike(Protocol):
    """只要带 text 与 bbox 就行——不绑定 OcrBox，方便单测与将来的引擎各写各的。"""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class TextBox:
    text: str
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 1.0


def text_boxes_from_dicts(rows: Sequence[dict]) -> list[TextBox]:
    """`out/results/*.json` 里的 boxes 是 dict，指标函数吃的是带属性的对象——在这转。

    少字段就按默认值补，缺 text 的丢掉；**不因为一个畸形字块让整页指标算不出来**。
    """

    boxes: list[TextBox] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = row.get("text")
        if text is None:
            continue
        boxes.append(
            TextBox(
                text=str(text),
                x0=float(row.get("x0", 0.0)),
                y0=float(row.get("y0", 0.0)),
                x1=float(row.get("x1", 0.0)),
                y1=float(row.get("y1", 1.0)),
            )
        )
    return boxes


@dataclass
class GoodsRowStats:
    """商品行结构的两件事：**行数对不对**、**每行归属哪一件**。

    归属用「**行签名**」判：一行 = 它的锚（HS 码）+ 伴值（单价 / 原产国）。某条行带
    「承载」某行，当且仅当这条带里同时出现该行的锚与全部伴值。

    - `pred_rows` 是识别出的行带数（给了 region 就只数货表区域内的）；
    - `anchor_found` 只要求锚出现过（伴值丢了也算找到），用来把「锚丢」和「行拆散」分开；
    - `merged` 是「同一行带承载了两行**签名不同**的行」，即 #60 §4.3 那种「19 行并成
      2–3 行」——只看 attach 会漏掉它，所以单独计数；
    - `attached` 要求：存在一条承载它的行带，且这条带没有同时承载另一行签名不同的行。

    **锚不是唯一键**：报关单里同一个 HS 码常出现在多行（同商品不同规格），所以不要求
    「锚只出现在一条带里」——那会把正常的重复 HS 码误判成失败，把伴值拿来区分。
    """

    ref_rows: int = 0
    anchor_rows: int = 0
    pred_rows: int = 0
    anchor_found: int = 0
    merged: int = 0
    attached: int = 0

    @property
    def row_count_ratio(self) -> float | None:
        if not self.ref_rows:
            return None
        return self.pred_rows / self.ref_rows

    @property
    def attach_rate(self) -> float | None:
        if not self.anchor_rows:
            return None
        return self.attached / self.anchor_rows

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "ref_rows": self.ref_rows,
            "anchor_rows": self.anchor_rows,
            "pred_rows": self.pred_rows,
            "row_count_ratio": self.row_count_ratio,
            "anchor_found": self.anchor_found,
            "merged_rows": self.merged,
            "attached": self.attached,
            "attach_rate": self.attach_rate,
        }


def cluster_row_bands(boxes: Sequence[BoxLike], *, y_tol_factor: float = 0.6) -> list[list[int]]:
    """按 y 中心把字块聚成行带，返回每带的字块下标。

    容差取**字块高度中位数** × `y_tol_factor`——绝对像素阈值在不同 DPI 的样本
    之间不可移植，用相对高度才跟分辨率无关。
    """

    if not boxes:
        return []
    heights = [abs(box.y1 - box.y0) for box in boxes]
    heights = [h for h in heights if h > 0]
    median_height = sorted(heights)[len(heights) // 2] if heights else 1.0
    tolerance = max(median_height * y_tol_factor, 1e-6)

    order = sorted(range(len(boxes)), key=lambda i: (boxes[i].y0 + boxes[i].y1) / 2)
    bands: list[list[int]] = []
    centers: list[float] = []
    for index in order:
        center = (boxes[index].y0 + boxes[index].y1) / 2
        if bands and abs(center - centers[-1]) <= tolerance:
            bands[-1].append(index)
            # 行带中心滚动平均：一页里字号可能变，跟着当前带调整
            centers[-1] = sum(
                (boxes[i].y0 + boxes[i].y1) / 2 for i in bands[-1]
            ) / len(bands[-1])
        else:
            bands.append([index])
            centers.append(center)
    return bands


def goods_row_structure(
    rows: Sequence[dict[str, str]],
    boxes: Sequence[BoxLike],
    *,
    anchor_key: str,
    mate_keys: Sequence[str] = (),
    region: tuple[float, float, float, float] | None = None,
    y_tol_factor: float = 0.6,
) -> GoodsRowStats:
    """参照商品行 vs 识别字块的行结构对比。

    `anchor_key` 是这一行的身份（半岛用 HS 码 `codeTs`），`mate_keys` 是必须跟它
    落在同一行带的伴值（数量 / 单价 / 原产国）。`region` 给货表区域，给了才把
    行带数限制在货表内——不给就是整页行带数，只能当参考值（报告里会写明）。
    """

    scoped = [
        box
        for box in boxes
        if region is None
        or (
            region[0] <= (box.x0 + box.x1) / 2 <= region[2]
            and region[1] <= (box.y0 + box.y1) / 2 <= region[3]
        )
    ]
    bands = cluster_row_bands(scoped, y_tol_factor=y_tol_factor)
    band_of_box = {index: band_index for band_index, band in enumerate(bands) for index in band}
    norm_text = [normalize(box.text) for box in scoped]

    def bands_containing(token: str) -> frozenset[int]:
        return frozenset(
            band_of_box[index] for index, text in enumerate(norm_text) if token and token in text
        )

    def band_carries(band_index: int, signature: tuple[str, tuple[str, ...]]) -> bool:
        anchor, mates = signature
        if band_index not in bands_containing(anchor):
            return False
        return all(band_index in bands_containing(mate) for mate in mates)

    signatures: list[tuple[str, tuple[str, ...]]] = []
    for row in rows:
        mates = tuple(
            mate for mate in (normalize(row.get(key, "")) for key in mate_keys) if mate
        )
        signatures.append((normalize(row.get(anchor_key, "")), mates))

    stats = GoodsRowStats(
        ref_rows=len(rows),
        anchor_rows=sum(1 for anchor, _mates in signatures if anchor),
        pred_rows=len(bands),
    )
    for index, signature in enumerate(signatures):
        anchor, _mates = signature
        if not anchor:
            continue
        if not bands_containing(anchor):
            continue
        stats.anchor_found += 1
        carrying = [band for band in range(len(bands)) if band_carries(band, signature)]
        if not carrying:
            continue  # 锚在、伴值散了：行被拆开，不算归属正确
        clashes = any(
            band_carries(band, other_signature)
            for band in carrying
            for other_index, other_signature in enumerate(signatures)
            # 签名相同的两行本来就分不开，不算互相「并」
            if other_index != index and other_signature[0] and other_signature != signature
        )
        if clashes:
            stats.merged += 1
        else:
            stats.attached += 1
    return stats

