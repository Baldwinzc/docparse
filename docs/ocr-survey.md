# OCR 调研：开源（参数量 / 显存）与闭源（价格）

对应 Issue：[#7](https://github.com/Baldwinzc/docparse/issues/7)

和 [model-survey.md](model-survey.md) 的分工：那份写解析链路分层（垂直单据 / 按页文档解析 / LLM）。本份只对照 **OCR 引擎本身**——把图里的字读出来。

> **阅读约定**
>
> - 每个被引用的参数量、显存、单价旁都有链接。
> - **已核对**：本环境读到了页面/论文原文中的数字。
> - **待打开核对**：检索口径一致，但本环境未读到 HTML 表格原文，实现前请点开链接。
> - 官方根本没给的指标写成「官方未给」，不用社区博客数字顶替。
> - 第一期策略仍是 **OCR + 规则，VLM 非必须**。文中的端到端 OCR-VLM 只作对照，不进 MVP。

---

## 1. 结论（先看这个）

第一期扫描件建议两条候选，样本到了再 A/B：

| 路径 | 是什么 | 为什么 |
|---|---|---|
| **闭源按页 OCR** | 合合 TextIn 通用识别，或报关单专用 API | 无 GPU、按页价透明、报关单有现成字段 |
| **开源传统 OCR** | PaddleOCR PP-OCRv5 mobile / RapidOCR | 官方给了体积和 V100 显存；可 CPU；不是 7B VLM |

不建议第一期上的：

- olmOCR（官方 7B、至少 12GB GPU）
- DeepSeek-OCR / Surya 这类「OCR 外壳的 VLM」（和已冻结的「VLM 非必须」冲突，且更吃显存）
- 腾讯云通用印刷体后付费低量档 **0.15 元/次**（同等清晰扫描件贵过 TextIn 套餐）

---

## 2. 开源

先分两类，不要把「认字小模型」和「视觉大模型做 OCR」放在同一显存档比较。

```text
传统检测+识别（Paddle / Rapid / Easy / Tesseract）
    体积几十到一两百 MB，CPU 能跑，GPU 通常数 GB

端到端 OCR-VLM（GOT / Surya / olmOCR / DeepSeek-OCR）
    从 580M 到 7B，官方多要求独立 GPU
```

### 2.1 传统 OCR（更贴近第一期）

#### PaddleOCR PP-OCRv5 / v4

| 文档 | 链接 |
|---|---|
| 算法与推理显存 | [paddleocr.ai · PP-OCRv5](https://www.paddleocr.ai/latest/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html) |
| 同上（GitHub md） | [PaddleOCR PP-OCRv5.md](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv5/PP-OCRv5.md) |
| 推理模型存储体积 | [PaddleX OCR pipeline](https://paddlepaddle.github.io/PaddleX/3.3/en/pipeline_usage/tutorials/ocr_pipelines/OCR.html) |
| 仓库 | [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) |

**推理模型存储体积（已核对 PaddleX 页，单位 MB）**

| 模型 | 体积 |
|---|---|
| PP-OCRv5_server_det | 84.3 |
| PP-OCRv5_mobile_det | 4.7 |
| PP-OCRv5_server_rec | 81 |
| PP-OCRv5_mobile_rec | 16 |
| PP-OCRv4_server_det | 109 |
| PP-OCRv4_mobile_det | 4.7 |
| PP-OCRv4_server_rec | 173 |
| PP-OCRv4_mobile_rec | 10.5 |

来源：[PaddleX OCR pipeline](https://paddlepaddle.github.io/PaddleX/3.3/en/pipeline_usage/tutorials/ocr_pipelines/OCR.html)

**端到端产线 GPU 显存（已核对算法页，单位 MB）**

测试硬件原文：NVIDIA Tesla V100 + Intel Xeon Gold 6271C，PaddlePaddle 3.0.0；200 张图，含读盘；列名「峰值 VRAM 用量（MB）」。

| 产线 | 峰值 VRAM | 平均 VRAM |
|---|---|---|
| v5_mobile | 4190.00 | 3114.02 |
| v4_mobile | 1304.00 | 1166.68 |
| v5_server | 5402.00 | 4683.93 |
| v4_server | 6760.67 | 5788.02 |

来源：[PP-OCRv5 算法页](https://www.paddleocr.ai/latest/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html)

注意：这是**整条产线峰值**，不是权重文件大小。分辨率、`limit_side_len`、是否开方向分类都会变。同页还有 A100 上更高峰值（例如策略 `min-1280` 可到上万 MB），实现前按自己的输入尺寸重测。

**参数量：** 上述两份官方页**没有**写出「X 亿参数」。Hugging Face 博客有「0.07 billion parameters」的表述（[baidu/ppocrv5](https://huggingface.co/blog/baidu/ppocrv5)），那是博客不是模型卡表格，**本表不把它当官方参数量**。部署请用上面的 MB 体积 + VRAM。

#### RapidOCR（Paddle 模型的工程封装）

- 仓库：[github.com/RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR)
- 文档：[rapidai.github.io/RapidOCRDocs](https://rapidai.github.io/RapidOCRDocs/)
- 官方定位：ONNX / OpenVINO 等后端跑 Paddle 系检测识别，偏部署。
- **参数量 / 峰值显存：官方 README 未给统一数字。** 体积随你选的 det/rec 模型变，应回指 Paddle 上表。
- 适合：不想装 PaddlePaddle、只要 CPU/ONNX 推理。Docling 默认 OCR 后端之一（见其文档，不在此展开）。

#### EasyOCR

- 仓库：[github.com/JaidedAI/EasyOCR](https://github.com/JaidedAI/EasyOCR)
- 文档：[jaided.ai/easyocr/documentation](https://www.jaided.ai/easyocr/documentation/)
- 已核对 README：**80+ 语言**；支持 `gpu=True/False`。
- **参数量：官方未给。**
- **VRAM：官方未给。** README 只提到低显存 GPU 时的注意，没有 MB 数字。

#### Tesseract

- 仓库：[github.com/tesseract-ocr/tesseract](https://github.com/tesseract-ocr/tesseract)
- 站点：[tesseract-ocr.github.io](https://tesseract-ocr.github.io/)
- 已核对：项目自述是 `libtesseract` + CLI，**官方未给 GPU 显存或参数量**。
- 实际是 CPU LSTM 引擎。中文密集表格、扫描报关单通常弱于 Paddle 系，只适合干净印刷体或作对照。

### 2.2 文档流水线里的 OCR（不是单一模型）

#### MinerU

- 文档：[opendatalab.github.io/MinerU/quick_start](https://opendatalab.github.io/MinerU/quick_start/)
- 仓库：[github.com/opendatalab/MinerU](https://github.com/opendatalab/MinerU)

**官方硬件表（已核对 Quick Start）**

| Backend | 最低显存 | 内存 |
|---|---|---|
| `pipeline` | **4GB** | 最低 16GB，推荐 32GB+ |
| `*-engine`（vlm / hybrid） | **8GB** | 同上 |
| `*-http-client` | **2GB** | 16GB |

`pipeline` 可纯 CPU；`engine` 官方写明要 GPU。  
**参数量：该页未给。** 流水线是多小模型组合，不能写成「MinerU = 某 B」。HF 上的 MinerU2.5 1.2B 是可选 VLM 后端，与 `pipeline` 不是同一档。

第一期若自建开源解析，优先 `pipeline`（4GB / 可 CPU），不要一上来开 8GB 的 VLM engine。

#### Docling

- 仓库：[github.com/docling-project/docling](https://github.com/docling-project/docling)
- GPU 说明：[docling-project.github.io/docling/usage/gpu](https://docling-project.github.io/docling/usage/gpu/)
- 本环境未能抓取 GPU 页全文。**整条默认流水线的峰值 VRAM，官方页未在本次核到单一数字。**
- 它是可换 OCR 后端的文档库（RapidOCR / EasyOCR 等），本身不是一个 OCR 权重。

### 2.3 端到端 OCR-VLM（对照用，不进第一期主路径）

和「VLM 非必须」冲突：它们用视觉语言模型直接出字，显存和运维都按大模型算。

#### GOT-OCR2.0

- 论文：[arxiv.org/abs/2409.01704](https://arxiv.org/abs/2409.01704)（HTML：[arxiv.org/html/2409.01704v1](https://arxiv.org/html/2409.01704v1)）
- 仓库：[github.com/Ucas-HaoranWei/GOT-OCR2.0](https://github.com/Ucas-HaoranWei/GOT-OCR2.0)

**已核对论文原文：**

- 「The GOT, with **580M** parameters」
- encoder **约 80M**，decoder **0.5B**，合计约 580M
- 「easier to deploy on a consumer-grade GPU with **4G** memory」

仓库 README **未**重复给出独立 VRAM 表；4GB 以论文为准。

#### Surya

- 仓库：[github.com/datalab-to/surya](https://github.com/datalab-to/surya)

**已核对 README：**

- 「**650M** param OCR model」；后文「~650M params」
- 吞吐示例：RTX 5090 上约 5 pages/s；bench 写的是 **RTX 5090 (32 GB)**
- **最低显存：官方未给固定 GB 下限**，只说用 `DETECTOR_BATCH_SIZE` 控制检测占用
- 代码 Apache-2.0；**权重是修改过的 AI Pubs Open Rail-M**，README 写明研究/个人/融资或收入低于 500 万美元的创业公司可用，更大范围商用要走他们的定价页。第一期若商用，先读许可证。

#### DeepSeek-OCR

- 论文：[arxiv.org/abs/2510.18234](https://arxiv.org/abs/2510.18234)（HTML：[arxiv.org/html/2510.18234v1](https://arxiv.org/html/2510.18234v1)）
- 模型卡：[huggingface.co/deepseek-ai/DeepSeek-OCR](https://huggingface.co/deepseek-ai/DeepSeek-OCR)

**已核对论文：**

- DeepEncoder **约 380M**（SAM-base 80M + CLIP-large 300M）
- Decoder：**3B MoE，激活 570M**（文中 `DeepSeek3B-MoE-A570M`）
- 吞吐：单卡 **A100-40G** 约 **20 万+ 页/天**；20 节点 × 8×A100 约 3300 万页/天

**已核对 HF 模型卡：** 规模标 **3B params**。  
**最低消费级显存：论文和模型卡都未写「至少 X GB」。** 不得用社区「8GB 能跑」当官方数。官方给出的生产卡是 A100-40G。

#### olmOCR（AllenAI）

- 仓库：[github.com/allenai/olmocr](https://github.com/allenai/olmocr)

**已核对 README：**

- 「Based on a **7B** parameter VLM, so it requires a GPU」
- 本地推理：「Recent NVIDIA GPU … **at least 12 GB of GPU RAM**」
- 测过 RTX 4090 / L40S / A100 / H100；磁盘约 30GB

这是开源里官方写得最清楚的「要独立中高端 GPU」的档，第一期不上。

### 2.4 开源对照（只含官方数字）

| 名称 | 官方规模 | 官方硬件 / 显存 | 核验 | 第一期 |
|---|---|---|---|---|
| PP-OCRv5 mobile 产线 | 权重 det 4.7 + rec 16 MB | V100 峰值 **4190 MB** | 已核对 | **首选开源** |
| PP-OCRv5 server 产线 | det 84.3 + rec 81 MB | V100 峰值 **5402 MB** | 已核对 | 精度不够再升 |
| RapidOCR | 未给（随 Paddle 模型） | 未给 | — | 要 ONNX/CPU 时用 |
| EasyOCR | 未给 | 未给 | — | 备选 |
| Tesseract | 未给 | 官方按 CPU 库 | 已核对无 GPU 数 | 对照 |
| MinerU pipeline | 未给单一参数量 | **4GB** 起，可 CPU | 已核对 | 要版面时 |
| MinerU vlm-engine | 该页未给 | **8GB** | 已核对 | 不上 |
| GOT-OCR2.0 | **580M** | 论文称 **4GB** 消费卡 | 已核对论文 | 对照 |
| Surya | **650M** | 未给下限；示例 32GB 5090 | 已核对 | 许可证先过 |
| DeepSeek-OCR | encoder 380M + 3B MoE 激活 570M | 生产口径 A100-40G | 已核对 | 不上 |
| olmOCR | **7B** | **≥12GB** | 已核对 | 不上 |

---

## 3. 闭源（价格）

单位不要混：有的按**次**（一张图一次），有的按**页**（PDF 一页一次），有的按 **1000 页/图**。下表保留原文单位。

### 3.1 国内：通用 OCR（按次 / 按页）

#### 合合 TextIn 通用文字识别 — 已核对产品页

- 产品页：[textin.com/market/detail/recognize-document-3d1-multipage](https://www.textin.com/market/detail/recognize-document-3d1-multipage)
- 文档入口（同站）：[recognize-document-3d1-multipage 文档](https://www.textin.com/document/recognize-document-3d1-multipage)

| 套餐 | 价格 | 页面展示折合 | QPS | 有效期 |
|---|---|---|---|---|
| 50 页（新客） | 免费 | — | 1 | 1 年 |
| 500 页 | 29 元 | 0.058 元/页 | 1 | 1 年 |
| 5,000 页 | 250 元 | 0.05 元/页 | 2 | 1 年 |
| 10,000 页 | 400 元 | 0.04 元/页 | 2 | 1 年 |
| 30,000 页 | 1,110 元 | 0.037 元/页 | 5 | 1 年 |
| 50,000 页 | 1,750 元 | 0.035 元/页 | 5 | 1 年 |

页面同时标了划线价 **0.1 元/页**（未买套餐的按量价口径）。  
报关单专用 API 的套餐见 [model-survey.md](model-survey.md) 与 [报关单产品页](https://www.textin.com/market/detail/customs_declaration)，不要和通用识别混用一个接口。

#### 阿里云通用文字识别 — 已核对该页当时内容

- 价目：[help.aliyun.com/zh/ocr/product-overview/pay-as-you-go](https://help.aliyun.com/zh/ocr/product-overview/pay-as-you-go)

按量，单位 **元/次**，自然月阶梯（本环境抽到页面数字）：

| 月调用量 | 基础版 / 标准档 | 高精版 |
|---|---|---|
| ≤1 万 | 0.0825 | 0.225 |
| 1 万–10 万 | 0.0495 | 0.09 |
| 10 万–50 万 | 0.0415 | 0.054 |
| 50 万–100 万 | 0.0248 | 0.045 |
| >100 万 | 0.009 | 0.036 |

同页检索口径还有每月每 API **200 次**免费额度。实现前再打开链接确认档位名称（基础版 / 高精版）是否仍对应这两列。

#### 腾讯云通用印刷体识别 — 已核对计费文档

- 计费概述：[cloud.tencent.com/document/product/866/17619](https://cloud.tencent.com/document/product/866/17619)
- 本环境打开后落到的计费正文亦见产品 866 文档族（抓取页含下列原文数字）。

**后付费（元/次）：**

| 月调用量 | 单价 |
|---|---|
| 0–1 万 | **0.15** |
| 1 万–10 万 | **0.10** |
| 10 万–100 万 | **0.06** |
| ≥100 万 | 商务 |

**预付费资源包（1 年）：** 1000 次 120 元；1 万次 800 元；10 万次 5000 元；100 万次 3 万元；1000 万次 20 万元。  
开通后有 **1000 次/月** 免费额度（文档原文，多接口共享）。

低量后付费 0.15 元/次，明显高于 TextIn 套餐折合的 0.04 元/页。除非已在腾讯云且用量走资源包，否则不作为第一期默认。

#### 百度智能云通用文字识别标准版 — 已核对价格页

- 价格页：[cloud.baidu.com/product-price/ocr.html](https://cloud.baidu.com/product-price/ocr.html)

**按量（元/次，成功才计）：**

| 月调用量 | 单价 |
|---|---|
| ≤5 万 | 0.0050 |
| 5 万–10 万 | 0.0045 |
| 10 万–20 万 | 0.0040 |
| 20 万–50 万 | 0.0035 |
| 50 万–100 万 | 0.0030 |
| >100 万 | 0.0025 |

**次数包：** 1 万次 50 元；5 万 248；10 万 470；20 万 860；50 万 1850；100 万 3250；500 万 12000。

公开价里这是**最便宜的通用印刷体档**。它出的是字，不是报关单字段；表格和海关口径仍要我们自己做规则。适合「只要文字层、量很大、能接受通用 OCR 质量」。

#### 华为云通用文字识别 — 已核对计费样例

- 计费样例：[support.huaweicloud.com/price-ocr/ocr_12_0008.html](https://support.huaweicloud.com/price-ocr/ocr_12_0008.html)
- 完整价目以计算器为准：[huaweicloud.com/pricing.html#/ocr](https://www.huaweicloud.com/pricing.html?tab=detail#/ocr)

样例原文：`5,000*0.08=400元` → 按需 **0.08 元/次**。  
同页/相邻计费页出现 **10 万次套餐包 3,200 元**。  
阶梯全表以计算器为准，本文件不编造未出现的档位。

#### 火山引擎通用文字识别

- 产品：[volcengine.com/product/OCR](https://www.volcengine.com/product/OCR)
- 视觉智能计费文档号检索为 [docs/86081](https://docs.volcengine.com/docs/86081/1660260)

本环境未能稳定抓取「元/次」表格。**通用 OCR 按次单价标为待打开核对**，不要沿用口头「0.005 元/次」。  
按页的「智能文档解析 / LAS PDF 解析」仍见 [model-survey.md](model-survey.md) 的 0.02 / 0.04 元/页（亦为待打开核对）。

### 3.2 海外：按 1000 图 / 页（美元）

汇率不在本文件换算，避免再引入一层幻觉。实现时按当时牌价自行乘。

#### Google Cloud Vision OCR — 已核对价目

- [cloud.google.com/vision/pricing](https://cloud.google.com/vision/pricing)

| 功能 | 每月前 1000 | 1001–500 万 | 500 万以上 |
|---|---|---|---|
| TEXT_DETECTION | 免费 | **$1.50 / 千单位** | **$0.60 / 千单位** |
| DOCUMENT_TEXT_DETECTION | 免费 | **$1.50 / 千单位** | **$0.60 / 千单位** |

按图计；PDF 一页算一图。

#### AWS Textract Detect Document Text — 已核对价目

- [aws.amazon.com/textract/pricing](https://aws.amazon.com/textract/pricing/)
- 抓取页示例地域：US West (Oregon)

| | 首 100 万页 | 之后 |
|---|---|---|
| Detect Document Text（纯 OCR） | **$0.0015 / 页** | **$0.0006 / 页** |
| Analyze Document · Tables | $0.015 / 页 | $0.01 / 页 |
| Analyze Document · Forms | $0.05 / 页 | $0.04 / 页 |

报关单若要键值/表格，账单走 Analyze 档，不是 0.0015。数据出境单独评估。

#### Azure AI Vision Read

- 价目：[azure.microsoft.com/pricing/details/computer-vision](https://azure.microsoft.com/en-us/pricing/details/computer-vision/)
- 本环境抓到的是 **`$-` 占位**，**不引用任何美元数字**。请打开该页或定价计算器看当前区域价。
- 免费档原文有 **5000 transactions / 月**（F0）。

### 3.3 闭源价格对照（同量级心里有数）

以「1 万页清晰扫描、每页一次成功调用」为尺子，**只把已核对单价代入**，不是报价单：

| 服务 | 1 万页粗算 | 怎么算 | 来源 |
|---|---|---|---|
| TextIn 通用 1 万页包 | **400 元** | 套餐价 | [产品页](https://www.textin.com/market/detail/recognize-document-3d1-multipage) |
| 百度标准版按量 | **50 元** | 1 万 × 0.005 | [价格页](https://cloud.baidu.com/product-price/ocr.html) |
| 阿里基础版按量 | **825 元** | 1 万 × 0.0825 | [按量付费](https://help.aliyun.com/zh/ocr/product-overview/pay-as-you-go) |
| 腾讯印刷体后付费 | **1500 元** | 1 万 × 0.15 | [计费概述](https://cloud.tencent.com/document/product/866/17619) |
| 腾讯 1 万次资源包 | **800 元** | 包价 | 同上 |
| 华为按需 | **800 元** | 1 万 × 0.08 | [计费样例](https://support.huaweicloud.com/price-ocr/ocr_12_0008.html) |
| Google Vision | **$15** | 1 万 / 1000 × 1.50（已过免费 1000） | [Vision 价目](https://cloud.google.com/vision/pricing) |
| Textract 纯 OCR | **$15** | 1 万 × 0.0015 | [Textract 价目](https://aws.amazon.com/textract/pricing/) |

便宜不等于能抽报关单号。百度 0.005 元/次只保证「字」；海关字段仍要规则，扫描件版面差时错误会堆在规则层。

---

## 4. 和第一期怎么接

已冻结：扫描件走 OCR + 规则，不接 VLM。

```text
图片 / 扫描 PDF
    → 闭源：TextIn 通用 或 报关单专用（按页，无 GPU）
    → 或开源：PP-OCRv5 / RapidOCR（CPU 或一块 4–6GB 卡）
    → 文本块 + bbox 写入 DocumentIR
    → 锚点 / 正则 / 格式校验
    → 失败 → needs_review
```

接到仓库（实现时另开 Issue，本文不动代码）：

| 能力 | 路径 |
|---|---|
| 云 OCR HTTP | `src/docparse/adapters/parsers/ocr.py` |
| 本地 Paddle / Rapid | 同上或 `adapters/parsers/image.py` |
| 字段仍只改 | `src/docparse/schema/fields.yaml` |

选型口诀：

1. **没有 GPU、要快上线、单据是报关单** → TextIn 专用，通用识别垫底。
2. **有 CPU / 一块普通卡、数据不能出网** → PP-OCRv5 mobile，显存按官方 V100 峰值约 4.2GB 预留余量。
3. **只要海量廉价文字层** → 百度标准版按量，但必须加规则和抽检。
4. **不要**用 olmOCR / DeepSeek-OCR 当第一期 OCR，那是换皮 VLM。

---

## 5. 实现前再点一次的清单

1. [PaddleOCR v5 显存表](https://www.paddleocr.ai/latest/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html)
2. [PaddleX 模型体积](https://paddlepaddle.github.io/PaddleX/3.3/en/pipeline_usage/tutorials/ocr_pipelines/OCR.html)
3. [MinerU 硬件](https://opendatalab.github.io/MinerU/quick_start/)
4. [olmOCR README](https://github.com/allenai/olmocr)（确认仍 ≥12GB）
5. [TextIn 通用套餐](https://www.textin.com/market/detail/recognize-document-3d1-multipage)
6. [阿里云 OCR 按量](https://help.aliyun.com/zh/ocr/product-overview/pay-as-you-go)
7. [腾讯云 OCR 计费](https://cloud.tencent.com/document/product/866/17619)
8. [百度 OCR 价格](https://cloud.baidu.com/product-price/ocr.html)
9. [华为计费样例](https://support.huaweicloud.com/price-ocr/ocr_12_0008.html)
10. [Google Vision](https://cloud.google.com/vision/pricing) · [Textract](https://aws.amazon.com/textract/pricing/)
