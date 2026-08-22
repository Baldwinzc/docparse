"""给每张 sheet 打角色。只贴标签，不删格子，不映射报关字段。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from docparse.domain.ir import DocumentIR, Sheet
from docparse.schema.loader import RoleSignal, SheetRole, SheetRoles, load_sheet_roles

_SPACE = re.compile(r"\s+")
_GENERIC_SHEET_NAME = re.compile(r"^(sheet\s*\d+|\d+)$", re.IGNORECASE)


def classify_sheets(document: DocumentIR) -> DocumentIR:
    catalog = load_sheet_roles()
    document.sheets = [
        classify_sheet(sheet, filename=document.filename, catalog=catalog)
        for sheet in document.sheets
    ]
    return document


def classify_sheet(
    sheet: Sheet,
    *,
    filename: str = "",
    catalog: SheetRoles | None = None,
) -> Sheet:
    catalog = catalog or load_sheet_roles()
    scored = [_score_role(sheet, filename, role, catalog) for role in catalog.roles]
    scored.sort(key=lambda item: item.score, reverse=True)
    best = scored[0] if scored else None
    runner_up = scored[1].score if len(scored) > 1 else 0
    if best is None or best.score < catalog.min_score or best.score == runner_up:
        return sheet.model_copy(
            update={
                "role": "unknown",
                "role_confidence": (
                    0.2 if best is None else _confidence(best.score, catalog.min_score)
                ),
                "consume": catalog.unknown_consume,
                "role_hits": [] if best is None else best.hits,
            }
        )
    return sheet.model_copy(
        update={
            "role": best.role_id,
            "role_confidence": _confidence(best.score, catalog.min_score),
            "consume": best.consume,
            "role_hits": best.hits,
        }
    )


@dataclass(frozen=True)
class _RoleScore:
    role_id: str
    consume: str
    score: int
    hits: list[str]


def _score_role(sheet: Sheet, filename: str, role: SheetRole, catalog: SheetRoles) -> _RoleScore:
    hits: list[str] = []
    score = 0
    hay = _sheet_haystack(sheet)
    score += _match_signals(role.signals.titles, hay, "title", hits)
    score += _match_signals(role.signals.keys, _key_haystack(sheet), "key", hits)
    score += _match_signals(role.signals.headers, _header_haystack(sheet), "header", hits)
    if role.lookup_pairs and _looks_like_lookup(sheet):
        score += 4
        hits.append("shape:lookup_pairs")
    if filename:
        score += _match_filename(role.signals.filename, filename, catalog.filename_weight, hits)
    return _RoleScore(role_id=role.id, consume=role.consume, score=score, hits=hits)


def _match_signals(
    signals: list[RoleSignal],
    texts: list[str],
    kind: str,
    hits: list[str],
) -> int:
    total = 0
    for signal in signals:
        if any(_hits_text(item, signal) for item in texts):
            total += signal.weight
            hits.append(f"{kind}:{signal.text}")
    return total


def _match_filename(
    signals: list[RoleSignal],
    filename: str,
    default_weight: int,
    hits: list[str],
) -> int:
    folded = _fold(filename)
    total = 0
    for signal in signals:
        needle = _fold(signal.text)
        if needle and needle in folded:
            total += default_weight
            hits.append(f"filename:{signal.text}")
    return total


def _sheet_haystack(sheet: Sheet) -> list[str]:
    texts = [_fold(sheet.name)]
    if _GENERIC_SHEET_NAME.match(sheet.name.strip()):
        texts = [""]
    for cell in sheet.cells:
        if cell.row is None or cell.row > 8 or not cell.value:
            continue
        texts.append(_fold(cell.value))
    return [item for item in texts if item]


def _key_haystack(sheet: Sheet) -> list[str]:
    return [_fold(item.key) for item in sheet.key_values if item.key]


def _header_haystack(sheet: Sheet) -> list[str]:
    texts: list[str] = []
    for table in sheet.tables:
        texts.extend(_fold(header) for header in table.headers if header)
    return texts


def _looks_like_lookup(sheet: Sheet) -> bool:
    if sheet.tables or len(sheet.key_values) >= 3:
        return False
    filled: dict[int, int] = {}
    for cell in sheet.cells:
        if cell.row is None or not cell.value:
            continue
        filled[cell.row] = filled.get(cell.row, 0) + 1
    if len(filled) < 3:
        return False
    pairs = sum(1 for count in filled.values() if count == 2)
    return pairs >= 3 and pairs * 5 >= len(filled) * 3


def _hits_text(haystack: str, signal: RoleSignal) -> bool:
    needle = _compact(_fold(signal.text))
    hay = _compact(haystack)
    if not needle:
        return False
    if signal.match == "exact":
        return hay == needle
    return needle in hay


def _fold(text: str) -> str:
    return _SPACE.sub(" ", text.strip()).casefold()


def _compact(text: str) -> str:
    return text.replace(" ", "")


def _confidence(score: int, min_score: int) -> float:
    if score < min_score:
        return 0.2
    if score < min_score + 2:
        return 0.7
    return 0.95
