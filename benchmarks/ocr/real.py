"""真机样本渲染：半岛 / 镇发 PDF 逐页出图。客户原件不入仓库，路径走环境变量。

- 半岛（SJ…）：2 页扫描报关单，页横图竖（rotation=270），带采购系统识别结果 JSON 作参照。
- 镇发（HKG…）：6 页扫描商业单据，无参照 JSON，仅做可视化与耗时。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]

_TRAILING_NOTE_RE = re.compile(r",\s*[^\"'{}\[\]\d][^,]*$")


def load_reference_json(path: Path) -> dict:
    """参照 JSON 里可能有人工批注（值后面的中文备注），严格解析失败再剥一次。"""

    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = "\n".join(_TRAILING_NOTE_RE.sub(",", line) for line in text.splitlines())
        return json.loads(cleaned)

PENINSULA_PDF = "SJ25084373-310795HKD.pdf"
PENINSULA_REF = "SJ25084373-310795HKD-识别结果.json"
ZHENFA_PDF = "HKG25003373MUC/镇发出口报关资料（11件）.pdf"

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


@dataclass
class RealSample:
    name: str
    pages: list[RealPage]
    reference: dict | None = None
    key_fields: dict[str, str] | None = None


def demo_dir() -> Path:
    env = os.environ.get("DOCPARSE_OCR_DEMO_DIR")
    return Path(env) if env else ROOT.parent / "AI识别Demo"


def _render_pdf(pdf_path: Path, sample: str, zoom: float = 2.0) -> list[RealPage]:
    doc = pymupdf.open(pdf_path)
    pages: list[RealPage] = []
    matrix = pymupdf.Matrix(zoom, zoom)
    for index, page in enumerate(doc, start=1):
        pixmap = page.get_pixmap(matrix=matrix)
        data = pixmap.tobytes("jpeg", jpg_quality=90)
        pages.append(
            RealPage(
                key=f"{sample}-p{index}",
                pdf_name=pdf_path.name,
                page_number=index,
                image=data,
            )
        )
    doc.close()
    return pages


def load_real_samples() -> list[RealSample]:
    base = demo_dir()
    samples: list[RealSample] = []

    peninsula_pdf = base / PENINSULA_PDF
    if peninsula_pdf.exists():
        reference = None
        ref_path = base / PENINSULA_REF
        if ref_path.exists():
            reference = load_reference_json(ref_path)
        samples.append(
            RealSample(
                name="peninsula",
                pages=_render_pdf(peninsula_pdf, "peninsula"),
                reference=reference,
                key_fields=PENINSULA_KEY_FIELDS,
            )
        )

    zhenfa_pdf = base / ZHENFA_PDF
    if zhenfa_pdf.exists():
        samples.append(RealSample(name="zhenfa", pages=_render_pdf(zhenfa_pdf, "zhenfa")))

    return samples


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
