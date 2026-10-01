"""样本清单与派生（#109）：一共几份、各自什么用途、哪份能上云、旋转页是哪几页。

本模块是「同一批样本」这句话的**唯一出处**：`real.py` 渲染哪份 PDF、`run.py` 跑哪些图、
报告里哪些页归到旋转表，都从这里读，不再各自硬编码路径、也不再靠 key 里的 `rot90`
字符串猜角度。

## 术语（先看这条，两侧约定不同，混了 #110 的归因实验就不可复现）

- `kind` / 派生名（`rot90`）：对这张图**施加**的旋转，与 `fixtures.apply_variant`
  同一约定（`PIL.Image.rotate`，逆时针）。
- `rotation_truth`：把这份图**转正**所需的逆时针角度，**就是 #110 C 组要敲的
  `--force-deg`**；`0` = 已正立。

两者互为补角：`truth(派生件) = (truth(原件) - 施加角) % 360`。所以

- 夹具 `a-rot90` 的 `rotation_truth` 是 **270**（名字记的是施加的角，转正要反着来）；
- 真机 `zhenfa-p1` 的 `rotation_truth` 是 **90**；对它再施加 rot90 得到 `zhenfa-p1-rot90`，
  那份 `rotation_truth` 是 **0**——它正是 #110 A 组要喂的「人工转正图」。

「内容旋转 90°」这类口语在两侧都出现过，**不要按字面推**：以本清单的 `rotation_truth` 为准。
没有这个数，`--rotate-mode force --force-deg 90`（#108 的 C 组）就只能人工敲数字，归因不可复现。

## 隐私红线（#108 / #97）

`AI识别Demo` 下是客户真实数据，**不得上传任何云端**。真机样本（含其派生件）`cloud_ok`
一律 `False`，派生件**继承原件**的 `cloud_ok`——派生自真机就还是真机数据。原件不入库，
路径走 `DOCPARSE_OCR_DEMO_DIR`（默认 `../AI识别Demo`），仓库里只留清单与参照。
"""

from __future__ import annotations

import fnmatch
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# 派生定义（唯一出处）

@dataclass(frozen=True)
class Derivation:
    """一种派生：往原图上**施加**什么加工。"""

    name: str
    kind: str
    applied_deg: int
    note: str


DERIVATIONS: dict[str, Derivation] = {
    "base": Derivation("base", "flat", 0, "原件本页，未做任何加工"),
    "rot90": Derivation("rot90", "rot90", 90, "整页逆时针 90°：方向分类没判出来就是这档崩"),
    "rot180": Derivation("rot180", "rot180", 180, "倒置 180°：方向分类的第三类"),
    "rot270": Derivation("rot270", "rot270", 270, "整页逆时针 270°（即顺时针 90°）"),
    "jpeg60": Derivation("jpeg60", "jpeg", 0, "JPEG 质量 60 重编码：压缩噪声对字块检测的影响"),
    "noise": Derivation("noise", "noise", 0, "高斯模糊 + 均匀噪声：模拟低质扫描"),
    "lowres": Derivation(
        "lowres", "lowres", 0, "降到 55% 再放大回原尺寸：低清扫描，字块检测先崩的那档"
    ),
}

# 夹具的七种变体由 fixtures.py 自己渲染（见 FIXTURE_DERIVATIONS 的一致性单测）；
# 真机页只派生这四类——jpeg / noise 对真机页意义不大（真机页本身就是 JPEG 扫描件）。
FIXTURE_DERIVATIONS: tuple[str, ...] = (
    "base",
    "rot90",
    "rot180",
    "rot270",
    "jpeg60",
    "noise",
    "lowres",
)
REAL_DERIVATIONS: tuple[str, ...] = ("base", "rot90", "rot180", "rot270", "lowres")


def derivations_for(source: str) -> tuple[str, ...]:
    """某类来源派生哪几档。加一档派生时改这里（实现见 fixtures.apply_variant）。"""

    if source == "fixture":
        return FIXTURE_DERIVATIONS
    if source == "real":
        return REAL_DERIVATIONS
    raise ValueError(f"未知来源：{source}")


# ---------------------------------------------------------------------------
# 参照

@dataclass(frozen=True)
class Reference:
    key: str
    label: str


REFERENCES: dict[str, Reference] = {
    "fixture-gt": Reference("fixture-gt", "夹具 GT（字段+商品行+bbox）"),
    "peninsula-head-goods": Reference(
        "peninsula-head-goods", "半岛表头 10 字段 + 19 商品行"
    ),
    "none": Reference("none", "无"),
}


def reference_label(key: str) -> str:
    return REFERENCES[key].label


# ---------------------------------------------------------------------------
# 原件登记（真机 + 夹具）

@dataclass(frozen=True)
class PageOrigin:
    """原件里的一页。`truth` 是这一页**转正**所需的逆时针角度（0 = 已正立）。"""

    key: str
    number: int
    truth: int
    note: str


@dataclass(frozen=True)
class Original:
    key: str
    source: str
    label: str
    pages: tuple[PageOrigin, ...]
    reference: str = "none"
    cloud_ok: bool = True
    path: str = ""
    reference_json: str = ""


PENINSULA = Original(
    key="peninsula",
    source="real",
    label="半岛 SJ25084373-310795HKD",
    path="SJ25084373-310795HKD.pdf",
    reference_json="SJ25084373-310795HKD-识别结果.json",
    reference="peninsula-head-goods",
    cloud_ok=False,
    pages=(
        PageOrigin(
            "peninsula-p1",
            1,
            0,
            "扫描报关单首页；PDF /Rotate=270 元数据在渲染时已转正，"
            "**不是内容旋转**（#103 要区分的那两种）",
        ),
        PageOrigin(
            "peninsula-p2",
            2,
            0,
            "同 p1，商品表续页；PDF /Rotate=270 元数据渲染时已转正，同样不是内容旋转",
        ),
    ),
)

ZHENFA = Original(
    key="zhenfa",
    source="real",
    label="镇发 HKG25003373MUC",
    path="HKG25003373MUC/镇发出口报关资料（11件）.pdf",
    reference="none",
    cloud_ok=False,
    pages=(
        PageOrigin(
            "zhenfa-p1",
            1,
            90,
            "**真机内容旋转 90°**：出口货物报关单，转正角 90；选型分水岭（#103）",
        ),
        PageOrigin("zhenfa-p2", 2, 0, "出口装箱单，平放"),
        PageOrigin("zhenfa-p3", 3, 0, "装箱明细，平放"),
        PageOrigin("zhenfa-p4", 4, 0, "出口发票，平放"),
        PageOrigin("zhenfa-p5", 5, 0, "购销合同，平放"),
        PageOrigin(
            "zhenfa-p6",
            6,
            90,
            "**真机内容旋转 90°**：出口规范申报要素，转正角同 p1；"
            "#97 盘点时只记了 p1，实测多出这一页",
        ),
    ),
)

REAL_ORIGINALS: tuple[Original, ...] = (PENINSULA, ZHENFA)

FIXTURE_ORIGINALS: tuple[Original, ...] = (
    Original(
        key="a",
        source="fixture",
        label="夹具 A（3 商品行）",
        reference="fixture-gt",
        pages=(PageOrigin("a", 1, 0, "程序渲染的仿真出口报关单，GT 精确已知，可上云"),),
    ),
    Original(
        key="b",
        source="fixture",
        label="夹具 B（1 商品行）",
        reference="fixture-gt",
        pages=(PageOrigin("b", 1, 0, "第二个版式，商品行更少，可上云"),),
    ),
)


def origins() -> tuple[Original, ...]:
    """全部原件：夹具在前，真机在后。

    加一份真机件 → 往 `REAL_ORIGINALS` 加一条 `Original`，别处不用动。
    """

    return (*FIXTURE_ORIGINALS, *REAL_ORIGINALS)


def demo_dir() -> Path:
    """真机原件目录（不入库；换机器用这个环境变量指过去）。"""

    env = os.environ.get("DOCPARSE_OCR_DEMO_DIR")
    return Path(env) if env else ROOT.parent / "AI识别Demo"


def origin_available(origin: Original) -> bool:
    """夹具永远可用；真机看原件在不在盘上。"""

    if origin.source != "real":
        return True
    return (demo_dir() / origin.path).exists()


def missing_origin_keys() -> tuple[str, ...]:
    return tuple(origin.key for origin in origins() if not origin_available(origin))


# ---------------------------------------------------------------------------
# 逐份样本

@dataclass(frozen=True)
class SampleSpec:
    """一份样本的全部登记项（不含图片字节）。

    `reference` 是参照的 key，`cloud_ok` 是隐私红线的开关（真机一律 False），
    `rotation_truth` 是转正角（= C 组 `--force-deg`）。
    """

    key: str
    source: str
    cloud_ok: bool
    kind: str
    origin: str
    page_key: str
    page: int
    variant: str
    rotation_truth: int
    reference: str
    notes: str

    @property
    def is_rotation(self) -> bool:
        """内容不在正立状态——#103 要求这类页结论不得混进平放页平均分。"""

        return self.rotation_truth % 360 != 0

    @property
    def is_derived(self) -> bool:
        return self.variant != "base"

    @property
    def target_kind(self) -> str:
        """喂给 `run.Target.kind` 的档位：真机 = real（云引擎默认闸住）。"""

        return "real" if self.source == "real" else "synthetic"


def _sample_key(page_key: str, source: str, variant: str) -> str:
    """样本 key。

    命名沿用既有口径，**不要改成统一的 `-base` 后缀**：#60 / #108 落盘的产物按这套名字存
    （`out/results/<引擎>/zhenfa-p1.json`），报告里的半岛表也按这个 key 对参照。

    - 真机原件页 = `{页 key}`（`zhenfa-p1`），派生件才加后缀（`zhenfa-p1-rot90`）；
    - 夹具一直带变体后缀（`a-base`），沿用既有口径。
    """

    if source == "real" and variant == "base":
        return page_key
    return f"{page_key}-{variant}"


def sample_specs() -> list[SampleSpec]:
    """枚举全部样本（原件 × 派生），顺序稳定：夹具在前，真机按页序。"""

    specs: list[SampleSpec] = []
    for origin in origins():
        for page in origin.pages:
            for name in derivations_for(origin.source):
                deriv = DERIVATIONS[name]
                specs.append(
                    SampleSpec(
                        key=_sample_key(page.key, origin.source, name),
                        source=origin.source,
                        # 派生件继承原件的 cloud_ok：派生自真机就还是真机数据
                        cloud_ok=origin.cloud_ok,
                        kind=deriv.kind,
                        origin=origin.key,
                        page_key=page.key,
                        page=page.number,
                        variant=name,
                        rotation_truth=(page.truth - deriv.applied_deg) % 360,
                        reference=origin.reference,
                        notes=page.note if name == "base" else deriv.note,
                    )
                )
    return specs


def available_sample_specs() -> list[SampleSpec]:
    """清单去掉原件不在这台机器上的那些（夹具永远在）。"""

    missing = set(missing_origin_keys())
    return [spec for spec in sample_specs() if spec.origin not in missing]


def spec_by_key() -> dict[str, SampleSpec]:
    return {spec.key: spec for spec in sample_specs()}


def sample_keys() -> list[str]:
    return [spec.key for spec in sample_specs()]


# ---------------------------------------------------------------------------
# 取图

@dataclass
class Sample:
    spec: SampleSpec
    image: bytes


def derive(image: bytes, derivation: Derivation) -> bytes:
    """真机页派生。

    实现**复用夹具那一套**（`fixtures.apply_variant`）——低清系数、旋转方向只有一处，
    两边口径不会漂。夹具自己的变体由 `fixtures.build_all()` 直接出图，不走这里。
    """

    if derivation.name == "base":
        return image
    import io

    from PIL import Image

    from benchmarks.ocr import fixtures as fx

    with Image.open(io.BytesIO(image)) as handle:
        handle.load()
        out = fx.apply_variant(handle.convert("RGB"), derivation.name)
    return fx.to_jpeg(out, quality=60 if derivation.kind == "jpeg" else 90)


def _in_scope(spec: SampleSpec, scope: str) -> bool:
    if scope == "all":
        return True
    if scope == "fixtures":
        return spec.source == "fixture"
    if scope == "real":
        return spec.source == "real" and not spec.is_derived
    if scope == "real-derived":
        return spec.source == "real" and spec.is_derived
    raise ValueError(f"未知 scope：{scope}")


def _matches(key: str, patterns: tuple[str, ...]) -> bool:
    """`--sample` 过滤：fnmatch 通配（不带通配符就是精确匹配，`zhenfa-p1` 不会带上派生件）。"""

    if not patterns:
        return True
    return any(fnmatch.fnmatch(key, pattern) for pattern in patterns)


class _ImageSources:
    """按需取图：每份原件只渲染一次，派生件算一次就缓存。"""

    def __init__(self) -> None:
        self._fixtures: dict[tuple[str, str], bytes] | None = None
        self._real_pages: dict[str, dict[str, bytes]] = {}
        self._cache: dict[str, bytes] = {}

    def _fixture_images(self) -> dict[tuple[str, str], bytes]:
        if self._fixtures is None:
            from benchmarks.ocr import fixtures as fx

            images, _gts = fx.build_all()
            self._fixtures = {(image.key, image.variant): image.image for image in images}
        return self._fixtures

    def _real_base_pages(self, origin_key: str) -> dict[str, bytes]:
        if origin_key not in self._real_pages:
            from benchmarks.ocr import real

            origin = next(o for o in origins() if o.key == origin_key)
            pages = real.render_pdf_pages(demo_dir() / origin.path, origin.key)
            self._real_pages[origin_key] = {page.key: page.image for page in pages}
        return self._real_pages[origin_key]

    def get(self, spec: SampleSpec) -> bytes:
        if spec.key in self._cache:
            return self._cache[spec.key]
        if spec.source == "fixture":
            # 夹具七档由 fixtures.py 一次出全
            image = self._fixture_images()[(spec.origin, spec.variant)]
        else:
            base = self._real_base_pages(spec.origin)[spec.page_key]
            image = derive(base, DERIVATIONS[spec.variant])
        self._cache[spec.key] = image
        return image


def load_samples(scope: str = "all", keys: tuple[str, ...] = ()) -> list[Sample]:
    """取图。`scope` 见 `SCOPES`；`keys` 是 fnmatch 通配的 key 过滤。"""

    sources = _ImageSources()
    return [
        Sample(spec=spec, image=sources.get(spec))
        for spec in available_sample_specs()
        if _in_scope(spec, scope) and _matches(spec.key, keys)
    ]


SCOPES: tuple[str, ...] = ("fixtures", "real", "real-derived", "all")


# ---------------------------------------------------------------------------
# 未覆盖类（#106 口径：显式记账，不许用「样本有限」一句话带过）

@dataclass(frozen=True)
class Uncovered:
    key: str
    label: str
    why: str
    how: str


UNCOVERED: tuple[Uncovered, ...] = (
    Uncovered(
        key="dense-goods-table",
        label="不同来源的密集商品表",
        why="现在只有半岛 19 商品行，密集表是行切分 / 列归属的主战场；"
        "一份来源过了不代表别的来源过了",
        how="追加真机测试件（原件不入库，放进 DOCPARSE_OCR_DEMO_DIR 后在 ORIGINS 登记一条）",
    ),
    Uncovered(
        key="photo-capture",
        label="拍照件（手机翻拍，非平板扫描）",
        why="透视畸变 / 光照不均 / 边缘阴影是**独立的失败模式**，扫描件过了不能推出拍照件过",
        how="手机翻拍 1–2 份（可脱敏），与真机同样按 cloud_ok=False 登记",
    ),
    Uncovered(
        key="real-landscape-more",
        label="真机横放件的更多实例",
        why="真机横放件只有镇发 p1 / p6 两页；**派生页过不等于真机横放件过**（#103 的分水岭）",
        how="再找横放扫描的真机件；在此之前，p1 / p6 的结论按两页样本读，不外推",
    ),
)


def uncovered_keys() -> list[str]:
    return [f"uncovered:{item.key}" for item in UNCOVERED]


# ---------------------------------------------------------------------------
# 旋转页转正对照（#110 A / B / C 三组的取图与角度）

@dataclass(frozen=True)
class RotationCase:
    """一个真机旋转页：转正角 + A 组要喂的那份转正图。"""

    page_key: str
    source: str
    truth: int
    upright_key: str

    def a_command(self, engine: str = "ENGINE") -> str:
        scope = "real-derived" if self.source == "real" else "fixtures"
        return (
            f"python -m benchmarks.ocr.run call --engine {engine} --scope {scope} "
            f"--rotate-mode off --sample {self.upright_key}"
        )

    def b_command(self, engine: str = "ENGINE") -> str:
        return (
            f"python -m benchmarks.ocr.run call --engine {engine} --scope real "
            f"--rotate-mode auto --sample {self.page_key}"
        )

    def c_command(self, engine: str = "ENGINE") -> str:
        return (
            f"python -m benchmarks.ocr.run call --engine {engine} --scope real "
            f"--rotate-mode force --force-deg {self.truth} --sample {self.page_key}"
        )


# 施加多少度 → 那个派生件叫什么（转正件就是把 rotation_truth 当施加角）
_NAME_BY_APPLIED = {0: "base", 90: "rot90", 180: "rot180", 270: "rot270"}


def upright_counterpart_key(spec: SampleSpec) -> str:
    """把 `spec` 转正所需的**派生件名**：施加 `rotation_truth` 度。

    真机 `zhenfa-p1`（truth 90）→ `zhenfa-p1-rot90`（truth 0）——就是 A 组喂的那份。
    """

    if spec.rotation_truth % 90:
        raise ValueError(f"{spec.key} 的 rotation_truth={spec.rotation_truth} 不是 90 的整数倍")
    name = _NAME_BY_APPLIED[spec.rotation_truth % 360]
    if name not in derivations_for(spec.source):
        raise ValueError(f"{spec.source} 没有派生 {name}，转正件取不到：{spec.key}")
    return _sample_key(spec.page_key, spec.source, name)


def rotation_cases() -> list[RotationCase]:
    """所有**原件页**里的旋转件（派生件不重复列，它们由原件推出）。"""

    cases: list[RotationCase] = []
    for spec in sample_specs():
        if spec.variant != "base" or not spec.is_rotation:
            continue
        cases.append(
            RotationCase(
                page_key=spec.page_key,
                source=spec.source,
                truth=spec.rotation_truth,
                upright_key=upright_counterpart_key(spec),
            )
        )
    return cases


# ---------------------------------------------------------------------------
# 覆盖矩阵与打印

@dataclass(frozen=True)
class CoverageRow:
    kind: str
    real: int
    fixture: int

    @property
    def total(self) -> int:
        return self.real + self.fixture


def coverage_matrix(specs: list[SampleSpec] | None = None) -> list[CoverageRow]:
    rows = specs if specs is not None else sample_specs()
    counts: dict[str, dict[str, int]] = {}
    for spec in rows:
        counts.setdefault(spec.kind, {"real": 0, "fixture": 0})[spec.source] += 1
    return [
        CoverageRow(kind=kind, real=count["real"], fixture=count["fixture"])
        for kind, count in sorted(counts.items())
    ]


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _plain(text: str) -> str:
    """清单是给人看的纯文本，登记项里的 markdown 加粗去掉。"""

    return text.replace("**", "")


def _clip(text: str, width: int = 44) -> str:
    text = _plain(text)
    if _display_width(text) <= width:
        return text
    out = ""
    used = 0
    for ch in text:
        size = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if used + size > width - 1:
            break
        out += ch
        used += size
    return out + "…"


def _mark(value: bool) -> str:
    return "✓" if value else "×"


def format_listing() -> str:
    """人读的清单：原件 → 逐份样本 → 覆盖矩阵 → 未覆盖类 → 旋转页 A/B/C 对照。"""

    specs = sample_specs()
    available = available_sample_specs()
    real_count = sum(1 for spec in specs if spec.source == "real")
    fixture_count = sum(1 for spec in specs if spec.source == "fixture")
    lines: list[str] = []
    lines.append(
        f"样本清单（#109）—— 真机 {real_count} 份 / 夹具 {fixture_count} 份，共 {len(specs)} 份"
    )
    lines.append(f"真机原件目录：{demo_dir()}（原件不入库；路径走 DOCPARSE_OCR_DEMO_DIR）")
    missing = missing_origin_keys()
    if missing:
        lines.append(
            f"⚠ 本机缺原件：{'、'.join(missing)}——这些样本不参与跑数，清单里仍然登记"
        )
    elif len(available) < len(specs):
        lines.append(f"⚠ 本机可用样本 {len(available)}/{len(specs)} 份")

    lines.append("")
    lines.append("== 原件 ==")
    header = ("原件页", 20), ("来源", 8), ("页", 4), ("外呼", 6), ("参照", 28), ("转正角", 8)
    lines.append("  ".join(_pad(name, width) for name, width in header) + "说明")
    for origin in origins():
        for page in origin.pages:
            cells = [
                _pad(page.key, 20),
                _pad(origin.source, 8),
                _pad(str(page.number), 4),
                _pad(_mark(origin.cloud_ok), 6),
                _pad(reference_label(origin.reference), 28),
                _pad(str(page.truth), 8),
            ]
            lines.append("  ".join(cells) + _clip(page.note, 60))

    lines.append("")
    lines.append("== 逐份样本 ==")
    header = (
        ("key", 22),
        ("来源", 8),
        ("外呼", 6),
        ("类型", 8),
        ("页", 4),
        ("参照", 28),
        ("真实角度", 10),
    )
    lines.append("  ".join(_pad(name, width) for name, width in header) + "说明")
    for spec in specs:
        cells = [
            _pad(spec.key, 22),
            _pad(spec.source, 8),
            _pad(_mark(spec.cloud_ok), 6),
            _pad(spec.kind, 8),
            _pad(str(spec.page), 4),
            _pad(reference_label(spec.reference), 28),
            _pad(str(spec.rotation_truth), 10),
        ]
        lines.append("  ".join(cells) + _clip(spec.notes))
    lines.append(
        "真实角度 = 把这份图转正所需的逆时针角 = C 组 --force-deg；0 = 已正立。"
        "派生件继承原件的 cloud_ok（真机派生件同样不可上云）。"
    )

    lines.append("")
    lines.append("== 覆盖矩阵 ==")
    lines.append(_pad("类型", 10) + _pad("真机", 6) + _pad("夹具", 6) + "合计")
    for row in coverage_matrix(specs):
        lines.append(
            _pad(row.kind, 10)
            + _pad(str(row.real), 6)
            + _pad(str(row.fixture), 6)
            + str(row.total)
        )

    lines.append("")
    lines.append("== 未覆盖类（#106 口径：显式记账，不许用「样本有限」带过）==")
    for item in UNCOVERED:
        lines.append(f"[{item.key}] {item.label}")
        lines.append(f"    为什么单列：{_plain(item.why)}")
        lines.append(f"    怎么补：{_plain(item.how)}")

    lines.append("")
    lines.append("== 旋转页转正对照（#110 A/B/C 归因用）==")
    cases = rotation_cases()
    if not cases:
        lines.append("_（清单里没有旋转页）_")
    for case in cases:
        lines.append(f"{case.page_key}  真实角度 {case.truth}  转正件 {case.upright_key}")
        lines.append(f"    A 组（人工转正后喂，识别层上限）：{case.a_command()}")
        lines.append(f"    B 组（走方向分类自己判）：      {case.b_command()}")
        lines.append(
            f"    C 组（跳过判定，用清单里的正确角）：{case.c_command()}"
        )
    lines.append(
        "跑完 A/B/C 三组之前不要下「某引擎旋转页不行」的结论——归因表见 #110。"
    )
    return "\n".join(lines)


def coverage_summary() -> dict[str, int]:
    """给报告用的一行摘要。"""

    return {
        "samples": len(sample_specs()),
        "real": sum(1 for spec in sample_specs() if spec.source == "real"),
        "fixture": sum(1 for spec in sample_specs() if spec.source == "fixture"),
        "rotation_pages": len(rotation_cases()),
        "uncovered": len(UNCOVERED),
    }
