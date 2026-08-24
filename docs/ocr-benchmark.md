# 云 OCR 实测报告（#60，为 #22 选型）

测试日期：2026-08-24。全部为真机云 API 调用，共 5 引擎 × 8 页 ≈ 40 次，费用 0（均在免费额度内）。

## 1. 结论（先看这个）

**推荐主路径：TextIn 通用文字识别（`recognize/multipage`），OCR + 自家规则，不采用任何垂直报关单 API 的成品字段。**

| 排名 | 引擎 | 一句话 |
|---|---|---|
| 1 | **TextIn 通用** | 唯一同时满足：旋转自动纠正 + 行结构完整 + 表头字段全命中；0.04–0.058 元/页 |
| 2 | 腾讯云通用印刷体 | 质量与 TextIn 同档，但 0.15 元/次（低量档），贵约 3 倍，作备选 |
| 3 | 百度标准版 | 最便宜（0.005 元/次），但 90° 旋转页直接乱码，需自建方向检测，第一期不选 |
| 4 | 阿里云通用 | 旋转页乱码 + 0.0825 元/次，无优势，不选 |
| - | TextIn 报关单专用 | 表头字段极准，但密集商品表行切分失败（见 §4.3），不作主路径 |

## 2. 测试范围

**样本（真机，本地，不入仓库）**：

| 样本 | 页数 | 形态 | 参照 |
|---|---|---|---|
| 半岛 SJ25084373-310795HKD.pdf | 2 | 扫描报关单，PDF 页横版（rot=270）、图竖版 3325×4676 | 采购系统识别结果 JSON（表头 10 字段 + 19 商品行） |
| 镇发 HKG25003373MUC 报关资料.pdf | 6 | 扫描商业单据（报关单 / 合同 / 箱单 / 发票），p1 内容旋转 90° | 无，仅可视化 + 耗时 |

**引擎**（均按上一期调研 #7 候选，密钥走环境变量，CLAUDE.md「模型只走云 API」约束满足）：

TextIn 通用、TextIn 报关单专用、百度通用标准版、阿里云通用（RecognizeGeneral）、腾讯云通用印刷体（GeneralBasicOCR）。

## 3. 结果总表

### 3.1 半岛 p1 表头字段命中（对采购系统参照，10 字段）

| 引擎 | 命中 | 明细 |
|---|---|---|
| TextIn 通用 | 10/10 | 全部精确出现 |
| 百度 | 10/10 | 同上 |
| 阿里云 | 10/10 | 同上 |
| 腾讯云 | 10/10 | 同上 |
| TextIn 报关单 | 7/10 精确 + 3/10 内容更全 | manualNo / grossWt / netWt / packNo / goodsPlace / consignorEname 精确；contrNo / markNo / cusTradeCountry 是参照 JSON 拆分口径不同（TextIn 给出更完整的原文），非识别错误 |

### 3.2 镇发 p1（内容旋转 90° 的扫描页）——分化点

| 引擎 | 输出行数 / 字符量 | 结果 |
|---|---|---|
| TextIn 通用 | 91 行 / 588 字符 | 正常读出「中华人民共和国海关出口货物报关单」「境内发货人（914419005645626079）」等 |
| 腾讯云 | 94 行 / 589 字符 | 同样正常，返回 angle=89.99° |
| 百度 | 24 行 / 156 字符 | **乱码**：`5)9706265e00014419(`、`朱达锦发律子有限公问`、单字碎片 |
| 阿里云 | 25 行 / 91 字符 | **乱码**：`—片飞鑫喷94410056466N6O9` |

TextIn 返回 `angle=90` 并自动转正；百度 / 阿里云无整图方向纠正能力。半岛两页因 PDF 自带 rotation 元数据、渲染时已转正，所以四家通用引擎都能读——**真正的风险点是无旋转元数据的横放内容**（镇发 p1 正是这种）。

### 3.3 半岛商品表行结构（决定规则链路能否复用）

参照 19 个商品行。通用引擎的行级输出按 y 聚类：

| 引擎 | p1 含 HS 码行带 | p2 含 HS 码行带 | 行结构 |
|---|---|---|---|
| TextIn 通用 | 10 | 15 | 每行的项号 / HS / 品名 / 数量 / 单价 / 总价 / 原产国都在同一 y 带，列对齐清晰 |
| 百度 | 9 | 15 | 行结构保留（但见 §3.2 旋转盲区） |
| 阿里云 | 11 | 15 | 行结构保留（同上） |
| 腾讯云 | 10 | 11 | p2 行带偏少，HS 码漏 4 个 |

### 3.4 耗时（8 页均值 / 最大值，秒级含网络）

| 引擎 | 平均 ms | 最大 ms | 备注 |
|---|---|---|---|
| 腾讯云 | 1482 | 2472 | 最稳 |
| 百度 | 1576 | 5643 | 大图（3325×4676）明显变慢 |
| TextIn 通用 | 1920 | 9585 | p2 大图 9.6s 是离群值，其余 0.6–1.7s |
| 阿里云 | 1915 | 3382 | 均匀 |
| TextIn 报关单 | 2721 | 5413 | 逐页模式 |

## 4. 关键发现

### 4.1 旋转处理是选型分水岭

Issue #22 写的「图是竖版页是横版」在半岛样本上表现为 PDF 旋转元数据（PyMuPDF 渲染时自动转正），但镇发 p1 证明还存在**无元数据的内容旋转**。TextIn / 腾讯自带检测与纠正（返回 angle）；百度 / 阿里云没有，直接乱码。若选百度必须自己先做方向检测（又回到「要一个模型先转图」的问题），第一期不值得。

### 4.2 「通用 OCR + 规则」路线成立

TextIn 通用在半岛两页给出 172 / 210 个带 bbox 的行级文本块，商品表每行的 9 个格子都在同一 y 带、列坐标规律（项号 x≈70、HS+品名 x≈116、数量 x≈768、单价 x≈929、原产国 x≈1088…），按 y 聚类 + 列区间切分即可重建 19 个商品行，直接接现有 xlsx 规则链路（版面 KV + 表头表）。这正是 Epic #11 冻结的「OCR + 规则，不走 VLM」。

### 4.3 TextIn 报关单专用 API：表头可用、商品行不可用

- 表头 69 字段全返回且与海关字段目录对齐，7 个可比字段精确。
- 商品表行切分失败：19 行被并成 2–3 行（`product_id` 一个字段里塞了 5 个 HS 码），`multipage=1&combine_document=1` 整 PDF 直传也一样。密集表格的行检测是其短板，不能当主路径。
- 可留作后续「表头兜底 / 交叉校验」的候选项，不进第一期主链路。

## 5. 费用粗算（引用 ocr-survey.md 已核对单价）

| 引擎 | 单价 | 1 万页 |
|---|---|---|
| TextIn 通用 | 0.04–0.058 元/页（套餐） | 400–580 元 |
| 百度标准版 | 0.005 元/次 | 50 元 |
| 阿里云基础版 | 0.0825 元/次 | 825 元 |
| 腾讯云后付费 | 0.15 元/次 | 1500 元 |

百度的 3 倍价差买不回旋转盲区的工程成本，主路径按效果选 TextIn。

## 6. 对 #22 的落地建议

```text
PDF（文字层 / 扫描）
  → PyMuPDF 逐页出图（渲染时应用页面 rotation）
  → 有文字层：直接抽字块（现有 pdf.py 已能）
  → 无文字层：TextIn 通用 recognize/multipage（octet-stream 传 JPEG）
  → 行级 text + bbox 写入 DocumentIR.pages[].blocks
  → 复用 xlsx 的版面 KV / 表头表 / 组装 / 校验
  → TextIn 返回的 page.angle 留档；乱码 / 低置信 → needs_review
```

- 引擎适配收在 `src/docparse/adapters/parsers/ocr.py`（本次 benchmarks/ocr/engines.py 的 TextinGeneralEngine 可直接迁移，含重试与 40306 QPS 限流处理）。
- 图（jpg / png）与扫描 PDF 页走同一入口。

## 7. 验收材料（本地 out/，不入库）

| 材料 | 路径 |
|---|---|
| 每引擎识别框画回原图 | `benchmarks/ocr/out/viz/<引擎>/<页>.png`（32 张） |
| 引擎原始返回 | `benchmarks/ocr/out/raw/<引擎>/<页>.json` |
| 归一化结果（text/boxes/fields） | `benchmarks/ocr/out/results/<引擎>/<页>.json` |
| 半岛参照字段 | `benchmarks/ocr/out/real/peninsula-reference.json` |

人工验收建议：先看 `viz/textin-general/peninsula-p1.png`（框是否贴合）、再对比 `viz/baidu-general/zhenfa-p1.png`（乱码页框稀疏）。

## 8. 复现

```bash
# 密钥见 benchmarks/ocr/README.md（环境变量，不入库）
python -m benchmarks.ocr.run real-render       # 渲染真机页
python -m benchmarks.ocr.run call --engine all --scope real
python -m benchmarks.ocr.run report
```

## 9. 以后新样本 / 新引擎改哪

| 场景 | 改哪 | 动不动 Python |
|---|---|---|
| 新增真机样本目录 | 环境变量 `DOCPARSE_OCR_DEMO_DIR`，`benchmarks/ocr/real.py` 加文件名 | 少量（加一个 RealSample 条目） |
| 换 / 加云 OCR 引擎 | `benchmarks/ocr/engines.py` 加一个类（recognize → OcrResult），`ALL_ENGINES` 注册 | 是（一个类 + 一个解析函数） |
| 夹具换版式 / 字段 | `benchmarks/ocr/fixtures.py` 的 FixtureSpec | 否（改数据即可） |
| GT 字段与 TextIn 字段对照 | `benchmarks/ocr/gt_field_map.py` | 否 |
| 指标口径（归一化规则） | `benchmarks/ocr/metrics.py` 的 normalize | 是（一处） |
