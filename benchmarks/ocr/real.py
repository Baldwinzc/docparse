"""真机样本渲染：把清单登记的真机 PDF 逐页出图，外加参照 JSON 的读取。

**哪几份、哪几页、旋转角多少，全部读 `samples.py` 的清单**——本模块不再硬编码路径，
也不判断旋转（那是清单的 `rotation_truth`）。客户原件不入仓库，目录走
`DOCPARSE_OCR_DEMO_DIR`（见 `samples.demo_dir`）。

- 半岛（SJ…）：2 页扫描报关单，PDF `/Rotate=270` 元数据在渲染时已被应用，
  所以出图是正立的（**不是内容旋转**，与镇发区分，见 #103）；带采购系统识别结果 JSON 作参照。
- 镇发（HKG…）：6 页扫描商业单据，p1 / p6 内容旋转 90°，其余平放；无参照 JSON。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

_TRAILING_NOTE_RE = re.compile(r",\s*[^\"'{}\[\]\d][^,]*$")


def load_reference_json(path: Path) -> dict:
    """参照 JSON 里可能有人工批注（值后面的中文备注），严格解析失败再剥一次。"""

    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = "\n".join(_TRAILING_NOTE_RE.sub(",", line) for line in text.splitlines())
        return json.loads(cleaned)


PENINSULA_KEY_FIELDS: dict[str, str] = {
    "contrNo": "合同协议号",
    "manualNo": "备案号",
    "grossWt": "毛重",
    "netWt": "净重",
    "packNo": "件数",
    "goodsPlace": "货物存放地点",
    "markNo": "标记唛码",
    "consignorEname": "境外发货人英文名",
    "cusTradeCountry": "贸易国代码",
    "cusVoyageNo": "航次号",
}

TEXTIN_CUSTOMS_FIELD_MAP: dict[str, str] = {
    "contrNo": "contract_agreement_number",
    "manualNo": "record_number",
    "grossWt": "gross_weight",
    "netWt": "net_weight",
    "packNo": "number_of_packages",
    "goodsPlace": "storage_place",
    "markNo": "marking_marks_and_remarks",
    "consignorEname": "overseas_consignor",
    "cusTradeCountry": "trading_country_code",
}


@dataclass
class RealPage:
    key: str
    pdf_name: str
    page_number: int
    image: bytes


def render_pdf_pages(pdf_path: Path, prefix: str, zoom: float = 2.0) -> list[RealPage]:
    """逐页渲染成 JPEG。key 用 `samples.py` 的页 key（`{prefix}-p{n}`），两边必须对上。"""

    doc = pymupdf.open(pdf_path)
    pages: list[RealPage] = []
    matrix = pymupdf.Matrix(zoom, zoom)
    for index, page in enumerate(doc, start=1):
        pixmap = page.get_pixmap(matrix=matrix)
        data = pixmap.tobytes("jpeg", jpg_quality=90)
        pages.append(
            RealPage(
                key=f"{prefix}-p{index}",
                pdf_name=pdf_path.name,
                page_number=index,
                image=data,
            )
        )
    doc.close()
    return pages


def peninsula_reference_fields(reference: dict) -> dict[str, str]:
    dec = reference.get("dec_results", {})
    fields: dict[str, str] = {}
    for key in PENINSULA_KEY_FIELDS:
        value = dec.get(key)
        if isinstance(value, str) and value:
            fields[key] = value
    return fields


def peninsula_goods_summary(reference: dict) -> list[dict[str, str]]:
    rows = reference.get("dec_results", {}).get("tdecGoodsitemsVoArr", [])
    summary: list[dict[str, str]] = []
    for row in rows:
        summary.append(
            {
                "codeTs": str(row.get("codeTs", "")),
                "customNetWt": str(row.get("customNetWt", "")),
                "declPrice": str(row.get("declPrice", "")),
                "cusOriginCountry": str(row.get("cusOriginCountry", "")),
            }
        )
    return summary
