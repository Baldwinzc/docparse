"""评测指标：归一化、字符错误率（CER）、字段命中。仅标准库。"""

from __future__ import annotations

import re
import unicodedata

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
