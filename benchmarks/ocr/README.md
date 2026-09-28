# OCR 引擎实测装置（云对照 + 本地评测台）

对应 Issue：[#60](https://github.com/Baldwinzc/docparse/issues/60)（云基线）→ [#108](https://github.com/Baldwinzc/docparse/issues/108)（本地评测装置，#97 拆 1/3）→ [#109](https://github.com/Baldwinzc/docparse/issues/109)（固定样本清单，#97 拆 2/3）。

云部分成稿时 CLAUDE.md 还是「只走云 API」约束，脚本按那个口径写；本地化（#94）之后本目录扩成**「本地可选 + 云端对照」**：同一批样本、同一套指标，本地引擎与 #60 的云基线**同表并列**（#97 要的正是这个）。

约束口径见 [CLAUDE.md](../../CLAUDE.md)。本地引擎的选型结论在 [#110](https://github.com/Baldwinzc/docparse/issues/110) 产出，本 README 只管**装置怎么用**。

> ⚠️ **隐私红线**：`AI识别Demo` / `补充测试` 下是客户真实数据，**不得上传任何云端**。装置里做成了默认硬闸（见「隐私闸」一节），不是靠人自觉。

## 结构

| 文件 | 作用 |
|---|---|
| `samples.py` | **样本清单**（#109）：一共几份、哪份能上云、哪页带参照、**旋转页的真实角度**、未覆盖类。原件路径 / 派生 / 取图都从这里出，`run.py` 与 `real.py` 都不再自己硬编码 |
| `fixtures.py` | 程序渲染仿真出口报关单（GT 精确已知），派生 base / rot90 / rot180 / rot270 / jpeg60 / noise / lowres 七种变体（变体表 `FIXTURE_VARIANTS` 对外暴露，供清单登记） |
| `engines.py` | 五个云引擎适配器（TextIn 通用、TextIn 报关单、百度、阿里云、腾讯云），纯 httpx + 标准库签名；云引擎带 `is_cloud = True` |
| `local_engines.py` | **本地引擎**：PaddleOCR PP-OCRv6/v5 各档、RapidOCR、整页方向分类 `doc-ori`、方向处理层 `RotatingEngine`、显存采样 `VramSampler`。重依赖懒 import |
| `metrics.py` | 归一化、CER、字段命中、**商品行结构正确率**、**时延 P50/P95** |
| `real.py` | 真机 PDF 逐页出图 + 参照 JSON 读取。**渲染哪份读 `samples.py` 的清单**，路径走 `DOCPARSE_OCR_DEMO_DIR`，原件不入仓库 |
| `visualize.py` | 识别框画回原图（`out/viz/`），供人工验收 |
| `run.py` | 编排 CLI |
| `gt_field_map.py` | 夹具 GT 字段名 → TextIn 报关单 API 字段名 |

`out/` 全部产物不入库（图片、原始返回、指标 JSON）。

## 安装

```bash
pip install -e ".[dev]"         # 跑单测 / 只看云引擎，够用
pip install -e ".[local-ocr]"   # 跑本地引擎（paddleocr / rapidocr，重依赖）
```

**GPU 机器**：PyPI 上没有 `paddlepaddle-gpu` 轮子，先按 Paddle 官方装 GPU 版，再装 `local-ocr` extra：

```bash
python -m pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
pip install -e ".[local-ocr]"
```

装完先验一遍（本机的模型名 / 返回结构未必和官方文档一字不差，probe 就是用来早点撞上这件事的）：

```bash
python -m benchmarks.ocr.run local-list            # 静态清单 + 缺哪个依赖、装哪条命令
python -m benchmarks.ocr.run local-list --probe    # 再真构造一次 + 白底小图跑一遍
```

## 运行

```bash
python -m benchmarks.ocr.run samples           # 样本清单：几份 / 能否外呼 / 真实角度
python -m benchmarks.ocr.run fixtures          # 夹具 + GT → out/
python -m benchmarks.ocr.run real-render       # 真机原件页 → out/real/
python -m benchmarks.ocr.run real-render --derived   # 连派生件一起 → out/real-derived/
python -m benchmarks.ocr.run call --engine cloud --scope fixtures
python -m benchmarks.ocr.run call --engine local --scope fixtures
python -m benchmarks.ocr.run call --engine local:paddle-v6-small --scope fixtures
python -m benchmarks.ocr.run report            # 汇总 → out/report.md
```

`--engine` 取值：`cloud`（五朵云）/ `local`（全部本地 OCR 档位）/ `all`（两者）/ 逗号分隔的具体引擎名（`textin-general`、`local:paddle-v6-medium`、…）。

### 样本清单（#109）

**别去翻 `fixtures.py` / `real.py` 数样本**——一共几份、哪页能不能上云、旋转页的转正角是多少，一条命令看全：

```bash
python -m benchmarks.ocr.run samples          # 清单 + 覆盖矩阵 + 未覆盖类 + A/B/C 命令
python -m benchmarks.ocr.run samples --json   # 再落一份 out/samples.json，供脚本读
```

清单在 `samples.py`：**原件登记一次，派生件自动展开**，`run.py` 取样本、`real.py` 渲染、报告分旋转页都读它。

| | 真机 | 夹具 |
|---|---|---|
| 原件 | 半岛 2 页 + 镇发 6 页 = **8 页**（客户件，原件不入库，路径走 `DOCPARSE_OCR_DEMO_DIR`） | 2 个版式 |
| 派生 | 每页 rot90 / rot180 / rot270 / lowres | 每页 7 档（多 jpeg60 / noise） |
| 样本数 | 40 | 14 |
| 能否上云 | **不能**（`cloud_ok=False`，**派生件继承原件**） | 能 |
| 参照 | 半岛：表头 10 字段 + 19 商品行；镇发：无 | 夹具 GT |

**真机旋转页有 2 页，不是 1 页**：镇发 p1（出口货物报关单）与 **p6（出口规范申报要素）**，都是内容旋转 90°。#97 盘点时只记了 p1，逐页核过实物后 p6 同样是旋转页，两页都按分水岭看待（#103）。半岛两页是 PDF `/Rotate=270` **元数据**、渲染时已转正，**不是内容旋转**——这两者要分开说。

#### 「真实角度」是什么，不是什么

清单里的 `rotation_truth` **不是**「内容转了多少度」这种口语，而是：

> **把这份图转正所需的逆时针角度 = C 组要敲的 `--force-deg`**；`0` = 已正立。

它与派生件的名字互为补角，**别看名字推角度**：

| 样本 | 名字里的角 | 真实角度（= `--force-deg`） |
|---|---|---|
| 夹具 `a-rot90` | 施加 90° | **270** |
| 夹具 `a-rot270` | 施加 270° | **90** |
| 真机 `zhenfa-p1` | —（名字里没有角） | **90** |
| `zhenfa-p1-rot90`（A 组要喂的转正图） | 施加 90° | **0**（已正立） |

搞混这两个，#110 的 A / C 组就会敲错角度、归因实验不可复现。

旋转页单列（#103）也由它驱动：`rotation_truth != 0` 的进旋转表，**不再靠 key 里的 `rotXX` 字符串猜**——那样既会漏掉镇发 p1（名字里没有角），也会把 `zhenfa-p1-rot90` 这种正立的转正件误判成旋转页。

#### 未覆盖类（#106 口径）

「不同来源的密集商品表」「拍照件」「真机横放件的更多实例」三类**当前没有来源**，按 #106 的要求**显式记账**（`samples.py` 的 `UNCOVERED`，`samples` 命令会打出来），**不许用「样本有限」一句带过**；补它的条件写在每条条目里，#110 的结论直接引用它。

#### `--scope` 与 `--sample`

| `--scope` | 跑哪些 |
|---|---|
| `fixtures` | 夹具 14 份 |
| `real` | 真机原件页 8 张（半岛 2 + 镇发 6） |
| `real-derived` | 真机派生件 32 张 |
| `all`（默认） | 三者之和 |

`--sample` 按 key 通配（fnmatch、可重复，如 `--sample 'zhenfa-p*'`）。**不带通配符就是精确匹配**：`--sample zhenfa-p1` 不会把 `zhenfa-p1-rot90` 一起带上。

### 本地引擎清单

| 引擎名 | 说明 |
|---|---|
| `local:paddle-v6-tiny` / `-small` / `-medium` | PaddleOCR PP-OCRv6 三档（small 是官方默认档） |
| `local:paddle-v5-mobile` / `-server` | PaddleOCR PP-OCRv5 旧基线两档 |
| `local:rapidocr-v6-tiny` / `-small` / `-medium` | 同一批 Paddle 权重转 ONNX，**不装 PaddlePaddle**；装不上 Paddle 系时的等价退路 |
| `local:doc-ori` | PP-LCNet_x1_0_doc_ori 整页方向分类（0/90/180/270）。**不是 OCR 引擎**，只出判定角度，用 `--rotate-mode auto` 挂它 |

引擎名与档位取自 [docs/local-models-survey.md](../../docs/local-models-survey.md) 已核对的官方口径。

## 方向处理与 A/B/C 三组（#97 归因方法）

镇发 p1 / p6（内容旋转 90°）是选型分水岭（#103）。**旋转页出现乱码不能直接判定「识别模型不行」**——角度判错、方向搞反、裁切、坐标变换都会产生同样的乱码。所以装置把三组做成了开关：

| 组 | 语义 | 装置开关 |
|---|---|---|
| **A** | 不走方向分类，人工把图转到正确角度再喂 OCR（识别层能力上限） | `--rotate-mode off` + **清单里的转正件**（`zhenfa-p1-rot90` 这种，`真实角度` 是 0） |
| **B** | 走方向分类，让它自己判（端到端真实表现） | `--rotate-mode auto` |
| **C** | 走方向分类但把判定角度换成人为指定的正确值（只隔离「方向模型判错」） | `--rotate-mode force --force-deg <该页真实角度>` |

**要敲几不用猜**：`python -m benchmarks.ocr.run samples` 里每页一个 `真实角度`，`samples` 命令直接把三组命令按页打出来（把 `ENGINE` 换成引擎名即可）。以镇发 p1 为例：

```bash
# A 组：喂转正件（zhenfa-p1-rot90 的 真实角度 = 0），不走方向分类
python -m benchmarks.ocr.run call --engine local:paddle-v6-small \
    --scope real-derived --rotate-mode off --sample zhenfa-p1-rot90

# B 组：喂原件页，让它自己判
python -m benchmarks.ocr.run call --engine local:paddle-v6-small \
    --scope real --rotate-mode auto --sample zhenfa-p1

# C 组：跳过判定，用清单里的正确角（p1 是 90）
python -m benchmarks.ocr.run call --engine local:paddle-v6-small \
    --scope real --rotate-mode force --force-deg 90 --sample zhenfa-p1
```

三种模式的产物落在**不同目录**（引擎名带 `@auto` / `@force90` 后缀），互不覆盖。

**方向约定**：`--force-deg DEG` 是把图按**逆时针**转 `DEG` 度后喂 OCR（即 `PIL.Image.rotate(DEG)`），与清单里的 `真实角度`、`fixtures.py` 的 rot90/rot180/rot270 同一个函数。所以「转正件」就是按该页的 `真实角度` 再转一次得到的那份：`zhenfa-p1`（90）→ `zhenfa-p1-rot90`（0）。

> 想验证清单给的角是不是反的，可以手动喂 `--force-deg 270` 对比；但**清单里的数就是实测正确角**，归因实验按它跑才可复现。

`--ori-invert` 把方向分类的 90/270 对调——「方向搞反」是 #97 列明的失败来源之一，用开关试，不靠猜。

> **跑完 A/B/C 三组之前，不要写「某引擎在旋转页不行」的结论。** 归因表见 [#110](https://github.com/Baldwinzc/docparse/issues/110)。

## 指标

| 指标 | 怎么算 |
|---|---|
| 字段命中率 / CER | 沿用 #60 口径（`metrics.normalize` 未改），保证与云基线同表可比 |
| **商品行结构正确率** | `metrics.goods_row_structure`：① 行数对不对（识别行带数 / 参照行数）；② 每行归属哪一件（锚 = HS 码，与单价 / 原产国是否落在**同一行带**）；③ **行被并**单独计数——#60 §4.3 那种「19 行并成 2–3 行」只看归属率会漏掉 |
| **时延 P50 / P95** | 逐页记录后算分位，报告里同时给样本数 n。只报均值会被长尾掩盖 |
| **显存峰值** | 见下 |

### 显存怎么读

PP-OCRv6 官方**没有**显存表（#96 已核实），只能自测。`VramSampler` 的取值优先级：

1. `paddle.device.cuda.max_memory_allocated()`——**只算本进程**，最准；
2. 退到 `nvidia-smi --query-gpu=memory.used` 轮询（0.2s 一次）——**整卡口径，含同卡其他进程**，结果里会写明；
3. 两个都没有（本机 Mac、无卡机器）→ 记 `-`，note 写「读不到」。

**读不到就写读不到，不拿社区数字顶替。**

### 旋转页单列

`out/report.md` 默认**分两张表**：平放页汇总、旋转页单列（#103：旋转页结论不得混进平均分）。判定读清单的 `真实角度`（`rotation_truth != 0`），**不看 key 怎么起名**——镇发 p1 / p6 名字里没有 `rotXX`（按名字猜会漏），而 `zhenfa-p1-rot90` 名字里有 `rot90` 却是**正立**的（按名字猜会误判）。所以 `call --scope real` 直接跑就会把 p1 / p6 归到旋转表，不用再手动点名；`--rotation-key` 只剩手动兜底的用途。

报告最后还有一节「云引擎放行留痕」，列出真机样本上被放行过的云引擎调用。

## 隐私闸（真机不外呼）

真机样本（半岛 / 镇发）是客户真实数据，**云引擎默认一次 HTTP 都不发**：

| 样本档 | 判定 | 允许的引擎 |
|---|---|---|
| `synthetic` | `fixtures.py` 程序渲染的夹具及派生 | 本地引擎 + 云引擎 |
| `real` | 真机页（半岛 / 镇发 / 将来的补充测试） | **只允许本地引擎** |

被拦时会打印原因并把该页跳过。唯一放行开关是 `--allow-cloud-on-real`，用了会在 `out/results` 与该页结果里留痕（`cloud_override: true`），并出现在报告的「云引擎放行留痕」一节。

**#60 的云基线数字是当时跑的**——不要为了「同表并列」重跑云端，重跑就等于把真机再传一次。

## 密钥环境变量（不写入仓库）

| 引擎 | 变量 |
|---|---|
| TextIn（两接口同钥） | `TEXTIN_APP_ID`、`TEXTIN_SECRET_CODE` |
| 百度 | `BAIDU_OCR_API_KEY`、`BAIDU_OCR_SECRET_KEY` |
| 阿里云 | `ALIBABA_CLOUD_ACCESS_KEY_ID`、`ALIBABA_CLOUD_ACCESS_KEY_SECRET` |
| 腾讯云 | `TENCENT_SECRET_ID`、`TENCENT_SECRET_KEY` |
| 真机样本目录 | `DOCPARSE_OCR_DEMO_DIR`（默认 `../AI识别Demo`） |
| 指定中文字体 | `OCR_BENCH_FONT`（ttf/ttc 路径，默认自动探测系统字体） |

## 调用量与费用口径（云引擎，写死在免费额度内）

夹具 2 页 × 7 变体 = 14 张，真机 8 页原件 + 32 张派生件 = 40 张（清单口径见 `run samples`），单引擎一轮 ≤ 54 次。**真机一律被隐私闸拦住，云引擎实际只跑夹具那 14 张**——费用按这个上限估。

| 引擎 | 免费额度 | 出处 |
|---|---|---|
| TextIn 通用 | 新客 50 页 | [产品页](https://www.textin.com/market/detail/recognize-document-3d1-multipage) |
| TextIn 报关单 | 新客 100 页 | [产品页](https://www.textin.com/market/detail/customs_declaration) |
| 百度标准版 | 每月免费额度 | [价格页](https://cloud.baidu.com/product-price/ocr.html) |
| 阿里云 | 有免费额度（登录控制台确认） | [按量付费](https://help.aliyun.com/zh/ocr/product-overview/pay-as-you-go) |
| 腾讯云 | 1000 次/月 | [计费概述](https://cloud.tencent.com/document/product/866/17619) |

引擎间串行 + 每次调用间隔 1.2s，避免触发 QPS 限制。本地引擎同样串行，间隔对本地跑是额外开销，但它换来的是「同一批样本同一条流水线」，先保持一致。

## 以后新引擎 / 新样本 / 新指标改哪

| 场景 | 改哪 | 动不动 Python |
|---|---|---|
| 加一个 PaddleOCR 档位（如 v7 tiny） | `local_engines.py` 的 `PADDLE_TIERS` 加一行 | 否（改数据） |
| 加一个 RapidOCR 档位 | `local_engines.py` 的 `RAPID_TIERS` 加一行 | 否（改数据） |
| 加一个非 Paddle 系本地引擎（docTR 等） | `local_engines.py` 加一个类 + 一个解析函数 | 是（一个类） |
| 换本地引擎的返回结构适配 | `local_engines.py` 的 `parse_*_result` 一处 | 是 |
| 加一个新指标 | `metrics.py` 加纯函数 + `run.py` 的报告加一列 | 是 |
| **加一份新真机 PDF / 图片** | `samples.py` 的 `REAL_ORIGINALS` 加一条 `Original`（含它的 `PageOrigin`：页号 / `truth` / 说明），原件放进 `DOCPARSE_OCR_DEMO_DIR`（**不入库**） | **否**（只有渲染器不认的新格式才要动 `real.py`） |
| **加一类派生变体** | `fixtures.py` 的 `FIXTURE_VARIANTS` 加一行 + `apply_variant` 加一个分支 + `samples.py` 的 `DERIVATIONS` 加元数据、`REAL_DERIVATIONS` 决定真机要不要 | 是（一处实现 + 两行数据） |
| **改参照（表头字段 / 商品行）** | `samples.py` 里该原件的 `reference` 指向 + `real.py` 的参照解析函数 | 否（换已有参照改数据；新一类参照才加函数） |
| **标一个新的旋转真机页** | `samples.py` 里该 `PageOrigin` 的 `truth` 填转正角；派生件与 A/B/C 命令自动跟着变 | **否** |
| **补一个「未覆盖类」**（#106 口径） | `samples.py` 的 `UNCOVERED` 加一条（说明为什么单列 + 怎么补） | 否 |
| 换显存采样方式 | `local_engines.py` 的 `VramSampler` 一处 | 是 |
| 换 / 加云引擎 | `engines.py` 加一个类（沿用 #60 做法），`ALL_ENGINES` 注册 | 是（一个类 + 一个解析函数） |
| 夹具换版式 / 字段 | `fixtures.py` 的 `FixtureSpec` | 否（改数据即可） |
| GT 字段与 TextIn 字段对照 | `gt_field_map.py` | 否 |
| 指标口径（归一化规则） | `metrics.py` 的 `normalize`——**改了就不能再和 #60 直接比** | 是（一处，慎重） |
