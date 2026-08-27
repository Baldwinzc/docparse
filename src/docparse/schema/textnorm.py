"""键文本归一化（Issue #66 / #82）。键 / 锚点专用，永远不碰值。

三件事：
- 去全部空白（含换行）：「毛 重」「毛重\\n（公斤）」都折成可对锚点的形状；
- 全角括号统一半角：锚点 / 词表只收一种写法；
- 键尾剥「（≤18 位字母数字）」码：「贸易方式（0110）」→「贸易方式」，
  「境内收货人（91440300MA5FETXT25）」→「境内收货人」（#82：备案清单把
  18 位信用代码印在标签里；4 位关区 / 6 位港码 / 10 位海关码同一条路收）。
  括号里不是字母数字（「贸易国（地区）」「毛重（公斤）」）不剥。
值里的括号码是业务信息，剥码只发生在键这一侧。
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")
_CJK_SPACE = re.compile(r"(?<=[^\x00-\x7f])\s+(?=[^\x00-\x7f])")
_FULLWIDTH_PARENS = str.maketrans("（）", "()")
_TRAILING_CODE = re.compile(r"[（(][A-Za-z0-9]{1,18}[)）]\Z")


def strip_trailing_code(text: str) -> str:
    """键尾括号码剥掉。「（0110）」「（91440300MA5FETXT25）」剥，「（地区）」不剥。"""
    return _TRAILING_CODE.sub("", text)


def _prepare(text: str, space: str) -> str:
    collapsed = _WHITESPACE.sub(space, text.strip())
    if space:
        # 中日韩字符之间的空格是排版噪声，去掉；ASCII 词距保留
        collapsed = _CJK_SPACE.sub("", collapsed)
    cleaned = strip_trailing_code(collapsed.translate(_FULLWIDTH_PARENS))
    return cleaned.casefold()


def fold_key(text: str) -> str:
    """紧凑形：空白全去。中文键 / 锚点对齐用它。"""
    return _prepare(text, "")


def fold_spaced(text: str) -> str:
    """保留词距形：英文 token 边界还在，供词边界匹配。"""
    return _prepare(text, " ")
