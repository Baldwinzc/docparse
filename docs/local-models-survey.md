# 本地引擎选型复核：OCR / 整页方向分类 / 版面分析 / 本地 LLM

对应 Issue：[#96](https://github.com/Baldwinzc/docparse/issues/96)（父 Epic [#94](https://github.com/Baldwinzc/docparse/issues/94) 数据不出网）；[#106](https://github.com/Baldwinzc/docparse/issues/106) 二次复核补课

**核对日期：2026-09-26；2026-09-27 按 [#106](https://github.com/Baldwinzc/docparse/issues/106) 二次复核。** 下表的体积 / 显存 / 精度 / 许可证都在核对日打开官方页面或官方仓库读到原文；价格与版本会动，实现前再点一次 §7 的链接。

> **#106 二次复核补了什么**：① 补 2026 上半年的轻量端到端 OCR-VLM（GLM-OCR / Surya 2 / LightOnOCR-2-1B / DeepSeek-OCR 2 / granite-docling / PaddleOCR-VL-1.6）；② **§4 扩成「结构解析：版面分析 + 表格结构识别」**，新增版面分析（PP-DocLayoutV2/V3）与第三方表格结构对照；③ MinerU 在 §1.4 留痕；④ **修掉两处过强推断**（§1.3 方向分类的淘汰判据、§2.1 的跨代比较）与 §2.4 Tesseract 的简化描述。
> **二次复核否掉的两条外部说法**（证据见 [#106](https://github.com/Baldwinzc/docparse/issues/106)）：MinerU **不是 AGPL-3.0**，是 Apache-2.0 + 附加条款；DeepSeek-OCR 2 **不是 MIT**，是 Apache-2.0。与官方原文冲突的说法，本文件一律以官方原文为准 —— 这正是「读到原文才算已核对」这条约定的用处。

> **阅读约定（沿用 [ocr-survey.md](ocr-survey.md)）**
>
> - 每条数字旁边都有官方链接。
> - **已核对**：本环境读到了官方页面 / 仓库 / 模型仓的原文或文件列表，数字是原文数字。
> - **待打开核对**：只看到检索口径或二手转述，没读到原文，实现前必须点开。
> - **官方未给**：官方文档根本没写这一项。不用社区数字顶替，不写「大约」。
> - 单位不混：**权重体积**是模型文件大小（MB），**显存**是产线峰值 VRAM，两者不是一回事；原表里没有的一律写清楚来源。

## 0. 这份文件和前两份的关系（先看这个）

| 文档 | 写什么 | 现在的地位 |
|---|---|---|
| [model-survey.md](model-survey.md)（#1） | 云解析链路分层（垂直单据 / 按页解析 / LLM） | **历史对照**，成稿于「只走云 API」时期 |
| [ocr-survey.md](ocr-survey.md)（#7） | 云 + 开源 OCR 泛览（参数量 / 显存 vs 价格） | **历史对照**；它的开源数字是本文的起点，但版本已推进（见 §2.1） |
| [ocr-benchmark.md](ocr-benchmark.md)（#60） | 四个云引擎实测 | **云基线**，#97 的本地引擎要与它同表并列 |
| **本文**（#96 / #106） | 本地跑什么：候选池 + 判据 + 落点 | 供 #97 评测、#99 接入、#100 开关、#101 LLM 引用 |

**本文不做选型定论。** 模型值不值得推荐要看 #97 在真机样本上的实测效果，不能凭厂商介绍页下结论。本文只回答三件事：

1. 哪些候选值得进 #97 的首轮（以及各自测什么档位）；
2. 每个候选**什么情况下直接淘汰**；
3. 必须过的分水岭是什么（旋转页，见 §3 与 #103）。

约束口径以 [CLAUDE.md](../CLAUDE.md)「已对齐的产品约束」为唯一出处：**本地优先，云端默认关，显式配置才外呼**。第一期仍是 **OCR + 规则，VLM 非必须**（[#11](https://github.com/Baldwinzc/docparse/issues/11) 已冻结）；本文的 VLM 候选只作对照，不进第一期主路径。

---

## 1. 结论：进 #97 首轮测什么、什么情况直接淘汰

### 1.1 硬门槛（不过就淘汰，不参与平均分）

| 门槛 | 依据 | 说明 |
|---|---|---|
| **真·内容旋转页（镇发 HKG25003373MUC p1，内容旋转 90°）不能乱码** | [#103](https://github.com/Baldwinzc/docparse/issues/103) | #60 选 TextIn 的决定性理由就是这一页；百度 / 阿里云在这一页直接乱码。旋转页与平放页**分开呈现**，不得混进平均分 |
| **半岛 SJ25084373 表头字段命中不下降** | #60 基线（10 字段）、#23 口径 | 毛重 1459.62 / 净重 485 / 件数 214 / 备案号 T5352W000228 / 境外发货人 Peninsula Merchandising Limited |
| **商品表行结构正确** | #60 §3.3（参照 19 商品行） | 行切分错则 #62 伪格子与规则链一起崩，字段再准也没用 |
| **许可证允许商用** | 本文 §2、§3、§4、§5、§6 | 权重受限的（如 Surya）在表里标红，不进首轮 |

### 1.2 进 #97 首轮的候选

**OCR 主链（det + rec）**

| 候选 | 档位 | 为什么进首轮 |
|---|---|---|
| **PaddleOCR PP-OCRv6** | `small` 为默认档，`medium` 作精度上限对照，`tiny` 作最省档对照 | 最新一代，官方给了参数量、体积、50 语言、**含「表格」场景的检测指标**；端到端速度官方表里全线有数。三档一起测才能回答「小模型够不够」 |
| **PaddleOCR PP-OCRv5** | `server` / `mobile` | 旧基线。v6 官方称 medium 比 v5_server 识别精度 +5.1%、检测 +4.6%、GPU 快 2.37×，**这句要有实测背书才作数** |
| **RapidOCR** | ONNX，默认 PP-OCRv6（tiny / small / medium） | 同一批 Paddle 权重转 ONNX，**不装 PaddlePaddle**。若 #99 现场装不上 Paddle 系依赖，这是等价退路；必须实测确认它与 PaddleOCR 原版结果一致 |
| **云基线 TextIn 通用** | `recognize/multipage`，`straighten=1` | 只作并列对照（#60 表升级为主路径前的最后一行）；默认关，不外呼 |

**整页方向分类（独立一项，#103）**

| 候选 | 为什么进首轮 |
|---|---|
| **PP-LCNet_x1_0_doc_ori** | 官方四类 0/90/180/270，7 MB，Top-1 99.06%——备选里官方口径最明确的一个（RapidOCR 官方清单里没有，见 §3.4） |
| **PP-LCNet_x0_25_textline_ori / x1_0** | 文本行级 0/180 纠正，行内竖排 / 倒置用；与上一项叠加，不是二选一 |

**本地 LLM 服务端（供 #101）**

| 候选 | 为什么进首轮 |
|---|---|
| **vLLM** | 内网 OpenAI 兼容端点的事实标准，`/v1/chat/completions` 与现有 `OpenAICompatClient` 对齐 |
| **Ollama** | 装机最轻，OpenAI 兼容子集含 `/v1/chat/completions`；作「不想起 GPU 服务」的退路 |

**不在首轮、但要盯着的（2026 上半年新一档）：** GLM-OCR、Surya 2、LightOnOCR-2-1B 这一批轻量端到端 OCR-VLM，体量已经压到 **0.65–1B**，与 PaddleOCR-VL 同档，中文与表格都在官方口径里（§2.6 有核过的数字）。它们**仍是 VLM**，按 #11 冻结的「第一期 OCR + 规则」只作对照；但这一档体积已经落到「单卡甚至 CPU 能跑」的区间，**如果 #97 证明传统 OCR + 规则在密集表上过不去，第一个回头的就是它们**——所以现在就要有官方数字备着，而不是到时候从头查。

### 1.3 各候选的淘汰判据

| 候选 | 什么情况直接淘汰 |
|---|---|
| PP-OCRv6 `medium` | 24GB 卡上单页显存或时延过不了 #98 的并发档，且 `small` 已达标 → medium 只留作离线抽检 |
| PP-OCRv6 `tiny` | 密集商品表行切分明显劣于 `small`（官方表格场景分 tiny 94.7 vs small 95.6，差距小，必须实测确认） |
| PP-OCRv5 | v6 在**同样样本**上不劣于它 → 直接淘汰，不留双版本 |
| RapidOCR | 与 PaddleOCR 输出不一致（bbox 或行切分对不上），或补不上整页方向分类（§3.4 已核实它官方没有 doc_ori） → 降级为「只在装不上 Paddle 时用」 |
| 方向分类模型 | 只在镇发 p1 上验证。**若加了方向分类后旋转页仍乱码，不能直接判定「识别模型不行」**——角度判错、旋转方向搞反、裁切、坐标变换都会产生同样的乱码。必须先做一组**人工指定正确角度**的对照实验（跳过方向分类、直接把图转到正确角度再喂 OCR），把「方向层的问题」和「识别层的问题」分开，再决定换方向模型还是换 OCR 引擎（§3.3） |
| EasyOCR / Tesseract | 进入首轮前若仍无官方表格或方向口径 → 只留对照，不进主路径 |
| 版面分析模型（§4.1） | 不是首轮项：现有 #62 用字块聚类造伪格子、规则链已跑通。**只有** #97 证明字块路线在密集表上不够、或出现多栏 / 图文混排 / 跨页阅读顺序这类「伪格子天然表达不了」的版面时，才回头看它 |
| vLLM | 目标机器无 NVIDIA 卡 / 显存不足 → 换 Ollama 或直接不做本地 LLM（#101 本来就是默认关） |

### 1.4 被排除的候选与理由

| 候选 | 排除理由 |
|---|---|
| **TrOCR**（microsoft/unilm） | 官方定位是**单文本行**识别（"single text-line images"），无检测、无版面、无表格；官方模型与 benchmark 全是英文场景，**不支持中文**。且 `trocr-base-printed` / `-large-printed` 的 HF 模型卡**没有 license 字段**，可商用性无官方声明。不进首轮 |
| **OpenOCR 的 OpenDoc-0.1B / UniRec-0.1B** | 官方自己在文档里用词是 **Vision-Language Model**，属于 §2.6 那一类，与「VLM 非必须」冲突。OpenOCR 的 SVTRv2 det+rec 主系统可以留作对照，但官方**没有**给表格专项指标，优先级低于 Paddle 系 |
| **Surya 2** | 代码 Apache-2.0，**权重是修改过的 AI Pubs Open Rail-M**：「free for research, personal use, and startups under $5M funding/revenue」，更大范围商用要买授权——**这是条件式许可，不是一刀切「要买授权」**（当前官方原文口径，见 §2.6） |
| **olmOCR / DeepSeek-OCR / DeepSeek-OCR 2 / GOT-OCR2.0** | 官方口径就是「要独立 GPU 的视觉语言模型」，与「第一期 OCR + 规则」冲突，见 [ocr-survey.md](ocr-survey.md) §2.3 与 §2.6。DeepSeek-OCR 2（2026-01）体积仍按大模型算（bf16 权重约 6.78 GB），排除理由不变 |
| **MinerU**（[opendatalab/MinerU](https://github.com/opendatalab/MinerU)） | 文档解析领域的事实标准之一，**必须留痕**：许可是 **Apache-2.0 + 附加条款**（不是 AGPL）。附加条款两条——MAU >1 亿或月收入 >$2000 万需单独商业授权；对第三方提供在线服务须显著署名。**排除理由不是许可，是定位**：它是完整文档解析流水线（自带版面/表格/公式与 Markdown 输出），与本项目「字块 → 伪格子 → 自家规则链」的路径重叠但不可替换，接进来等于换掉 #62 与规则链。结论：第一期不接，只留作对照与后续调研 |
| **EasyOCR / Tesseract** | 见 §2.3 / §2.4：官方均未给表格能力口径；Tesseract 官方 LSTM 引擎定位是行识别**但另有 psm 页面分割与 OSD**，缺的是表格结构能力。留作对照，不进首轮 |

---

## 2. OCR 候选（四列对照）

### 2.1 PaddleOCR PP-OCRv6 / PP-OCRv5

| 项 | 链接 |
|---|---|
| 仓库 | [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) |
| 产线模型总表（体积 / 精度 / 模块时延） | [OCR pipeline 文档](https://www.paddleocr.ai/latest/version3.x/pipeline_usage/OCR.html) |
| PP-OCRv6 算法页（参数量 / 场景表 / 端到端速度） | [PP-OCRv6](https://www.paddleocr.ai/latest/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html) |
| PP-OCRv5 算法页（产线峰值 VRAM） | [PP-OCRv5](https://www.paddleocr.ai/latest/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html) |
| 文本识别模块（逐模型体积 / 精度） | [text_recognition](https://www.paddleocr.ai/latest/version3.x/module_usage/text_recognition.html) |
| 文档方向分类 | [doc_img_orientation_classification](https://www.paddleocr.ai/latest/version3.x/module_usage/doc_img_orientation_classification.html) |

**模型体积与精度（已核对官方模型表，单位 MB）**

| 模型 | 存储体积 | 官方精度 | 官方时延 |
|---|---|---|---|
| PP-OCRv6_tiny_det | **1.9** | 检测 Hmean 80.6%* | 官方模块表未给 |
| PP-OCRv6_small_det | **9.6** | 检测 Hmean 84.1%* | 官方模块表未给 |
| PP-OCRv6_medium_det | **59.4** | 检测 Hmean 86.2%* | 官方模块表未给 |
| PP-OCRv6_tiny_rec | **4.4** | 识别 73.5%* | 官方模块表未给 |
| PP-OCRv6_small_rec | **20.4** | 识别 81.3%* | 官方模块表未给 |
| PP-OCRv6_medium_rec | **73.3** | 识别 83.2%* | 官方模块表未给 |
| PP-OCRv5_mobile_det | 4.7 | 检测 Hmean 79.0% | GPU **10.67 ms** / CPU 57.77 ms（T4，常规模式） |
| PP-OCRv5_mobile_rec | 16 | 识别 81.29% | GPU **5.43 ms** / CPU 21.20 ms |
| PP-OCRv5_server_det | 84.3 | 检测 Hmean 83.8% | GPU **89.55 ms** / CPU 383.15 ms |
| PP-OCRv5_server_rec | 81 | 识别 86.38% | GPU **8.46 ms** / CPU 31.21 ms |

\* 官方原文注明：PP-OCRv6 的指标来自**内部多场景评估集**，与 v5/v4 的数**不能直接比**。跨代比较一律以 #97 在自家样本上的实测为准。

行业常见的「PP-OCRv5 = 0.07B 参数」是 HF 博客口径，[ocr-survey.md](ocr-survey.md) 已明确不采信；**PP-OCRv6 是官方第一次给出参数量的版本**：官方原文一处写「覆盖 **1.5M 至 34.5M** 参数的三档完整 OCR 模型族」，另一处写「即使是仅 **1.1M** 参数的 PP-OCRv6_tiny」——**官方自述的 tiny 档有两个数（1.1M / 1.5M）**，本文照录不取其一，medium 的 **34.5M** 两处一致。

**中文密集表格能力（这条最直接）**

PP-OCRv6 官方给了按场景拆的检测 Hmean 表，**其中就有独立的「表格」列**——这是本文能拿到的最硬的表格能力官方数字：

| 模型 | 表格场景 检测 Hmean | 旋转场景 检测 Hmean | 印刷 CN |
|---|---|---|---|
| PP-OCRv6_medium | **96.8** | **93.8** | 95.1 |
| PP-OCRv6_small | 95.6 | 93.7 | 94.2 |
| PP-OCRv6_tiny | 94.7 | 91.0 | 93.1 |
| PP-OCRv5_server | **97.1** | 80.0 | 94.5 |
| PP-OCRv5_mobile | 92.8 | **64.7** | 90.5 |

⚠️ **下面两条是「待验证线索」，不是结论。** 官方已注明 PP-OCRv6 的指标来自内部多场景评估集，**与 v5 的数不能直接比**——同一张表里的跨代数字只能用来决定「先测什么」，不能用来判优劣：

- **表格场景检测**：v5_server 97.1 / v6_medium 96.8 —— 两者差距（0.3）远小于跨代口径的不可比程度，**不足以支持「v6 在表格上不如 v5」**，只能说明「v5_server 值得留在首轮」；
- **旋转场景检测**：v5_mobile 64.7 明显低于 v6_medium 93.8 —— 这一条差距大（29 个点），但仍必须**在同一批旋转样本上实测**才能成立；在实测之前，它只是「v5_mobile 的旋转页要重点看」的提醒。

**要下这两条的结论，唯一的路是 #97 在自家密集表与旋转页上同批实测。** 本文不替它下。

注意这是**检测**指标（字块找得准不准），不是表格结构还原；密集表的结构还原仍由 #62 伪格子 + 规则链负责，见 §4。

**显存（已核对 PP-OCRv5 产线峰值，V100 / PaddlePaddle 3.0.0 / 200 张图 / 含读盘）**

| 产线 | 峰值 VRAM | 平均 VRAM |
|---|---|---|
| v5_mobile（v5_mobile_det + v5_mobile_rec） | **4190.00 MB** | 3114.02 |
| v5_server（v5_server_det + v5_server_rec） | **5402.00 MB** | 4683.93 |

同一页还有关掉文档预处理、改缩放策略的 `OCR-nopp-*` 系列（PaddlePaddle 3.1.0），V100 上 mobile 档峰值 4198 MB、server 档 5410 MB，量级一致。**PP-OCRv6 官方没有给显存表**（只有端到端 s/image），这一项 **官方未给，待 #97 实测**。

**端到端速度（已核对 PP-OCRv6 算法页，单位 s/image，200 张图，含读图与前后处理）**

| 硬件 / 后端 | v6_medium | v6_small | v6_tiny | v5_server | v5_mobile |
|---|---|---|---|---|---|
| NVIDIA A100 / PaddlePaddle | 0.29 | 0.25 | **0.13** | 0.32 | 0.25 |
| NVIDIA V100 / PaddlePaddle | 0.72 | 0.49 | 0.21 | 0.66 | 0.50 |
| NVIDIA V100 / ONNX Runtime | 0.67 | 0.53 | 0.29 | 0.77 | 0.46 |
| Intel Xeon 8350C / PaddlePaddle | 2.05 | 0.79 | 0.32 | 2.04 | 0.80 |
| Intel Xeon 8350C / OpenVINO | 1.40 | 0.59 | **0.20** | 7.30 | 0.78 |
| Apple M4 / PaddlePaddle | 8.82 | 3.07 | 0.96 | >10 | 5.82 |

这张表回答了 #98 的一半问题：**CPU 也能跑**（Xeon 8350C 上 v6_small 0.79 s/页、OpenVINO 0.59 s/页），只是并发档位要另测。

**许可证：** 仓库 [Apache-2.0](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE)，**已核对**。权重同为 Apache-2.0——RapidOCR 的官方 MODEL_LICENSES.md 写明上游 PP-OCRv6 权重与 ONNX 表示「identified as Apache-2.0」，可作为旁证（§2.2）。

### 2.2 RapidOCR（Paddle 权重转 ONNX）

| 项 | 链接 |
|---|---|
| 仓库 | [RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR) |
| 文档站 | [rapidai.github.io/RapidOCRDocs](https://rapidai.github.io/RapidOCRDocs/main/) |
| 模型许可说明 | [python/MODEL_LICENSES.md](https://github.com/RapidAI/RapidOCR/blob/main/python/MODEL_LICENSES.md) |
| 模型清单（含 SHA256） | [python/rapidocr/default_models.yaml](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml) |
| 权重下载（官方模型仓） | [ModelScope · RapidAI/RapidOCR](https://www.modelscope.cn/models/RapidAI/RapidOCR/files) |

**版本已推进（这是 #7 之后最大的变化）：** 官方文档写明 `rapidocr>=3.9.0` 默认用 **PP-OCRv6**（tiny / small / medium），`<3.9.0` 默认 PP-OCRv4 mobile。[ocr-survey.md](ocr-survey.md) 里写的「随你选的 det/rec 模型变」现在有了确定的默认值。

**ONNX 权重体积（已核对官方模型仓 v3.9.2 的文件列表；按 1 MB = 1048576 字节换算）**

| 模型 | det | rec | 文本行方向 cls |
|---|---|---|---|
| PP-OCRv6 tiny | 1.74 | 4.28 | 无（见下） |
| PP-OCRv6 small | 9.47 | 20.25 | 无 |
| PP-OCRv6 medium | 59.24 | 73.08 | 无 |
| PP-OCRv5 mobile | 4.60 | 15.86 | 0.97 |
| PP-OCRv5 server | 84.04 | 80.66 | 6.46 |

**显存：官方未给。** README 只讲后端（ONNX Runtime / OpenVINO / MNN / PaddlePaddle / TensorRT / PyTorch），没有 MB 数字。要显存就回指 Paddle 的产线表，并在 #97 自测。

**中文密集表格能力：官方未给表格专项指标。** 它跑的就是 Paddle 的权重，能力等同上游——但**这一点要在 #97 用实测确认输出一致**，不能靠推理宣称。

**许可证（已核对，这是它的一大卖点）：** 代码 Apache-2.0；MODEL_LICENSES.md 原文写明上游权重版权属百度 / PaddleOCR，**「These permissions are not restricted to non-commercial use.」**，即权重也是 Apache-2.0 且不限商用。

**⚠️ 一个必须写进选型记录的缺口：RapidOCR 官方没有整页方向分类模型。** 已核对 `default_models.yaml`：全文 `doc_ori` 出现 **0 次**，`cls` 只有 `ch_PP-LCNet_x0_25_textline_ori` / `ch_PP-LCNet_x1_0_textline_ori`（**文本行** 0/180）与老的 `ch_ppocr_mobile_v2.0_cls`。也就是说走 RapidOCR 就得**另外配一个页面方向模型**（见 §3），安装面比 PaddleOCR 全家桶杂。

### 2.3 EasyOCR

| 项 | 链接 |
|---|---|
| 仓库 | [JaidedAI/EasyOCR](https://github.com/JaidedAI/EasyOCR) |
| 文档 | [jaided.ai/easyocr/documentation](https://www.jaided.ai/easyocr/documentation/) |
| 模型下载页 | [模型中心](https://www.jaided.ai/easyocr/modelhub/) |

| 四列 | 内容 | 核验 |
|---|---|---|
| 权重体积 | 官方模型中心**只列模型名、不列文件大小**；官方 GitHub Releases 资产（zip）：`zh_sim_g2.zip` **20.3 MB**、`craft_mlt_25k.zip` **77.3 MB**、`english_g2.zip` 14.0 MB、`japanese_g2.zip` 16.1 MB | 已核对 Releases 资产 |
| 显存 | **官方未给。** README 只提「显存小的机器可以 `gpu=False` 走 CPU」 | 官方未给 |
| 许可证 | **Apache-2.0**（仓库 license） | 已核对 |
| 中文密集表格能力 | **官方未提及。** README 与文档页没有表格结构 / 密集表指标 | 官方未给 |

结论：**不进首轮。** 识别质量本身不差，但「体积 / 显存 / 表格 / 方向」四项官方全是空的，同样场景下 Paddle 系四项都有官方数字，没有理由先测它。

### 2.4 Tesseract

| 项 | 链接 |
|---|---|
| 仓库 | [tesseract-ocr/tesseract](https://github.com/tesseract-ocr/tesseract) |
| 文档 | [tesseract-ocr.github.io](https://tesseract-ocr.github.io/) |
| 中文数据 | [tesseract-ocr/tessdata_best](https://github.com/tesseract-ocr/tessdata_best) / [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) |

| 四列 | 内容 | 核验 |
|---|---|---|
| 权重体积 | 官方 tessdata 仓库文件大小（十进制 MB）：`chi_sim.traineddata` — tessdata **44.4 MB** / tessdata_best **13.1 MB** / tessdata_fast **2.5 MB**；另有 `osd.traineddata`（方向与文字方向检测）**10.6 MB** 与 `chi_sim_vert.traineddata`（竖排）| 已核对官方仓库文件大小 |
| 显存 | **官方未给**，官方定位是 CPU 库 | 官方未给 |
| 许可证 | **Apache-2.0**（代码 + tessdata_best README 原文「All data in the repository are licensed under the Apache-2.0 License」） | 已核对 |
| 中文密集表格能力 | **官方未提及，且定位相反**：README 原文「a neural-net (LSTM) engine **which is focused on line recognition**」，全文无 table structure 字样 | 已核对原文 |

结论：**只作对照。** 准确的定位是——官方 LSTM 引擎做的是**行识别**，但 tesseract 本身**有** psm 页面分割（`--psm 0` 起有 OSD、`1`/`12` 带 OSD 的自动分割、`3` 全自动分割等，见官方 [ImproveQuality](https://github.com/tesseract-ocr/tessdoc/blob/main/ImproveQuality.md#page-segmentation-method)）与 `osd` 方向检测；**它缺的是表格结构能力**，不是「没有版面概念」。密集商品表仍要自己接检测 + 版面 + 表格结构，等于把 #62 整条重做一遍，所以不进首轮。

**顺带一条对 #103 有用的：** Tesseract 有官方 `osd`（Orientation and Script Detection）数据，`--psm 0` 只做整页方向与文字方向检测——如果最后不选 Paddle 系，OSD 是一个可考虑的独立方向方案（见 §3.1 第二类）。

### 2.5 补充候选（经典 + 最新）

| 候选 | 权重体积 | 显存 | 许可证 | 中文密集表格能力 | 核验 |
|---|---|---|---|---|---|
| **CnOCR**（[breezedeus/CnOCR](https://github.com/breezedeus/CnOCR)） | 识别：12 M / 25 M / 82 M（自有 densenet 系），另有 PP-OCRv6 系 4.3 / 20 / 73 M；检测 1.7 M–108 M | **官方未给**（只说 CPU 用 `ort-cpu`、GPU 用 `ort-gpu`） | 代码 **Apache-2.0**；HF 上 `breezedeus/cnocr-*` 开权重同为 apache-2.0，另有模型仓未标 license；**官方 README 写明 `densenet_lite_246-gru_base` 先供知识星球会员（一个月后开源）、`densenet_lite_666-gru_large` 是 Pro 模型购买后可用** | **官方未提及**（场景只分 scene / doc / number / general） | 已核对 README 与仓库 license |
| **OpenOCR / SVTRv2**（[Topdu/OpenOCR](https://github.com/Topdu/OpenOCR)） | 官方 Release：`openocr_rec_model.onnx` **25.14 MB**、`openocr_det_model.onnx` **12.42 MB**、`openocr_det_repvit_ch.pth` 12.73 MB | **官方未给**（只给 CPU / GPU 启动命令） | **Apache-2.0**（仓库）；部分 HF 权重仓未标 license | 主系统无表格专项指标；表格能力在 OpenDoc-0.1B，而官方称其为 **VLM**（见 §2.6） | 已核对 Release 资产与 license |
| **TrOCR**（[microsoft/unilm](https://github.com/microsoft/unilm)） | `trocr-base-printed` **1271.6 MB**、`trocr-large-printed` **2319.9 MB**（safetensors） | **官方未给** | 仓库 MIT；**`-printed` 权重模型卡无 license 字段** | **不支持中文**，官方 benchmark 全为英文（IAM / SROIE） | 已核对，**已排除**（§1.4） |
| **docTR**（[mindee/doctr](https://github.com/mindee/doctr)） | 官方未给权重体积（模型按架构名随用随下） | **官方未给** | **Apache-2.0**（仓库）；权重随仓库发布 | 官方文档列出的识别架构为 CRNN / SAR / MASTER / ViTSTR / PARSeq / ViPTR，**官方未把中文列为预训练语言** | 已核对仓库 license 与模型清单 |

**要补的一条候选判据（来自 #106）：** docTR 是**非 Paddle 系**的完整两阶段 det+rec 管线（PyTorch，支持 ONNX），当前首轮四个 OCR 候选**本质上都在比 Paddle 权重的版本与推理封装**（PaddleOCR v5/v6 + RapidOCR）。补 docTR 的价值是给「Paddle 权重这条路整个不成立」时留一条技术路线不同的退路。**但它的中文能力官方没有背书**——要进 #97 得先自测中文，测不过就只留对照，别为了「候选多样性」占评测工期。

### 2.6 端到端 OCR-VLM（对照用，不进第一期主路径）

与「第一期 OCR + 规则，VLM 非必须」冲突：它们直接出字，显存和运维按大模型算。#97 只在「传统 OCR 路线被证伪」时才回头看这一档。

**2026 上半年这一档的体量已经明显下来**（0.65B–1.7B），和 2025 年那批 7B 级不是一回事，所以单列一张表：

| 模型 | 官方规模 | 权重体积 | 许可证 | 官方中文 / 表格口径 | 核验 |
|---|---|---|---|---|---|
| **PaddleOCR-VL-1.6**（[模型卡](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6)） | **0.9B** | `model.safetensors` **1828.4 MB** | **apache-2.0** | 官方称 OmniDocBench **v1.6 达 96.33%**，在 v1.5 与 Real5-OmniDocBench 上也刷新记录；架构与 1.5 完全兼容 | 已核对 HF 模型卡（2026-05-27 建仓，官方 2026.05.28 发布） |
| **GLM-OCR**（[模型卡](https://huggingface.co/zai-org/GLM-OCR)） | **0.9B**（模型卡另提 GLM-0.5B 语言解码器——那是组件，不是全模型） | `model.safetensors` **2527.8 MB** | **MIT** | 官方原文「Achieves a score of **94.62** on OmniDocBench V1.5, ranking #1 overall」；管线用 **PP-DocLayout-V3**（Apache-2.0）；官方称支持 **vLLM / SGLang / Ollama** 部署 | 已核对 HF 模型卡（2026-01-30 建仓）。**注意**：官方只写 Markdown / JSON 结构化输出，**没有「表格输出 HTML」的说法** |
| **Surya 2**（[仓库](https://github.com/datalab-to/surya)） | 0.65B，官方 benchmark 行名「Surya OCR 2」 | 官方未给固定体积 | ⚠️ **代码 Apache-2.0，权重是修改过的 AI Pubs Open Rail-M**：README 原文「free for research, personal use, and startups under **$5M funding/revenue**」，更大范围商用要走 [定价页](https://www.datalab.to/pricing)。**标红：条件式许可，商用前过法务**（口径截至复核日**未变**，不要写成「已放开」或「一律要买授权」） | 官方原文：「**Surya 2 runs layout, OCR, and table recognition through a single VLM**」——一个模型做版面 + OCR + 表格（含阅读顺序），这是它相对上表其他项最实质的差异 | 已核对 README |
| **LightOnOCR-2-1B**（[模型卡](https://huggingface.co/lightonai/LightOnOCR-2-1B)） | 1B，官方称「end-to-end 1B-parameter vision-language model」 | 官方未给固定体积 | **apache-2.0** | 官方支持 en/fr/de/es/it/nl/pt/sv/da/**zh**/ja。官方速度口径是「**3.3× faster than Chandra OCR**」（Chandra 为 9.0B）——**限定语不能抹掉**，它不是泛指「比 9B 级快 3.3 倍」 | 已核对模型卡。**olmOCR-bench 83.2 不是它自己模型卡的数**，出自 Surya README 的对照表（该表自注口径不可直接比），引用时要带出处 |
| **DeepSeek-OCR 2**（[模型卡](https://huggingface.co/deepseek-ai/DeepSeek-OCR-2)） | 官方模型卡**未标参数量**；bf16 权重约 **6.78 GB** | 6.78 GB | **apache-2.0**（**不是 MIT**） | 官方未给中文 / 表格专项数字 | 已核对 HF front-matter 与权重文件（2026-01-27 建仓）。体积仍按大模型算，排除理由不变 |
| **granite-docling-258M**（[模型卡](https://huggingface.co/ibm-granite/granite-docling-258M)） | **258M**（Idefics3 架构；视觉编码器 siglip2-base-patch16-512 + **Granite 165M** LLM） | 官方未给固定体积 | **apache-2.0** | 官方表 **FinTabNet 150dpi**：TEDS(structure) **0.97** / TEDS(w/content) **0.96**——**这是本档里唯一给到「含内容」表格分的**；官方写「**Japanese, Arabic and Chinese support (_experimental_)**」，中文是实验性 | 已核对模型卡（官方 Release Date 2025-09-17）。**「约 0.5 GB 显存 / 笔记本可跑」官方未给**，模型卡无任何显存数字 |
| **dots.ocr**（[模型卡](https://huggingface.co/rednote-hilab/dots.ocr)） | 1.7B LLM 底座，官方称 SOTA | 仓库 **5.67 GB** | **MIT** | 官方称多语言文档解析；部署推荐 vLLM | 已核对 |
| olmOCR / DeepSeek-OCR（初代） / GOT-OCR2.0 | 7B / 3B MoE / 580M | 见 [ocr-survey.md](ocr-survey.md) §2.3 | 各自见原文 | 见 #7 | 沿用 #7 结论 |

 **这张表怎么用：** 第一期不选它们，但**如果 #97 的结论是「传统 OCR + 规则在密集商品表上过不去」，回头的顺序就是这张表从上到下**——先试体积最小、官方中文/表格口径最全的（GLM-OCR 与 PaddleOCR-VL-1.6 同为 0.9B 且都带官方表格口径；granite-docling 有含内容的 TEDS，但中文是实验性）。Surya 2 的「一个模型做三件事」是架构上最省事的一条，但权重许可要先过法务。

---

## 3. 整页方向分类（#103 的分水岭，独立成节）

### 3.1 三类解，适用边界不同

| 解 | 解决什么 | 适用边界 |
|---|---|---|
| **① 引擎自带的整页方向分类** | 输入图整页被转 90/180/270，先转正再 OCR | **首选。** 前提是引擎提供 doc_ori 模型；PaddleOCR 有，RapidOCR 没有（§3.4） |
| **② 独立方向分类模型** | 同上，但换别的来源 | 选 RapidOCR / 自建管线时的补丁；Tesseract 的 `osd` 属这一类 |
| **③ 页面 rotation 元数据** | PDF 自带 `/Rotate`，渲染时已转正 | **已经在做，不是缺口。** [pdf.py](../src/docparse/adapters/parsers/pdf.py) 渲染时 `pymupdf.Matrix` 已应用页面 rotation，文字层 bbox 也取 fitz 显示坐标系（已应用 rotation） |

### 3.2 官方模型（已核对）

| 模型 | 存储体积 | Top-1 Acc | 类别 | 作用 |
|---|---|---|---|---|
| **PP-LCNet_x1_0_doc_ori** | **7 MB** | **99.06%** | **0° / 90° / 180° / 270°** 四类 | 整页方向分类 |
| PP-LCNet_x0_25_textline_ori | 0.96 MB | 98.85% | 文本行 0/180 | 行级方向纠正 |
| PP-LCNet_x1_0_textline_ori | 6.5 MB | 99.42% | 文本行 0/180 | 同上，更大档 |

来源：[文档图像方向分类模块](https://www.paddleocr.ai/latest/version3.x/module_usage/doc_img_orientation_classification.html)（原文写明「四个类别，即0度，90度，180度，270度」）、[OCR pipeline 模型表](https://www.paddleocr.ai/latest/version3.x/pipeline_usage/OCR.html)。

### 3.3 为什么这层不能省

- **半岛那种（PDF 自带 rotation 元数据）**：渲染时已转正，四家通用引擎都能读——这类**已经解决**，别拿它当方向分类的效果证据。
- **镇发那种（无元数据、内容真的转了 90°）**：百度 / 阿里云直接乱码，TextIn 靠 `straighten=1` 返回 `angle=90` 自动转正——**这才是 #60 的分水岭**。
- 换本地引擎后，**没有 `straighten` 这种东西**，必须自己先判方向。不补这层，镇发 p1 会原样复现乱码。

**⚠️ 乱码怎么归因（#106 修正，这条是方法，不是结论）：** 旋转页出现乱码，**不能直接判成「识别模型不行」**。同一个现象至少有四个来源：① 方向分类角度判错；② 旋转方向搞反（90 转成 270）；③ 转正后裁切范围错了；④ OCR 像素 → 页面 pt 的坐标变换错。**正确的做法是先做一组对照实验**：

```text
A 组：不走方向分类，人工把图转到正确角度再喂 OCR   ← 识别层的能力上限
B 组：走方向分类，让它自己判                        ← 端到端真实表现
C 组：走方向分类但把判定角度换成人为指定的正确值     ← 只隔离「方向模型判错」这一项
```

- A 组过、B 组不过、C 组过 → **方向模型的锅**，换/调方向分类，不动 OCR；
- A 组就不过 → 才是**识别层的锅**，换 OCR 引擎；
- A 组过、C 组也不过 → 问题在**转正后的裁切或坐标变换**，是 #99 的接入实现，不是任何一个模型。

**在跑完这三组之前，不要写「某引擎在旋转页不行」的结论。**

### 3.4 已核实的缺口

**RapidOCR 官方模型清单里没有任何 `doc_ori` 模型**——已核对 `default_models.yaml` 全文，`doc_ori` 出现 0 次，`cls` 只有文本行方向（0/180）与老的 v2.0 cls。**文本行方向 ≠ 整页方向**：前者纠正的是行内倒置，后者纠正的是整页转 90°。

选 RapidOCR 就必须额外配 ①/② 里的整页方向模型（如 PP-LCNet_x1_0_doc_ori 的 ONNX 版），并接受「两个来源、两套版本管理」的运维成本。**这一条要写进 #99 的选型结论**。

### 3.5 坐标约定（#99 不能破的约定，已核对现有代码）

[ocr.py](../src/docparse/adapters/parsers/ocr.py) 的 `OcrOutcome` 语义：`lines` 与 `width`/`height` **均以正立图为参照系**（angle 为 90/270 时宽高对调），整页 angle 留档进 warnings；[pdf.py](../src/docparse/adapters/parsers/pdf.py) 把 OCR 像素按 `1 / RENDER_ZOOM` 缩回页面 pt（`RENDER_ZOOM = 2.0`）。#62 的伪格子直接吃这套坐标——**#99 接本地引擎时这套语义必须保持一致**，#103 的「旋转页」验收也挂在这上面。

---

## 4. 结构解析：版面分析 + 表格结构识别（备选，非第一期主路径）

这一节管的是「字块 → 结构」那一步。#62 现在用**字块聚类造伪格子**把它整个跳过了；下面两类模型是「跳过这一步不够用」时的备选。

### 4.1 版面分析（layout）

版面分析做两件事：把页面切成语义区域（文本段 / 标题 / 表格 / 公式 / 图片…），以及**恢复阅读顺序**。它不是 OCR，输入是页面图，输出是区域框 + 类别 + 顺序。

| 模型 | 存储体积 | 官方精度 | 许可证 | 核验 |
|---|---|---|---|---|
| **PP-DocLayoutV2**（[模型卡](https://huggingface.co/PaddlePaddle/PP-DocLayoutV2)） | **203.8 MB**（官方文档）/ HF `inference.pdiparams` 202.3 MB | **mAP(0.5) 81.4%** | **apache-2.0** | 已核对官方 [版面分析模块文档](https://www.paddleocr.ai/latest/version3.x/module_usage/layout_analysis.html) |
| **PP-DocLayoutV3**（[模型卡](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3)） | **官方文档未给**；HF `inference.pdiparams` **124.7 MB** | **官方文档未给**；官方只给了速度（`paddle_static` 端到端 **72.33 ms**） | **apache-2.0** | 已核对 HF 模型卡；体积与精度**官方未给** |

**官方评估口径（已核对 V2 那行）**：自建版面区域检测数据集，**1000 张**中英文论文 / 杂志 / 报纸 / 研报 / PPT / 试卷 / 课本等，**25 类**版面元素（文档标题、段落标题、文本、竖排文本、页码、摘要、目录、参考文献、脚注、图像脚注、页眉、页脚、页眉图像、页脚图像、算法、行内公式、行间公式、公式编号、图像、表格、图/表标题、印章、图表、侧栏文本、参考文献内容）。

**⚠️ 官方文档自相矛盾（引用前必读）**：同一份 `layout_analysis.md` 里，正文写「**该模块目前仅支持 PP-DocLayoutV2 一个模型**」，而快速开始与 Python 示例**全部用 `PP-DocLayoutV3`**，速度表里也两代都列。**引用体积 / 精度时只能引 V2 那行，别把 V2 的数字安到 V3 上**；V3 的体积与精度以官方后续更新为准，本文不替它填。

**为什么现在要单独记这一节：** 它是**下游新一档 VLM 的公共组件**——GLM-OCR 官方管线用的就是 PP-DocLayout-V3（§2.6），PaddleOCR-VL 系同理。也就是说，如果哪天要走 VLM 路线，**版面模型是会被一起带进来的**，现在把它记清楚，免得那时候才发现这一层也要过许可证与体积的账。

**第一期怎么处理：** 跟 #62 的关系说清楚——#62 的伪格子是**从字块位置反推格子**，不做区域分类、不恢复阅读顺序；对报关单这种「表头 KV + 一张商品表」的结构够用，而且已经跑通。版面分析要解决的是**多栏、图文混排、跨页阅读顺序**这类场景，**报关单不是**。所以：不进首轮，触发条件与下一节表格结构相同。

### 4.2 表格结构识别

| 模型 | 存储体积 | 官方精度（%） | 官方 GPU 时延 | 备注 |
|---|---|---|---|---|
| SLANet | **6.9 MB** | 59.52 | 23.96 / 21.75 ms（常规 / 高性能） | PP-LCNet 骨干，轻量 |
| SLANet_plus | **6.9 MB** | 63.69 | 23.43 / 22.16 ms | SLANet 增强 |
| SLANeXt_wired | **351 MB** | 69.65 | 85.92 ms | 有线表专用，体积大 |

来源：[表格结构识别模块](https://www.paddleocr.ai/latest/version3.x/module_usage/table_structure_recognition.html)。**官方列名只写「精度（%）」，未写明指标定义**（业内通常是 TEDS，但官方没写，本文件不替它认定）。输出是表格区域的 HTML 结构。

**非 Paddle 系对照（检验 SLANeX 的 69.65% 在外部口径下是什么位置）：**

| 候选 | 体积 | 许可证 | 官方表格指标 | 核验 |
|---|---|---|---|---|
| [RapidTable](https://github.com/RapidAI/RapidTable) | 官方未给（包装 PP-Structure / ModelScope 算法） | Apache-2.0 | 官方未给 | 已核对 license |
| [Table Transformer (TATR)](https://huggingface.co/microsoft/table-transformer-structure-recognition)（Microsoft） | `model.safetensors` **110.1 MB**（结构识别）/ **110.0 MB**（检测） | **MIT** | 官方未给（经典 2021 模型，英文文档为主） | 已核对 HF 模型卡 |
| **TableFormer**（Docling 内置） | **官方未给**（`ds4sd/tableformer` 模型仓**未标 license 字段**） | ⚠️ **代码 MIT（Docling 本体），但 TableFormer 权重仓无 license 声明**——**标红：要用先过法务** | 官方未给 | 已核对 HF 仓库（无 license）与 Docling 仓库（MIT） |
| **granite-docling-258M** | 258M 参数 | **apache-2.0** | **FinTabNet 150dpi：TEDS(structure) 0.97 / TEDS(w/content) 0.96** | 已核对模型卡（§2.6） |

第三行那条要特别注意：**官方口径里唯一给了「含内容」TEDS 的是 granite-docling（0.96）**，但它是端到端 VLM，不是可插拔的表格结构模块；而真正可插拔的 TableFormer 权重仓**没有 license 声明**。这一格正好说明为什么第一期不该急着换：现有的字块路线**没有任何许可悬空**。

### 4.3 为什么第一期不上（版面分析与表格结构同一条）

1. **现有路线已经跑通且不依赖它**：[ocr_layout.py](../src/docparse/adapters/parsers/ocr_layout.py) 按行带聚类 + 分区列切分造伪格子，复用 [layout.py](../src/docparse/adapters/parsers/layout.py) 的 `split_sheet` 与现成版面刀（#62 / #23 已收口）。加这两类模型都是**加一个新引擎**，不是加一条新规则，动静比改 YAML 大得多。
2. **它们换掉的是「字块 → 格子」这一步，而这一步现在同时喂着表头 KV 和商品表**；换掉要连 #62、#23 的验收一起重做。
3. **官方精度口径不透明**（表格结构只写「精度（%）」；版面分析的 V3 干脆没给体积与精度），拿它替换一条已有实测背书的链路，性价比要先算。

**触发条件（写清什么时候才回头看它）：** #97 在镇发 / 半岛 / 补充测试的密集商品表上，若「行切分 / 列归属」错误占到字段错误的主因，且调版面刀治不好，再上 SLANet_plus 做 A/B；**版面分析的触发条件更靠后**——只有出现多栏 / 图文混排 / 跨页阅读顺序这类「伪格子天然表达不了」的版面时才需要。**在那之前不加依赖。**

---

## 5. 本地 LLM 候选（服务端口径，供 #101）

**范围提醒：** #101 只做「把端点换成内网可起的 OpenAI 兼容服务 + 默认关」，**不解决消歧效果**。#26 / #27 真要启用 LLM 时，模型质量要另评。本节只回答「服务端起哪个、吃什么资源」。

### 5.1 服务端对照

| 项 | vLLM | Ollama |
|---|---|---|
| 仓库 / 文档 | [vllm-project/vllm](https://github.com/vllm-project/vllm) · [在线服务文档](https://docs.vllm.ai/en/latest/serving/online_serving/) | [ollama/ollama](https://github.com/ollama/ollama) · [OpenAI 兼容文档](https://docs.ollama.com/api/openai-compatibility) |
| 许可证 | **Apache-2.0**（已核对） | **MIT**（已核对） |
| OpenAI 兼容端点 | `/v1/chat/completions`、`/v1/completions`、`/v1/embeddings`、`/v1/responses` 等（已核对官方端点表） | **子集**：`/v1/chat/completions`、`/v1/completions`、`/v1/models`、`/v1/embeddings`、`/v1/responses`（v0.13.3 起）。已核对原文「Ollama supports **a subset** of the OpenAI API」 |
| 已知限制 | `/v1/chat/completions` 需要 chat template；`user` 参数被忽略 | 本地服务**要求 API key 但会忽略它**；`tool_choice` / `logit_bias` / `user` / `n` / Logprobs 不支持；图片只收 base64 不收 URL |
| 显存闸 | `--gpu-memory-utilization` **默认 0.92**（已核对官方 CLI 文档），即默认吃掉 92% 显存 | 官方 README **未给**显存口径 |
| 启动 | `vllm serve <model>` | `ollama serve` + `ollama pull <model>` |
| 硬件要求 | 官方 README：NVIDIA / AMD / Intel GPU、x86/ARM/PowerPC CPU **均可**（未给 VRAM 数字） | 官方未给 |

**共同点（#100 / #101 要用）：** 两者都能起一个只监听内网的 OpenAI 兼容端点，现有 [openai_compat.py](../src/docparse/adapters/llm/openai_compat.py) 只把档位 `DOCPARSE_LLM_ENGINE` 留作 `local`、再把 `DOCPARSE_LLM_LOCAL_BASE_URL` / `DOCPARSE_LLM_LOCAL_MODEL` 指过去即可对上，**协议不用改**（#101 落地，见 §5.4）。

### 5.2 模型档位与体积

Ollama 官方模型页给了**确定的文件体积**（已核对 [ollama.com/library/qwen3](https://ollama.com/library/qwen3)）：

| 档位 | 官方文件体积 |
|---|---|
| qwen3:0.6b | 523 MB |
| qwen3:1.7b | 1.4 GB |
| qwen3:4b | **2.5 GB** |
| qwen3:8b | 5.2 GB |
| qwen3:14b | 9.3 GB |
| qwen3:32b | 20 GB |

**换算原则（不是官方数字，写清楚免得被当实测）：** 权重体积 ≠ 显存占用。实际显存 ≈ 权重 + KV cache + 框架开销；vLLM 默认还要按 `--gpu-memory-utilization 0.92` 预留。**任何「X GB 卡能跑 YB 模型」的结论都必须由 #98 实测给，本文不给。**

**第一期的保守起点（供 #101 起服务，不代表质量已认可）：** 4B 级——如 [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)（官方模型卡：参数量 **4.0B**、License **apache-2.0**、BF16）。在 24GB 卡上有充足余量跑并发；消歧效果由 #26 / #27 另评。

### 5.3 默认关（与 #100 同一套语义）

两个 client（云 OCR / 云 LLM）共用一套开关语义：**未显式启用则不发 HTTP**。本地端点同样默认关——「本地」不等于「可以随便起服务」，配置项、端口、模型名都要显式写。#100 负责这条闸的落地与零外呼验证。

### 5.4 #101 落地：档位与本地端点

已在 [openai_compat.py](../src/docparse/adapters/llm/openai_compat.py) + [config.py](../src/docparse/config.py) 落地，与 #99 的 `DOCPARSE_OCR_ENGINE`（`local` / `textin`）同形：

| 配置项 | 默认 | 说明 |
|---|---|---|
| `DOCPARSE_LLM_ENGINE` | `local` | `local` = 内网 OpenAI 兼容口；`cloud` = 云端口（需密钥）。除 `cloud` 外的取值一律按 `local` 处理——档位写错时倒向**不出网**那一档 |
| `DOCPARSE_LLM_LOCAL_BASE_URL` | `http://127.0.0.1:11434/v1` | 本地端点地址（Ollama 默认口）；vLLM 按 `vllm serve` 的监听地址改 |
| `DOCPARSE_LLM_LOCAL_MODEL` | `qwen3:4b`（§5.2 的 4B 保守起点） | 本地模型名 |
| `DOCPARSE_LLM_LOCAL_API_KEY` | 空 | 本地端点通常不鉴权，可留空（空则不带头）；Ollama 要求非空但忽略内容，填任意串即可 |
| `DOCPARSE_LLM_BASE_URL` / `DOCPARSE_LLM_MODEL` / `DOCPARSE_LLM_API_KEY` | 云端 | 仅 `llm_engine=cloud` 时生效，仍强制密钥 |

**两档共用 #100 的硬闸**：`DOCPARSE_ALLOW_CLOUD` 未显式 `true` 时，本地档也一样一次 HTTP 都不发（`cloud_gate` 只看开关、不看地址）。**默认零外呼**，不用拔网线也能验。

**怎么验证本 Issue 的验收（「启用时能对着内网端点跑通一次 `complete_json`」）：**

```bash
# 1) 起一个内网 OpenAI 兼容端点（二选一，任选本机可跑）
ollama serve && ollama pull qwen3:4b         # 默认 http://127.0.0.1:11434/v1
vllm serve Qwen/Qwen3-4B-Instruct-2507        # 默认 http://127.0.0.1:8000/v1，改上面的 BASE_URL

# 2) .env：保持 llm_engine=local，显式开闸
DOCPARSE_ALLOW_CLOUD=true
DOCPARSE_LLM_LOCAL_BASE_URL=http://127.0.0.1:11434/v1
DOCPARSE_LLM_LOCAL_MODEL=qwen3:4b

# 3) 跑一次
python -c "from docparse.adapters.llm import OpenAICompatClient; \
print(OpenAICompatClient().complete_json(system='只输出 JSON', user='回 {\"ok\": true}'))"
```

**注意：本 Issue 不解决消歧效果。** `fields.yaml` 目前没有任何字段启用 `llm` extractor，抽取行为与 #101 前完全一致（`tests/test_local_llm.py` 有一条守门断言盯着）。#26 / #27 真要启用 LLM 时，本地模型的质量要**另评**，不能拿本 Issue 的「跑得通」当效果背书。

---

## 6. 与流水线怎么接（本文不动代码）

```text
扫描 PDF / jpg / png
    → pdf.py / image.py 渲染（已应用页面 rotation 元数据）
    → OcrClient.read_image(bytes) → OcrOutcome
         ├─ 云端：TextinOcrClient（现路径，默认关）
         └─ 本地：local_ocr.py（#99 新增，可带 doc_ori 前置）
    → ocr_blocks() → DocumentIR（bbox 以正立图为参照系）
    → ocr_layout.py 伪格子（#62，零改动）
    → layout.py 版面刀 → head_map / goods_map / assemble / validate（零改动）
```

| 能力 | 落点 | 不动的 |
|---|---|---|
| 本地 OCR 引擎 | `adapters/parsers/local_ocr.py` + `config.py`（#99） | `pdf.py` / `image.py` / `ocr_layout.py` / pipeline / extraction / schema |
| 离线开关 | `config.py` + 两个 client 的前置检查（#100） | 流水线结构 |
| 本地 LLM 端点 | `config.py` + `adapters/llm/openai_compat.py`（#101） | `complete_json` 协议、`fields.yaml` 的 `llm` extractor 开关状态 |
| 版面分析 / 表格结构（§4，**备选**） | 若启用，是在 `ocr_layout.py` **之前或替代**它插一个步骤，并把区域框写进 IR | 若真做，`ocr_layout.py` 与 #62 验收要一起重做——不是「加个 adapter」那么轻 |

**出网点只剩两个，且都默认关：** 云 OCR（TextIn）与云 LLM。xlsx / xls、文字层 PDF、版面重建、抽取、组装、校验、FastAPI 全程不出网（已核对 [#94](https://github.com/Baldwinzc/docparse/issues/94) 的出网点盘点）。

**#99 的接入边界（一句话）：** 只换 `OcrClient` 的实现与 `config.py` 的档位，**上面这条链路一个字都不用改**——方向分类作为本地 client 的前置步骤塞在 `local_ocr.py` 里面，伪格子与版面刀看不到它。这也是 §3.5 那条坐标约定必须守住的原因。

---

## 7. 实现前再点一次的清单

1. [PP-OCRv6 算法页](https://www.paddleocr.ai/latest/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html)（参数量、场景表、端到端速度）
2. [PP-OCRv5 算法页](https://www.paddleocr.ai/latest/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html)（产线峰值 VRAM）
3. [OCR pipeline 模型总表](https://www.paddleocr.ai/latest/version3.x/pipeline_usage/OCR.html)（体积 / 精度 / 模块时延）
4. [文档方向分类模块](https://www.paddleocr.ai/latest/version3.x/module_usage/doc_img_orientation_classification.html)
5. [版面分析模块](https://www.paddleocr.ai/latest/version3.x/module_usage/layout_analysis.html)（PP-DocLayoutV2/V3；正文与示例矛盾，见 §4.1）
6. [表格结构识别模块](https://www.paddleocr.ai/latest/version3.x/module_usage/table_structure_recognition.html)
7. [RapidOCR 模型清单 default_models.yaml](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml)（版本与 SHA256）
8. [RapidOCR MODEL_LICENSES.md](https://github.com/RapidAI/RapidOCR/blob/main/python/MODEL_LICENSES.md)（权重许可）
9. [Surya 权重许可](https://github.com/datalab-to/surya)（OpenRAIL-M 条件，商用前必读；当前口径见 §2.6）
10. [MinerU LICENSE.md](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md)（Apache-2.0 **+ 附加条款**，不是 AGPL）
11. [GLM-OCR](https://huggingface.co/zai-org/GLM-OCR) · [PaddleOCR-VL-1.6](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6) · [granite-docling-258M](https://huggingface.co/ibm-granite/granite-docling-258M)（轻量 OCR-VLM 一档）
12. [vLLM 在线服务文档](https://docs.vllm.ai/en/latest/serving/online_serving/) 与 [CLI 参考](https://docs.vllm.ai/en/latest/cli/serve.html)（端点、默认参数）
13. [Ollama OpenAI 兼容文档](https://docs.ollama.com/api/openai-compatibility)（支持的端点子集）

把当时的版本号、体积、许可证记回本文件的「已核对」列，再开 #97。

---

## 8. 以后新引擎 / 新版本往哪加

| 要加什么 | 改哪个文件 | 动不动 Python |
|---|---|---|
| **加一个本地 OCR 引擎**（第 3、第 4 个） | `src/docparse/adapters/parsers/local_ocr.py` 加一个实现 `OcrClient` 协议的类；引擎档位加到 `config.py` | **要**（一个类 + 一个配置项），但 `pdf.py` / `image.py` / `ocr_layout.py` / pipeline **零改动** |
| **换模型版本**（如 PP-OCRv7） | 只改 `config.py` 的模型名，或 #99 的引擎权重清单 | **不要**（前提是同一个引擎后端） |
| **换引擎后端**（Paddle ↔ ONNX ↔ OpenVINO） | `local_ocr.py` 里的后端选择 + `pyproject.toml` 的 optional 依赖 | 要，但只在 `local_ocr.py` |
| **加 / 换整页方向分类** | 同上，方向分类作为本地 client 的前置步骤；若独立成模块则新加一个类 | 要；**注意 bbox 参照系必须仍是正立图**（§3.5） |
| **加版面分析**（§4.1） | 新增解析步骤 + `pipeline/steps/` 挂点，输出区域框进 IR（`domain/ir.py` 可能要加字段） | 要，且要重跑 #62 / #23 验收；**改动面比前几项大，因为它改的是 IR 结构** |
| **加一个表格结构识别**（§4.2） | 新增解析步骤 + `pipeline/steps/` 挂点，替换或旁路 `ocr_layout.py` 的伪格子 | 要，且要重跑 #62 / #23 验收 |
| **换本地 LLM 服务端** | 只改 `.env` 的 `DOCPARSE_LLM_LOCAL_BASE_URL` / `DOCPARSE_LLM_LOCAL_MODEL`（vLLM ↔ Ollama 同协议） | **不要**（OpenAI 兼容端点同一套协议；`config.py` 的档位 `local` 已就位，#101） |
| **上一条 VLM 主路径**（GLM-OCR / PaddleOCR-VL-1.6 一类） | 不是「加引擎」而是**改链路**：`ocr_layout.py` + 规则链要让位给端到端输出 | 要，且是重新开 Epic 的规模（与 #11 冻结的「VLM 非必须」冲突，需先改冻结结论） |
| **新增评测引擎 / 样本** | `benchmarks/ocr/engines.py`（加引擎适配器）、`benchmarks/ocr/real.py` + `DOCPARSE_OCR_DEMO_DIR`（加真机样本） | 要（#97 的实现文件） |
| **新增候选调研**（不写代码） | 就在本文件对应章节加一行，写清四列 + 官方链接 + 核验状态 | 不要 |
