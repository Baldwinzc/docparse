# 本地 OCR 实测与选型结论（#110，父 #97）

本文是 #97 的**结论部分**：装置（[#108](https://github.com/Baldwinzc/docparse/issues/108)，PR #111）与样本（[#109](https://github.com/Baldwinzc/docparse/issues/109)，PR #112）就位后，在自有 4090 上跑数，回答三问——**第一期用哪个引擎、哪个档位**、**要不要方向分类**、**与 #60 TextIn 云基线比掉了多少**。

- 装置怎么用见 [benchmarks/ocr/README.md](../benchmarks/ocr/README.md)（本目录）。
- 云基线见 [ocr-benchmark.md](ocr-benchmark.md)（#60）；本文与它**同表并列**，但**不重跑云端**——重跑等于把真机再传一次。
- 选型判据见 [local-models-survey.md](local-models-survey.md)（#96 §1.3 / §2.6 / §3.1），本文结论逐条对齐。

> **隐私红线**：真机样本（半岛 / 镇发）是客户真实数据。本次全程**未开 `--allow-cloud-on-real`**，云引擎一次 HTTP 都没发；报告的「云引擎放行留痕」一节为空。

---

## 1. 结论（先看这个）

| 问题 | 结论 |
|---|---|
| **第一期用哪个引擎** | **PaddleOCR PP-OCRv6 `small`**（官方默认档）。 |
| **档位取舍** | `medium` **不留主档**（与 small 在噪音内持平，显存 2.2×）；`tiny` 作最省档备选；**PP-OCRv5 两档淘汰**；RapidOCR 降为**等价退路**（与 Paddle 输出高度一致，但本体走 CPU、且缺整页方向分类）。 |
| **要不要方向分类** | **要**。且用 **PP-LCNet_x1_0_doc_ori**（PaddleOCR 自带）即可；它在 54/54 份样本上判对角度。 |
| **与 #60 掉多少** | 半岛 p1 表头 10 字段 **本地全部 8 档都 10/10，与 TextIn 通用持平**；镇发 p1 输出量与 TextIn 同量级。**没掉。** |

**一句话**：`PP-OCRv6 small` + `doc-ori` 方向分类，就是第一期的本地主路径；RapidOCR 留作装不上 Paddle 系时的退路。

### 1.1 逐条对齐 #96 §1.3 的淘汰判据

| 候选 | #96 §1.3 判据 | 本次实测 | 结论 |
|---|---|---|---|
| PP-OCRv6 `medium` | small 已达标 → medium 只留离线抽检 | 平地 CER 0.0884 vs small 0.0882、字段命中同为 0.9444；显存 851 MB vs 380 MB | **不留主档** |
| PP-OCRv6 `tiny` | 密集表行切分明显劣于 small → 淘汰 | 锚命中/行带数与 small 一致；CER 0.0961 vs 0.0882（差一档） | 留作**最省档备选**（214 MB） |
| PP-OCRv5（mobile/server） | v6 在同批样本不劣于它 → 淘汰 | v6-small 命中 0.9444 ≥ v5-mobile 0.9028 / v5-server 0.9375；CER 也是 v6 更低 | **淘汰**，不留双版本 |
| RapidOCR | 与 Paddle 输出不一致 → 降级 | IoU≥0.5 匹配 **99%** 的框，其中 **97.3% 文本完全相同**（§7） | **等价退路成立** |
| 方向分类模型 | 加方向分类后仍乱码才判识别层 | A 过 / B 过 / C 过（§6） | **方向模型可用，不动 OCR** |

---

## 2. 跑数环境与口径

**机器**（自有远程 4090，非生产机）：

| 项 | 值 |
|---|---|
| 卡 | NVIDIA GeForce RTX 4090 24 GB（**固定用 2 号卡**，`CUDA_VISIBLE_DEVICES=2`） |
| 驱动 | 580.95.05（`nvidia-smi` 报 CUDA 13.0） |
| Python | 3.11.16 |
| paddlepaddle-gpu | 3.3.1（cu126 源） |
| paddleocr / paddlex | 3.7.0 / 3.7.2 |
| rapidocr / onnxruntime | 3.9.2 / 1.30.0（**onnxruntime 是 CPU 版**，见 §8） |
| pymupdf | 1.28.2 |
| 模型来源 | PaddleX 官方模型（首次运行自动下载并缓存）；**跑矩阵时已预热**（每题首次调用含模型加载，不计入表内分位——分位按逐次 `recognize` 计时） |

**样本**：完全按 [#109](https://github.com/Baldwinzc/docparse/issues/109) 的固定清单（`python -m benchmarks.ocr.run samples`），共 **54 份**（真机 40 / 夹具 14）。原件不入库，路径走 `DOCPARSE_OCR_DEMO_DIR`。

**方向处理**：主表一律 `--rotate-mode auto`（挂 `doc-ori`，即建议的生产配置）；`off` 只用于 §6 的 A/B/C 归因对照。

**口径**：字段命中 / CER 用装置 `metrics.normalize`，与 #60 一字未改，保证同表可比。**每引擎一个进程**跑，显存读数只含它自己加载的模型（见 §8）。

> **样本量提醒**：真机平放页 **n=6**、真机旋转页 **n=2**、夹具平放 n=8、夹具旋转 n=6。**样本很少，本表是"能不能用"的判据，不是"普遍可靠"的证明**——未覆盖类见 §9。

---

## 3. 平放页表

### 3.1 夹具·平放（8 份/引擎：base / jpeg60 / noise / lowres × 2 版式）

| 引擎 | n | 平均 CER | 平均字段命中 |
|---|---|---|---|
| PaddleOCR PP-OCRv6 tiny | 8 | 0.0961 | 0.9167 |
| **PaddleOCR PP-OCRv6 small** | 8 | **0.0882** | **0.9444** |
| PaddleOCR PP-OCRv6 medium | 8 | 0.0884 | 0.9444 |
| PaddleOCR PP-OCRv5 mobile | 8 | 0.0992 | 0.9028 |
| PaddleOCR PP-OCRv5 server | 8 | 0.1054 | 0.9375 |
| RapidOCR v6 tiny（CPU） | 8 | 0.0993 | 0.9028 |
| RapidOCR v6 small（CPU） | 8 | 0.0909 | 0.9167 |
| RapidOCR v6 medium（CPU） | 8 | 0.0903 | 0.9306 |

### 3.2 真机·平放页（半岛 p1/p2 + 镇发 p2–p5，n=6/引擎）

| 引擎 | n | P50 ms | P95 ms | 显存峰值 MB | 平均框数 | 平均字符 |
|---|---|---|---|---|---|---|
| PaddleOCR PP-OCRv6 tiny | 6 | 416 | 764 | 214 | 98.3 | 890.7 |
| **PaddleOCR PP-OCRv6 small** | 6 | **571** | **1477** | **380** | 95.8 | 885.7 |
| PaddleOCR PP-OCRv6 medium | 6 | 574 | 1326 | 851 | 98.5 | 891.2 |
| PaddleOCR PP-OCRv5 mobile | 6 | 544 | 1423 | 274 | 98.7 | 880.5 |
| PaddleOCR PP-OCRv5 server | 6 | 720 | 1701 | 1330 | 99.7 | 883.3 |
| RapidOCR v6 tiny（CPU） | 6 | 964 | 1635 | ≈0（见 §8） | 98.2 | 887.8 |
| RapidOCR v6 small（CPU） | 6 | 1830 | 3334 | ≈0（见 §8） | 96.3 | 887.8 |
| RapidOCR v6 medium（CPU） | 6 | 11631 | 26501 | ≈0（见 §8） | 98.8 | 888.0 |

### 3.3 商品行结构（口径有局限，务必连注一起读）

「行数对不对、每行归属哪一件」用 `metrics.goods_row_structure`，锚 = HS 码（`codeTs`）。**此处只报可用的两项**：

| 引擎 | 半岛 p1 锚命中 | p1 识别行带 | 半岛 p2 锚命中 | p2 识别行带 |
|---|---|---|---|---|
| PaddleOCR PP-OCRv6 tiny | 19/19 | 39 | 14/19 | 44 |
| PaddleOCR PP-OCRv6 small | 19/19 | 39 | 14/19 | 42 |
| PaddleOCR PP-OCRv6 medium | 19/19 | 39 | 14/19 | 42 |
| PaddleOCR PP-OCRv5 mobile | 19/19 | 41 | 14/19 | 44 |
| PaddleOCR PP-OCRv5 server | 19/19 | 39 | 14/19 | 43 |
| RapidOCR v6 tiny（CPU） | 19/19 | 39 | 14/19 | 42 |
| RapidOCR v6 small（CPU） | 19/19 | 39 | 14/19 | 42 |
| RapidOCR v6 medium（CPU） | 19/19 | 39 | 14/19 | 42 |

**这张表的三个局限，别当成"行结构全对"**：

1. **参照 19 商品行横跨 p1+p2 两页**，而指标按单页算 → 行带数不能直接和 19 比（p2 是续页，14/19 锚命中是因为部分 HS 码在 p1）。
2. **未指定货表区域**（`--goods-region`），行带数按整页算，含表头/边框行 → 只能当参考值（装置已在报告里标注）。
3. **`归属率` 一项本次不可用**：参照把 `cusOriginCountry` 记成 ISO 码（`GBR`），而 OCR 出的是中文名（`英国`）；`declPrice` 又有尾零差异（`66.83` vs `66.8300`）→ 伴值匹配恒为 0。**这是参照与 OCR 的表示差异，不是识别失败**，但会让「行归属」这一项失真。

> 结论上的处理：本项**只用于佐证"锚没有跨行串行"**（8 个引擎半岛 p1 全部 19/19）。真正的「行结构正确率」要等装置把**货表区域**与**伴值的表示对齐**（ISO 码映射 / 数值化比较）补上——列为 #108 指标口径的 follow-up，不在本 Issue 改（#110「大改回开 #108 的 follow-up」）。

---

## 4. 旋转页表（单列，不混进平放页平均分）

**#103 硬要求**：旋转页单独成表。判定读清单的 `rotation_truth`，不看 key 命名——镇发 **p1 / p6 两页**都是真机内容旋转 90°（#97 盘点时只记了 p1）。

### 4.1 夹具·旋转（6 份/引擎：rot90 / rot180 / rot270 × 2 版式）

| 引擎 | n | 平均 CER | 平均字段命中 |
|---|---|---|---|
| PaddleOCR PP-OCRv6 tiny | 6 | 0.0946 | 0.9444 |
| PaddleOCR PP-OCRv6 small | 6 | 0.0944 | 0.9444 |
| PaddleOCR PP-OCRv6 medium | 6 | 0.0840 | 0.9444 |
| PaddleOCR PP-OCRv5 mobile | 6 | 0.1000 | 0.9444 |
| PaddleOCR PP-OCRv5 server | 6 | 0.1062 | 0.9444 |
| RapidOCR v6 tiny（CPU） | 6 | 0.1010 | 0.8333 |
| RapidOCR v6 small（CPU） | 6 | 0.0897 | 0.8889 |
| RapidOCR v6 medium（CPU） | 6 | 0.0922 | 0.9259 |

（挂了 `doc-ori` 之后，旋转变体的 CER 与平放页同档——方向分类在这一档是**有效**的，对比 §6 的 `off` 行。）

### 4.2 真机·旋转页（镇发 p1/p6，n=2/引擎）

| 引擎 | n | P50 ms | P95 ms | 显存峰值 MB | 平均框数 | 平均字符 |
|---|---|---|---|---|---|---|
| PaddleOCR PP-OCRv6 tiny | 2 | 306 | 383 | 214 | 60.0 | 367.0 |
| **PaddleOCR PP-OCRv6 small** | 2 | **446** | **598** | **380** | 61.0 | 368.5 |
| PaddleOCR PP-OCRv6 medium | 2 | 460 | 583 | 851 | 63.5 | 371.5 |
| PaddleOCR PP-OCRv5 mobile | 2 | 480 | 676 | 278 | 61.5 | 366.0 |
| PaddleOCR PP-OCRv5 server | 2 | 496 | 650 | 1330 | 62.0 | 369.5 |
| RapidOCR v6 tiny（CPU） | 2 | 883 | 1004 | ≈0 | 60.0 | 366.0 |
| RapidOCR v6 small（CPU） | 2 | 1538 | 1814 | ≈0 | 61.0 | 369.5 |
| RapidOCR v6 medium（CPU） | 2 | 10397 | 12808 | ≈0 | 59.5 | 366.5 |

**旋转页能过**——但前提是**挂了方向分类**（§6）。这一点必须说清楚：`off`（不判方向）时 8 个引擎在 p1/p6 上全部**阅读顺序乱掉**。

---

## 5. 与 #60 TextIn 云基线同表并列

**同一批页、同一归一化口径**（`metrics.normalize`，未改）。云端数字读自 [ocr-benchmark.md](ocr-benchmark.md)，**未重跑**。

### 5.1 半岛 p1 表头 10 字段命中

| 引擎 | 命中 | 数据来源 |
|---|---|---|
| TextIn 通用（#60 云基线） | **10/10** | ocr-benchmark.md §3.1 |
| 百度 / 阿里云 / 腾讯云（#60） | 10/10 | 同上 |
| PaddleOCR PP-OCRv6 tiny / small / medium | **10/10** | 本次实测 |
| PaddleOCR PP-OCRv5 mobile / server | **10/10** | 本次实测 |
| RapidOCR v6 tiny / small / medium | **10/10** | 本次实测 |

**8 个本地档位全部 10/10，与云基线持平，没掉。**

### 5.2 镇发 p1（真机内容旋转 90°）输出量

| 引擎 | 输出 | 数据来源 |
|---|---|---|
| TextIn 通用（#60） | 91 行 / 588 字符 | ocr-benchmark.md §3.2 |
| 腾讯云（#60） | 94 行 / 589 字符 | 同上 |
| 百度 / 阿里云（#60） | 24–25 行 / 91–156 字符，**乱码** | 同上 |
| **PaddleOCR PP-OCRv6 small（本次，auto）** | **92 框 / 590 字符** | 本次实测 |
| PaddleOCR PP-OCRv6 tiny / medium（本次） | 90–93 框 / 584–591 字符 | 本次实测 |
| PaddleOCR PP-OCRv5 mobile / server（本次） | 91–92 框 / 583–588 字符 | 本次实测 |
| RapidOCR v6 三档（本次） | 90–91 框 / 585–589 字符 | 本次实测 |

口径提醒：#60 报的是"行级输出行数"，本次报的是"识别框数"，两者近似但不等价；字符数按去换行计。**同量级、无乱码**——local 这条路在 #60 的分水岭页上是站得住的。

---

## 6. 方向分类三组对照（A / B / C，镇发 p1 / p6）

按 #97「归因方法」跑全三组，**8 个引擎结果完全一致**，下表用 `PP-OCRv6 small` 代表（其余档位同结论）。

判定口径：**首行是否是对的方向**（p1 应以「中华人民共和国海关出口货物报关单」开头，p6 应以「东莞镇发电子有限公司出口规范申报要素」开头）。

| 组 | 做法 | 装置开关 | zhenfa-p1 | zhenfa-p6 |
|---|---|---|---|---|
| — | 不判方向，直接喂原件 | `--rotate-mode off`（原件） | ✗ **序乱** 93 框/585 字 | ✗ **序乱** 29 框/145 字 |
| **A** | 人工把图转正再喂（识别层上限） | `off` + 转正件 `zhenfa-p1-rot90` | ✓ 序对 92 框/590 字 | ✓ 序对 30 框/147 字 |
| **B** | 走方向分类自己判（端到端） | `auto` | ✓ 序对 92 框/590 字 | ✓ 序对 30 框/147 字 |
| **C** | 方向分类但角度换成人为正确值 | `force --force-deg 90` | ✓ 序对 92 框/590 字 | ✓ 序对 30 框/147 字 |

**A 过 / B 过 / C 过** → 按 #97 归因表：**方向模型没判错，识别层也没问题**；唯一失败的是"完全不判方向"那一行。A / B / C 三行输出**逐字一致**，说明方向层转正后的裁切与坐标变换也是对的。

**乱码的真相**（这条要写进 #103 的账）：本地引擎在旋转页上**不是认不出字**——字符数与转正后几乎一样（p1 585 vs 590），而是**阅读顺序是转置的**（原件旋转 90°，det 按旋转后的版面自上而下出框）。直接喂给 #62 伪格子 / 规则链就会错位。所以这层**不能省**。

### 6.1 doc-ori 的判定准确率

`PP-LCNet_x1_0_doc_ori`（PaddleOCR 自带）在**全部 54 份样本上判对 54/54**：

| 样本 | 应判角（清单 `rotation_truth`） | doc-ori 判定 |
|---|---|---|
| 镇发 p1 / p6 | 90 | **90** |
| 半岛 p1 / p2 | 0（PDF `/Rotate` 元数据渲染时已转正） | **0**（不误转，关键） |
| 夹具/真机各 rot90 / rot180 / rot270 | 270 / 180 / 90 | **270 / 180 / 90** |

### 6.2 三类方向解的边界（#96 §3.1，本次实测落到具体）

| 解 | 适用 | 本次实测 |
|---|---|---|
| ① 引擎自带 doc_ori | 首选 | **PaddleOCR 有**（`DocImgOrientationClassification`），54/54 判对 → 第一期用它 |
| ② 独立方向模型 | 换来源时的补丁 | **RapidOCR 官方没有 doc_ori**（#96 §3.4 已核实）；要用必须另挂 ①，本装置已支持 |
| ③ 页面 rotation 元数据 | PDF 自带 | **半岛两页就是这种**：`pymupdf` 渲染时已转正，`doc-ori` 判 0，**不是内容旋转**——与镇发那种（真·内容旋转 90°）分开说，#103 要求 |

> `--ori-invert`（把 90/270 对调）本次**没触发**：C 组用清单的正确角（90）一把过，方向没搞反。

---

## 7. RapidOCR vs PaddleOCR 输出一致性

#96 §1.2 要求**实测确认**、不许推理宣称。同一批平放样本（22 份/对），逐框按 IoU≥0.5 匹配后比文本：

| 对比 | 样本 | Paddle 框 | Rapid 框 | IoU≥0.5 匹配 | 其中文本相同 |
|---|---|---|---|---|---|
| v6-tiny | 22 | 1832 | 1818 | 1801（**98.3%**） | 1719（**95.4%**） |
| v6-small | 22 | 1798 | 1796 | 1785（**99.3%**） | 1737（**97.3%**） |
| v6-medium | 22 | 1826 | 1829 | 1790（**98.0%**） | 1746（**97.5%**） |

**bbox 与行切分对得上（99% 的框能匹配），其中 97% 文本逐字相同**——尾部差异集中在极小的字块与标点上。**RapidOCR 可作 PaddleOCR 的等价退路**（装不上 Paddle 系依赖时用），但**它本体走 CPU**（见 §8），吞吐不是一个量级。

---

## 8. 显存 / 时延怎么读（这不是 SLA）

- **这是单机单卡单批样本的实测，不是生产 SLA**。并发 / 吞吐 / 采购换算交 [#98](https://github.com/Baldwinzc/docparse/issues/98)。
- **时延含装置口径的固定开销**：每张图之间固定等 1.2s（`run.py` 的 `CALL_INTERVAL_SECONDS`，为和云端串行口径一致），真实吞吐要把这 1.2s 扣掉。
- **显存来自 `paddle.device.cuda.max_memory_allocated()`（只算本进程）**。**每引擎一个进程**跑，读数不含别的引擎残留的模型。
- **RapidOCR 的显存 ≈ 0**：本装置里它走 **onnxruntime CPU**（`onnxruntime` 是 CPU 版），不在卡上。表里 @auto 行出现的几 MB 是 `doc-ori` 方向模型的占用，不是 RapidOCR 本体。它的时延（P50 0.9–11.6 s/页）因此是 **CPU 口径**，与 GPU 上的 Paddle 不可直接比。
- Paddle 三档的显存峰值集中在 **214 / 380 / 851 MB**（tiny / small / medium），24 GB 卡上余量充足。

---

## 9. 未覆盖类（#109 口径，不许用「样本有限」一句带过）

以下三类**当前没有来源**，本次结论**不外推到它们**：

| 未覆盖类 | 为什么 | 怎么补 |
|---|---|---|
| 不同来源的密集商品表 | 只有半岛 19 商品行一份；密集表是行切分/列归属的主战场 | 追加真机测试件（原件不入库，登记进 `samples.py` 的 `REAL_ORIGINALS`） |
| 拍照件（手机翻拍，非平板扫描） | 透视畸变 / 光照不均 / 边缘阴影是**独立的失败模式** | 手机翻拍 1–2 份（可脱敏），按 `cloud_ok=False` 登记 |
| 真机横放件的更多实例 | 真机横放件只有镇发 p1 / p6 **两页**；派生页过 ≠ 真机横放件过 | 再找横放扫描的真机件；在此之前 p1/p6 的结论**按两页样本读** |

**这对结论可信度的影响**：本结论足以判"能不能用"（#96 §1.1 的硬门槛都过了），但**不足以证明"普遍可靠"**——样本量见 §2 的提醒。

---

## 10. 回头的条件

若传统 OCR + 规则在**密集商品表**上过不去（表现为：行切分崩溃、列归属串行、伪格子还原不出表），按 [local-models-survey.md](local-models-survey.md) §2.6 的表**从上到下**回头试轻量 OCR-VLM——顺序是 GLM-OCR / PaddleOCR-VL-1.6（同为 0.9B，都有官方中文/表格口径）→ granite-docling（唯一给到含内容 TEDS，但中文实验性）→ Surya 2（一个模型做三件事，但权重许可要先过法务）。

**触发条件写死**：只有出现"密集表行结构正确率明显低于字段命中率"（即字都认得出、行就是拼不回来）时才触发；字段命中本身就是 low 的，属于识别层问题，先换 OCR 档位，别跳 VLM。

---

## 11. 复现

在跑数机器（GPU、已装 `.[local-ocr]`）的仓库根目录：

```bash
export DOCPARSE_OCR_DEMO_DIR=/path/to/既有真机样本目录
export CUDA_VISIBLE_DEVICES=2                 # 固定单卡，显存读数才干净
export OCR_BENCH_FONT=/path/to/CJK.ttf        # 夹具渲染要中文字体

python -m benchmarks.ocr.run samples          # 样本清单：几份 / 能否外呼 / 真实角度
python -m benchmarks.ocr.run real-render --derived
python -m benchmarks.ocr.run local-list --probe

# 全矩阵：每个引擎一个进程（显存干净），off 与 auto 各一轮
for E in local:paddle-v6-tiny local:paddle-v6-small local:paddle-v6-medium \
         local:paddle-v5-mobile local:paddle-v5-server \
         local:rapidocr-v6-tiny local:rapidocr-v6-small local:rapidocr-v6-medium; do
  python -m benchmarks.ocr.run call --engine "$E" --scope all --rotate-mode off
  python -m benchmarks.ocr.run call --engine "$E" --scope all --rotate-mode auto
done

# C 组：force 90（镇发 p1/p6 的 rotation_truth）
for E in local:paddle-v6-small; do
  python -m benchmarks.ocr.run call --engine "$E" --scope real \
      --rotate-mode force --force-deg 90 --sample zhenfa-p1 --sample zhenfa-p6
done

python -m benchmarks.ocr.run report            # → out/report.md
```

A 组复用第一轮 `off` 结果里的转正件（`out/results/<引擎>/zhenfa-p1-rot90.json`），不用另跑。产物在 `benchmarks/ocr/out/`，**全部不入库**。

---

## 12. 跑数暴露的装置缺陷（已修，随本 PR #110）

跑这台机器时撞上 5 处装置缺陷，都是**小改**（#110 允许回改 `benchmarks/ocr/`）：

| 现象 | 根因 | 修在哪 |
|---|---|---|
| `local:rapidocr-*` 全部 `TypeError: The value of Det.model_type must be Enum Type.` | RapidOCR 3.9 起枚举项要传 `Enum` 实例，档位表给的是字符串 | `local_engines.rapidocr_params`：懒解析成 `ModelType`/`OCRVersion` 等 |
| RapidOCR 在空白页抛「未能解析出文本行」 | 空白页返回 `txts=None`（属性在、值为 None），被当成结构变化 | `parse_rapidocr_result`：属性存在但为 None/空 → 返回空列表 |
| 显存峰值取不到，退回 `nvidia-smi` 并**报了别的卡**（43 GB） | Paddle 3.3 没有 `reset_peak_memory_allocated`（叫 `reset_max_memory_allocated`）；`nvidia-smi` 退路取全机最大值 | `reset_paddle_peak`（多个别名逐个试）+ `visible_gpu_id`（按 `CUDA_VISIBLE_DEVICES` 只读那张卡） |
| 只装 `rapidocr` 起不来 | `rapidocr` 不声明推理后端 | `pyproject.toml` 的 `local-ocr` extra 加 `onnxruntime>=1.17` |
| 夹具渲染报「未找到中文字体」 | 评测机没有中文字体 | 不修代码：文档写明设 `OCR_BENCH_FONT`（README「安装」一节） |

配套单测：`tests/test_local_ocr_benchmark.py` 新增 `TestRapidParams` / `TestVramHelpers` 与空白页用例，**本机不装 paddleocr / rapidocr 也能跑**。

---

## 13. 以后新引擎 / 新样本 / 新指标往哪加

**与 #108 的表合并成一处**，不放两份——见 [benchmarks/ocr/README.md](../benchmarks/ocr/README.md) 末尾的「以后新引擎 / 新样本 / 新指标改哪」表。加档位、加派生、换显存采样方式、加指标各改哪、动不动 Python，都在那张表里。本文只加一条**本文特有的**：

| 场景 | 改哪 | 动不动 Python |
|---|---|---|
| 结论要更新（重跑后改本期选型） | 本文 §1 结论表 + §3–§7 的数字 | 否 |
| 新增一个"未覆盖类"要补上 | `samples.py` 的 `UNCOVERED` 去掉该条 + 登记新样本；本文 §9 同步 | 否 |
