# 云模型与解析服务调研

对应 Issue：[#1](https://github.com/Baldwinzc/docparse/issues/1)
流程图：[flow.html](flow.html)
模块地图：[modules.md](modules.md)
OCR 引擎对照（开源显存 / 闭源价格）：[ocr-survey.md](ocr-survey.md)

> **阅读约定**
>
> - 主链路仍是固定流水线，本文件只回答「云 API 用哪一层、哪一家」。
> - 每个数字旁边都有来源链接。能抽出页面原文的标 **已核对**；页面为前端渲染、本环境未读到表格的标 **待打开链接核对**，不得当成已核实合同价。
> - 下单、限流、套餐折扣以各家控制台为准。价格会变，实现前再点开一次链接。

## 1. 结论（先看这个）

火山引擎**能覆盖我们的需求**，但要拆成两条产品，不要混成「一个模型」：

| 层级 | 火山对应产品 | 计费 | 第一期角色 |
|---|---|---|---|
| B 通用文档解析 | LAS「PDF 文档解析（豆包）」 | 按页 | 扫描件 / 未知版式还原 |
| C 语义抽取 / 消歧 | 方舟豆包视觉与文本模型 | 按 token | 规则抽不到时的兜底 |

报关单扫描件的准确率主力，应另评 **合合 TextIn 报关单专用 API**（按页套餐，字段已按海关单设计）。不要把每一页都丢给方舟旗舰 VLM。

第一期推荐组合：

1. Excel / 文本 PDF：继续走本地 parser + 规则（成本≈0）
2. 报关单扫描件：评测 [TextIn 报关单](https://www.textin.com/market/detail/customs_declaration)
3. 通用 PDF / 图片还原：火山 LAS [PDF 文档解析（豆包）](https://docs.volcengine.com/docs/6492/2172371)
4. 字段消歧 / 未知模板：方舟 `doubao-seed-2.0-lite`（或控制台当时推荐的 lite），接口见 [文档理解](https://docs.volcengine.com/docs/82379/1902647) + [结构化输出](https://docs.volcengine.com/docs/82379/1568221)
5. 旗舰 `doubao-seed-2.1-pro`：只打难例和抽检，不跑全量

不在第一期做：Azure / Google 报关单 Custom、本地部署大模型、Agent 编排。

---

## 2. 三层能力，不要横向比「哪个大模型最强」

| 层 | 输入 → 输出 | 计费 | 准确率来源 | 接到现有代码 |
|---|---|---|---|---|
| A 垂直单据 OCR | 报关单/发票图 → 业务字段 JSON | 按页 / 按次 | 字段先验最强 | `adapters/parsers/ocr.py` |
| B 通用文档解析 | PDF/图 → 阅读顺序、表格、Markdown、bbox | 按页 | 版面还原 | `adapters/parsers/pdf.py` / `image.py` |
| C LLM / VLM | 局部文本或截图 → Schema JSON | 按 token | 弹性强、最不稳 | `adapters/llm/openai_compat.py` |

和流水线的关系（已对齐，不改）：

```text
规则能抽到        → 不调云
扫描件 / 复杂版式  → A 或 B
多候选 / 未知版式  → C
仍不确定          → needs_review
```

四维优先级：**准确率 > 成本 > 时延 > 并发**。并发和时延靠拆页、异步、限流解决，不靠换更贵的旗舰模型。

---

## 3. A 层：垂直单据 OCR

### 3.1 合合 TextIn「海关进出口货物报关单识别」— 已核对套餐页

这是目前找到的、对中国进出口报关单**开箱即用**的专用 API。

| 项 | 内容 | 来源 |
|---|---|---|
| 产品页 | 海关进出口货物报关单识别 | [textin.com/market/detail/customs_declaration](https://www.textin.com/market/detail/customs_declaration) |
| API 文档 | 字段、入参、错误码 | [textin.com/document/customs_declaration](https://www.textin.com/document/customs_declaration) |
| 接口 | `POST https://api.textin.com/ai/service/v1/customs_declaration` | 同上 API 文档 |
| 认证 | 请求头 `x-ti-app-id`、`x-ti-secret-code` | 同上 |
| 格式 | JPEG / PNG / BMP / PDF / TIFF / WebP，或公网 URL | 同上 |
| 限制 | 单文件 ≤ 10MB；边长 20–10000 px | 同上 |
| 可选参 | `multipage`、`combine_document`、`split_price`、`split_product_info` | 同上 |
| 超限 | `40306` = QPS 超限，文档写明不要立即重试 | 同上 |

产品页套餐（有效期 1 年，本环境 **WebFetch 已读到页面原文**，**已核对**）：

| 套餐 | 价格 | 折合 | QPS |
|---|---|---|---|
| 100 页（新客） | 免费 | — | 1 |
| 5,000 页 | 250 元 | 0.05 元/页 | 2 |
| 10,000 页 | 400 元 | 0.04 元/页 | 2 |
| 50,000 页 | 1,750 元 | 0.035 元/页 | 5 |
| 100,000 页 | 3,000 元 | 0.03 元/页 | 5 |
| 500,000 页 | 12,500 元 | 0.025 元/页 | 10 |

来源：[产品页](https://www.textin.com/market/detail/customs_declaration)。页面同时显示划线价「0.1 元/页」，以上为现价。

能力边界（来自 API 文档，不是价格）：

- 区分进口 / 出口报关单
- 表头含海关编号、收发货人、关别、日期、运输、监管方式、毛净重等
- 明细 `item_list`：HS、品名规格、数量单位、单价总价币制、原产国、征免
- 文档宣称可拆价格、拆品名、合并多页表格

**准确率：** 产品页只写「识别准确率行业靠前」，**没有可引用的第三方同测数字**。厂商宣传的「印刷体 99.7%」未在本次打开的产品页/API 页中抽出，**不写入结论**。上线前必须用需求方样本盲测。

**并发：** 套餐绑定 1–10 QPS，见上表。超限错误码见 [API 文档](https://www.textin.com/document/customs_declaration) 的 `40306`。

### 3.2 阿里云「单据票证信息抽取」— 无报关单预置

[按量付费说明](https://help.aliyun.com/zh/document-mind/product-overview/pay-as-you-go)（本环境抽到页面数字，**已核对该页当时内容**）：

| 能力 | 公开档位（元/页） |
|---|---|
| 大模型文档解析 · 基础 | 0.02 |
| 大模型文档解析 · 增强 | 0.04 |
| 电子文档解析 | 0.005 |
| 单据票证信息抽取 | 0.04 / 0.035 / 0.03 / 0.025 / 0.02（按月用量递减） |
| 自定义 KV | 0.12 起，高用量可到 0.03 |

官方预置清单**没有**中国海关报关单，做报关单要自学习标注。适合「已经在阿里云、版式可枚举、愿意标数据」。第一期不作为报关单主路径。

产品入口：[文档智能](https://www.aliyun.com/product/ai/docmind)

---

## 4. B 层：通用文档解析

### 4.1 火山引擎 LAS「PDF 文档解析（豆包）」

这是「~0.02–0.04 元/页」对应的**具体产品**，不是方舟大模型按 token 的价。

| 项 | 链接 |
|---|---|
| 算子说明 | [docs.volcengine.com/docs/6492/2172371](https://docs.volcengine.com/docs/6492/2172371) |
| 大模型 / 算子计费 | [docs.volcengine.com/docs/6492/1544808](https://docs.volcengine.com/docs/6492/1544808) |
| 算子库更新 | [volcengine.com/docs/6492/1798370](https://www.volcengine.com/docs/6492/1798370) |
| 视觉智能「智能文档解析」计费（另一条产品线，易混淆） | [docs.volcengine.com/docs/86081/1804813](https://docs.volcengine.com/docs/86081/1804813) |
| OCR 产品总入口 | [volcengine.com/product/OCR](https://www.volcengine.com/product/OCR) |

公开文档检索中反复出现的单价（**待打开上表链接核对原文表格**，本环境抓取官方页为空，未读到 HTML 表格）：

| 模式 | 检索一致的单价 | 核验 |
|---|---|---|
| `normal`（默认，更快） | **0.02 元/页** | 待打开 [2172371](https://docs.volcengine.com/docs/6492/2172371) 与 [1544808](https://docs.volcengine.com/docs/6492/1544808) |
| `detail`（精细 / 深度思考） | **0.04 元/页** | 同上 |

计费口径（检索摘要，同样请打开计费页确认）：按 PDF/图片**智能分段后的页数**计，不是按原始文件个数。过长页可能被切开再计页。

能力（来自算子文档检索，实现前打开 [2172371](https://docs.volcengine.com/docs/6492/2172371) 核对）：

- 视觉还原标题、表格、公式、图片区域
- 可返回 bbox 与图片 URL
- 2026 年更新：除 PDF 外支持 PNG / JPEG / BMP / WebP；页数上限检索称 200→400，长文档用 `start_page` / `num_pages` 切片

**为何第一期仍推荐它：** 和方舟同一账号体系、国内合规、按页成本可预期、输出带版面，适合送进规则抽取。它**不是**报关单字段 API。

### 4.2 不要和「方舟文档理解」算成同一个价

[方舟文档理解](https://docs.volcengine.com/docs/82379/1902647) 是把 PDF 拆成页图，再送给豆包视觉模型，走 **token 账单**。适合问答、抽字段、小批量难例。大批量「先还原再抽」应走 4.1 的按页算子。

### 4.3 Azure / Google（第一期不接）

| 厂商 | 官方价目 | 本环境 |
|---|---|---|
| Azure Document Intelligence | [azure.microsoft.com/pricing/details/ai-document-intelligence](https://azure.microsoft.com/pricing/details/ai-document-intelligence/) | 抓取结果是 `$-` 占位，**没有可用的官方数字可引用** |
| Google Document AI | [cloud.google.com/document-ai/pricing](https://cloud.google.com/document-ai/pricing) | 页面过长被截断，**请直接打开价目表** |

两者都**没有**中国报关单预置模型，要走 Custom。数据出境和单价都不适合当第一期主路径。第三方文章里常见的「Layout $10 / Custom $30 每千页」**未在本次官方页抓取中核实**，这里不采用。

---

## 5. C 层：方舟豆包（按 token）

### 5.1 官方入口

| 文档 | 链接 |
|---|---|
| 模型价格 | [docs.volcengine.com/docs/82379/1544106](https://docs.volcengine.com/docs/82379/1544106) |
| 价格说明（同源另一文档号） | [docs.volcengine.com/docs/82379/1099320](https://docs.volcengine.com/docs/82379/1099320) |
| 模型列表 | [docs.volcengine.com/docs/82379/1330310](https://docs.volcengine.com/docs/82379/1330310) |
| 文档理解 | [docs.volcengine.com/docs/82379/1902647](https://docs.volcengine.com/docs/82379/1902647) |
| 结构化输出 | [docs.volcengine.com/docs/82379/1568221](https://docs.volcengine.com/docs/82379/1568221) |
| File API | [docs.volcengine.com/docs/82379/1885708](https://docs.volcengine.com/docs/82379/1885708) |
| 豆包产品页 | [volcengine.com/product/doubao](https://www.volcengine.com/product/doubao) |
| OpenAI 兼容基座 | `https://ark.cn-beijing.volces.com/api/v3`（见方舟文档） |

现有代码 `OpenAICompatClient` 只改 `DOCPARSE_LLM_BASE_URL` / `DOCPARSE_LLM_MODEL` / `DOCPARSE_LLM_API_KEY` 即可对上方舟。

### 5.2 公开检索中的标价（元 / 百万 token）

本环境打开价格页得到空 HTML（前端渲染），**下表全部是「待打开 [1544106](https://docs.volcengine.com/docs/82379/1544106) 核对」**。检索与产品页口径一致，但不是本仓库抓到的原文表格。

| 模型（文档中的常见写法） | 输入（约，≤32k） | 输出（约） | 第一期用法 |
|---|---|---|---|
| `doubao-seed-2.0-mini` | 0.20 | 2.00 | 分类、极简消歧、高 QPS |
| `doubao-seed-2.0-lite` | 0.60 | 3.60 | **默认兜底** |
| `doubao-seed-2.1-turbo` | 3.00 | 15.00 | 复杂页、要速度 |
| `doubao-seed-2.1-pro` | 6.00 | 30.00 | 难例 / 抽检，禁止全量 |

补充：

- 超过 32k / 128k 输入，lite 会按档上浮，以价格页分档为准。
- 2.1-pro 产品页检索口径与 [1099320](https://docs.volcengine.com/docs/82379/1099320) 一致写过「6 元输入 / 30 元输出」。
- 旧视觉 SKU（如 `doubao-seed-1-6-vision-*`、`doubao-1-5-vision-pro-*`）在模型列表中有下线窗口，**不要写死进配置**。实现时打开 [模型列表](https://docs.volcengine.com/docs/82379/1330310) 看当前推荐 ID。

### 5.3 为何不能全量走 Pro

按页解析是「一页一个固定价」；VLM 是「一页图可能几千到一两万 input token」。同一页扫描件：

- LAS `normal`：检索口径 0.02 元（[计费页](https://docs.volcengine.com/docs/6492/1544808)）
- 2.1-pro：若输入 8k token + 输出 1k token，按上表粗算约 `8×0.006 + 1×0.030 = 0.078` 元，已是按页解析的数倍；图更大或整本送入会再翻

所以 C 层只吃「规则 / A / B 之后仍不确定」的局部片段。

### 5.4 业务侧旁证（不是报价）

2026 年火山为欧坚 / 云贸通做报关智能体，公开表述是「文档理解 + 大模型 + 规则校验」，不是单模型端到端。来源：[杨浦区通稿](https://www.shyp.gov.cn/shypq/xwzx-bmdt/20260316/501606.html)。说明这条链路在业务上成立，也说明规则校验不可省。

---

## 6. 并发、时延、成本怎么设计

### 6.1 并发

各家默认 QPS 都不高，必须在我们这边拆池：

```text
解压池（CPU，严限，防 zip bomb）
  → 解析池（A/B 按页并行，独立限流）
  → LLM 池（C 单独更严的 QPS / 预算）
  → 校验（本地，不占云配额）
```

已知的官方/产品页并发线索：

| 服务 | 线索 | 来源 |
|---|---|---|
| TextIn 报关单 | 套餐 1 / 2 / 5 / 10 QPS | [产品页](https://www.textin.com/market/detail/customs_declaration) |
| TextIn 超限 | `40306`，不要立刻重试 | [API 文档](https://www.textin.com/document/customs_declaration) |
| 方舟 | 默认限额在控制台，需单独提额 | [方舟文档中心](https://docs.volcengine.com/docs/82379/1330310) |
| LAS 按页解析 | 以算子文档 / 控制台为准 | [2172371](https://docs.volcengine.com/docs/6492/2172371) |

工程要求（实现对应 Issue 时落地，本文只定原则）：

- A/B 与 C **分开限流、分开重试**
- 429 / `40306` 用抖动退避，禁止打满
- 同步 HTTP 只给小文件调试；生产走 job
- 按文件 hash 缓存解析结果

### 6.2 时延（量级，不是 SLA）

没有各家公开的报关单 P99。按链路经验排，实现后用样本实测：

| 步骤 | 量级 |
|---|---|
| Excel / 文本 PDF 本地 | 几十到两百 ms |
| 按页 OCR / 文档解析 | 约 0.5–3 s/页，可并行 |
| 单次 LLM 消歧 | 约 1–5 s |
| 整本 VLM | 十几秒到一分钟，易超时 |

### 6.3 成本怎么估（公式，不用拍脑袋）

先打开对应价目，再代入真实页数：

```text
一票成本 ≈
    0                             × Excel/文本页
  + P_ocr                         × 报关单扫描页     （TextIn 套餐折合）
  + P_parse                       × 其他扫描页       （LAS normal/detail）
  + (in_tokens/1e6 × Pin
     + out_tokens/1e6 × Pout)     × LLM 调用次数
```

示例（**仅演示数量级**，单价以链接为准）：

假设一票 = 1 份 Excel + 8 页报关单扫描，规则吃掉 Excel，8 页走 TextIn 1 万页包折合 0.04 元/页，LLM 只对 1 个字段调 lite：

- OCR：8 × 0.04 = 0.32 元（[TextIn 产品页](https://www.textin.com/market/detail/customs_declaration)）
- LLM：若 2k in + 0.2k out，按 lite 0.6 / 3.6 粗算约 0.002 元（[方舟价格](https://docs.volcengine.com/docs/82379/1544106)，待核对）
- 合计约 **0.32 元/票** 量级

若 8 页全部当图丢给 2.1-pro，成本会高出数倍，且不一定更准。

日 1000 票、每票 8 页扫描：仅 OCR 约 320 元/天。全量旗舰 VLM 没有固定页价，不要用这个量去赌。

---

## 7. 准确率怎么验收（比换模型重要）

样本未到之前，任何「谁更准」都是假的。样本到了按字段打这张表：

| 指标 | 定义 |
|---|---|
| Exact Match | 标准化后与人工标完全一致 |
| 自动通过率 | `accepted` 且未进复核 |
| 自动通过错误率 | **最重要**：放过去的里面有多少是错的 |
| 单页时延 P50/P95 | 解析 + 抽取 |
| 单页 / 单票成本 | 按账单回算 |

对照组（同一批脱敏件，禁止只测清晰件）：

1. 仅规则
2. TextIn 报关单
3. LAS 解析 + 规则
4. LAS 解析 + 规则 + lite 消歧
5. 仅 2.1-pro（作为上限对照，不作为生产默认）

没有证据位置的结果，不得标 `accepted`（已写进 [CLAUDE.md](../CLAUDE.md)）。

---

## 8. 接到仓库的位置（实现时另开 Issue）

| 能力 | 改哪里 | 不要改 |
|---|---|---|
| TextIn 报关单 / 发票 | `src/docparse/adapters/parsers/ocr.py` | pipeline 编排 |
| LAS / 方舟按页还原 | `adapters/parsers/pdf.py`、`image.py` | domain IR 形状（除非缺字段） |
| 豆包 lite / turbo | `.env` + `adapters/llm/openai_compat.py` | 不要写死模型 ID 在抽取逻辑里 |
| 字段允许哪些抽取器 | `src/docparse/schema/fields.yaml` 的 `extractors` | 不要在 runner 里 if-else 厂商名 |

建议的字段抽取顺序（写入 YAML，不写死代码）：

```text
rule → textin（仅报关单/发票类）→ llm → human
```

后续拆 Issue 的顺序见 [modules.md](modules.md)。本 Issue 只交文档。

---

## 9. 第一期明确不做

- 不把整份压缩包塞进 VLM
- 不在未评测前把 TextIn 或豆包定为「唯一真相」
- 不上 LangChain / LangGraph
- 不部署本地大模型
- 不接 Azure / Google 做中国报关单主路径
- 不把检索到但未打开原文的价格写进计费代码

---

## 10. 实现前再点一次的清单

开通或写适配器之前，用浏览器打开并截图存档：

1. [TextIn 报关单套餐](https://www.textin.com/market/detail/customs_declaration)
2. [TextIn 报关单 API](https://www.textin.com/document/customs_declaration)
3. [LAS 算子 2172371](https://docs.volcengine.com/docs/6492/2172371)
4. [LAS 计费 1544808](https://docs.volcengine.com/docs/6492/1544808)
5. [方舟价格 1544106](https://docs.volcengine.com/docs/82379/1544106)
6. [方舟模型列表](https://docs.volcengine.com/docs/82379/1330310)
7. [方舟文档理解](https://docs.volcengine.com/docs/82379/1902647)
8. 方舟控制台当前模型 ID 与 QPS 配额

把当时的型号 ID、单价、QPS 记回本文件的「已核对」列，再开实现 Issue。
