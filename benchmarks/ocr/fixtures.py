"""自造报关单扫描夹具：程序渲染仿真出口报关单页，GT 精确已知，再派生扫描变体。

对应 Issue：#60。渲染结果只落 out/（不入库），GT 随代码可复现。
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

PAGE_W = 1240
PAGE_H = 1754
MARGIN = 60

_FONT_CANDIDATES: list[tuple[str, int]] = [
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 4),
    ("/System/Library/Fonts/STHeiti Light.ttc", 1),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
]

VARIANTS = ["base", "rot90", "rot180", "rot270", "jpeg60", "noise", "lowres"]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    env_path = os.environ.get("OCR_BENCH_FONT")
    if env_path:
        return ImageFont.truetype(env_path, size)
    for path, index in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            continue
    raise RuntimeError("未找到中文字体；可用环境变量 OCR_BENCH_FONT 指定 ttf/ttc 路径")


@dataclass
class FixtureSpec:
    key: str
    title: str
    pre_entry: tuple[str, str]
    customs_no: tuple[str, str]
    head_rows: list[tuple[str, str, str, str]]
    goods_header: list[str]
    goods_rows: list[list[str]]
    footer: list[str]


@dataclass
class GtLine:
    text: str
    bbox: tuple[float, float, float, float]


@dataclass
class FixtureImage:
    key: str
    variant: str
    image: bytes
    width: int
    height: int


@dataclass
class FixtureGt:
    key: str
    lines: list[GtLine] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    goods: list[list[str]] = field(default_factory=list)

    def full_text(self) -> str:
        return "\n".join(line.text for line in self.lines)


SPEC_A = FixtureSpec(
    key="a",
    title="中华人民共和国海关出口货物报关单",
    pre_entry=("预录入编号", "DEMO2026080001"),
    customs_no=("海关编号", "530320260000123456A"),
    head_rows=[
        ("境内发货人", "示例精密科技（惠州）有限公司", "出口日期", "2026.08.20"),
        ("境外收货人", "PENINSULA EXAMPLE CO., LTD.", "申报日期", "2026.08.22"),
        ("生产销售单位", "示例精密科技（惠州）有限公司", "运输方式", "水路运输"),
        ("合同协议号", "EX-20260824-01", "监管方式", "一般贸易"),
        ("贸易国（地区）", "香港", "征免性质", "一般征税"),
        ("指运港", "香港", "成交方式", "FOB"),
        ("件数", "120", "毛重（千克）", "1459.62"),
        ("净重（千克）", "485.00", "包装种类", "纸箱"),
    ],
    goods_header=[
        "序号",
        "商品编号",
        "商品名称及规格型号",
        "数量及单位",
        "原产国（地区）",
        "单价",
        "总价",
        "币制",
        "征免方式",
    ],
    goods_rows=[
        [
            "1", "8479899090", "示例机械配件", "型号EX-A100",
            "100个", "中国", "6.68", "668.00", "USD", "照章征税",
        ],
        [
            "2", "1905310000", "示例烘焙食品", "规格500克/袋",
            "200千克", "中国", "3.35", "670.00", "USD", "照章征税",
        ],
        [
            "3", "9403709990", "示例收纳家具", "型号EX-C200",
            "50件", "中国", "12.50", "625.00", "USD", "照章征税",
        ],
    ],
    footer=[
        "标记唛码及备注 N/M",
        "录入员 张三 录入单位 示例报关服务有限公司",
        "兹声明对以上内容承担如实申报、依法纳税之法律责任",
        "填制日期 2026.08.22",
    ],
)

SPEC_B = FixtureSpec(
    key="b",
    title="中华人民共和国海关出口货物报关单",
    pre_entry=("预录入编号", "DEMO2026090002"),
    customs_no=("海关编号", "514820260000654321B"),
    head_rows=[
        ("境内发货人", "示范家居用品（东莞）有限公司", "出口日期", "2026.09.05"),
        ("境外收货人", "GREAT WALL TRADING PTE. LTD.", "申报日期", "2026.09.06"),
        ("生产销售单位", "示范家居用品（东莞）有限公司", "运输方式", "航空运输"),
        ("合同协议号", "GW-2026-0998", "监管方式", "一般贸易"),
        ("贸易国（地区）", "新加坡", "征免性质", "一般征税"),
        ("指运港", "新加坡", "成交方式", "CIF"),
        ("件数", "86", "毛重（千克）", "732.40"),
        ("净重（千克）", "610.25", "包装种类", "木箱"),
    ],
    goods_header=[
        "序号",
        "商品编号",
        "商品名称及规格型号",
        "数量及单位",
        "原产国（地区）",
        "单价",
        "总价",
        "币制",
        "征免方式",
    ],
    goods_rows=[
        [
            "1", "9403609990", "示范木质衣架", "材质橡胶木/尺寸40cm",
            "3000个", "中国", "0.85", "2550.00", "USD", "照章征税",
        ],
    ],
    footer=[
        "标记唛码及备注 GW0998/SIN/86CTNS",
        "录入员 李四 录入单位 示范报关行",
        "兹声明对以上内容承担如实申报、依法纳税之法律责任",
        "填制日期 2026.09.06",
    ],
)


class _Renderer:
    def __init__(self, spec: FixtureSpec) -> None:
        self.spec = spec
        self.image = Image.new("RGB", (PAGE_W, PAGE_H), "white")
        self.draw = ImageDraw.Draw(self.image)
        self.lines: list[GtLine] = []
        self.fields: dict[str, str] = {}
        self.font_title = load_font(46)
        self.font_body = load_font(22)
        self.font_small = load_font(20)

    def _text(
        self,
        xy: tuple[int, int],
        text: str,
        font: ImageFont.FreeTypeFont,
        *,
        anchor: str = "la",
    ) -> None:
        self.draw.text(xy, text, fill="black", font=font, anchor=anchor)
        bbox = self.draw.textbbox(xy, text, font=font, anchor=anchor)
        self.lines.append(GtLine(text=text, bbox=(bbox[0], bbox[1], bbox[2], bbox[3])))

    def _rect(self, xy: tuple[int, int, int, int]) -> None:
        self.draw.rectangle(xy, outline="black", width=2)

    def render(self) -> None:
        spec = self.spec
        self._text((PAGE_W // 2, MARGIN), spec.title, self.font_title, anchor="ma")

        top = MARGIN + 84
        right = PAGE_W - MARGIN
        self._text(
            (right, top),
            f"{spec.pre_entry[0]} {spec.pre_entry[1]}",
            self.font_small,
            anchor="ra",
        )
        self._text(
            (right, top + 30),
            f"{spec.customs_no[0]} {spec.customs_no[1]}",
            self.font_small,
            anchor="ra",
        )
        self.fields[spec.pre_entry[0]] = spec.pre_entry[1]
        self.fields[spec.customs_no[0]] = spec.customs_no[1]

        grid_top = top + 84
        col_x = [MARGIN, MARGIN + 190, MARGIN + 520, MARGIN + 710, right]
        row_h = 48
        for i, (l1, v1, l2, v2) in enumerate(spec.head_rows):
            y0 = grid_top + i * row_h
            cy = y0 + row_h // 2
            self._text((col_x[0] + 14, cy), l1, self.font_body, anchor="lm")
            self._text((col_x[1] + 12, cy), v1, self.font_body, anchor="lm")
            self._text((col_x[2] + 14, cy), l2, self.font_body, anchor="lm")
            self._text((col_x[3] + 12, cy), v2, self.font_body, anchor="lm")
            self.fields[l1] = v1
            self.fields[l2] = v2
        grid_bottom = grid_top + len(spec.head_rows) * row_h
        grid_right = col_x[-1]
        for x in col_x:
            self.draw.line([(x, grid_top), (x, grid_bottom)], fill="black", width=2)
        for i in range(len(spec.head_rows) + 1):
            y = grid_top + i * row_h
            self.draw.line([(MARGIN, y), (grid_right, y)], fill="black", width=2)

        goods_top = grid_bottom + 36
        widths = [46, 122, 400, 110, 110, 78, 90, 58, 106]
        goods_x = [MARGIN]
        for w in widths:
            goods_x.append(goods_x[-1] + w)
        header_h = 44
        row_h_g = 66
        for j, head in enumerate(spec.goods_header):
            cx = (goods_x[j] + goods_x[j + 1]) // 2
            self._text((cx, goods_top + header_h // 2), head, self.font_small, anchor="mm")
        for i, row in enumerate(spec.goods_rows):
            y0 = goods_top + header_h + i * row_h_g
            cy = y0 + row_h_g // 2
            self._text(((goods_x[0] + goods_x[1]) // 2, cy), row[0], self.font_body, anchor="mm")
            self._text((goods_x[1] + 10, cy), row[1], self.font_body, anchor="lm")
            self._text((goods_x[2] + 10, y0 + 24), row[2], self.font_small, anchor="lm")
            self._text((goods_x[2] + 10, y0 + 48), row[3], self.font_small, anchor="lm")
            self._text((goods_x[3] + 12, cy), row[4], self.font_body, anchor="lm")
            self._text((goods_x[4] + 12, cy), row[5], self.font_body, anchor="lm")
            self._text(((goods_x[5] + goods_x[6]) // 2, cy), row[6], self.font_body, anchor="mm")
            self._text(((goods_x[6] + goods_x[7]) // 2, cy), row[7], self.font_body, anchor="mm")
            self._text(((goods_x[7] + goods_x[8]) // 2, cy), row[8], self.font_body, anchor="mm")
            self._text(((goods_x[8] + goods_x[9]) // 2, cy), row[9], self.font_body, anchor="mm")
        goods_bottom = goods_top + header_h + len(spec.goods_rows) * row_h_g
        for x in goods_x:
            self.draw.line([(x, goods_top), (x, goods_bottom)], fill="black", width=2)
        h_lines = [goods_top, goods_top + header_h]
        for i in range(1, len(spec.goods_rows) + 1):
            h_lines.append(goods_top + header_h + i * row_h_g)
        for y in h_lines:
            self.draw.line([(MARGIN, y), (goods_x[-1], y)], fill="black", width=2)

        foot_top = goods_bottom + 44
        for k, line in enumerate(spec.footer):
            self._text((MARGIN, foot_top + k * 34), line, self.font_body, anchor="la")


def render_spec(spec: FixtureSpec) -> tuple[Image.Image, FixtureGt]:
    renderer = _Renderer(spec)
    renderer.render()
    gt = FixtureGt(
        key=spec.key,
        lines=renderer.lines,
        fields=renderer.fields,
        goods=spec.goods_rows,
    )
    return renderer.image, gt


def apply_variant(base: Image.Image, variant: str) -> Image.Image:
    if variant in {"base", "jpeg60"}:
        return base
    if variant == "rot90":
        return base.rotate(90, expand=True, fillcolor="white")
    if variant == "rot180":
        return base.rotate(180, expand=True, fillcolor="white")
    if variant == "rot270":
        return base.rotate(270, expand=True, fillcolor="white")
    if variant == "noise":
        noisy = base.filter(ImageFilter.GaussianBlur(0.6))
        noise = Image.effect_noise(base.size, 14).convert("RGB")
        return ImageChops.add(noisy, noise, scale=1, offset=-128)
    if variant == "lowres":
        small = base.resize((int(base.width * 0.55), int(base.height * 0.55)), Image.LANCZOS)
        return small.resize(base.size, Image.BILINEAR)
    raise ValueError(f"未知变体：{variant}")


def to_jpeg(image: Image.Image, quality: int = 90) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def build_fixture_images(spec: FixtureSpec) -> list[FixtureImage]:
    base, _gt = render_spec(spec)
    images: list[FixtureImage] = []
    for variant in VARIANTS:
        img = apply_variant(base, variant)
        data = to_jpeg(img, quality=60 if variant == "jpeg60" else 90)
        images.append(
            FixtureImage(
                key=spec.key,
                variant=variant,
                image=data,
                width=img.width,
                height=img.height,
            )
        )
    return images


def build_all() -> tuple[list[FixtureImage], dict[str, FixtureGt]]:
    images: list[FixtureImage] = []
    gts: dict[str, FixtureGt] = {}
    for spec in (SPEC_A, SPEC_B):
        rendered, gt = render_spec(spec)
        gts[spec.key] = gt
        for variant in VARIANTS:
            img = apply_variant(rendered, variant)
            images.append(
                FixtureImage(
                    key=spec.key,
                    variant=variant,
                    image=to_jpeg(img, quality=60 if variant == "jpeg60" else 90),
                    width=img.width,
                    height=img.height,
                )
            )
    return images, gts
