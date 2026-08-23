# 模块地图

流程图见 [flow.html](flow.html)。OCR 引擎对照（开源显存 / 闭源价格）见 [ocr-survey.md](ocr-survey.md)（#7）。后期每个模块单独建 Issue，在对应 worktree 里实现，不要一次改整条链路。

```text
docparse/
├── docs/                      设计、流程、模块说明
├── src/docparse/
│   ├── api/                   HTTP 入口（收文件 + caller → pipeline）
│   ├── cli.py                 本地命令行
│   ├── config.py              环境变量
│   ├── domain/                任务 / IR / 字段（稳定契约）
│   ├── schema/                字段表 YAML + 版面词表 YAML + 码表 YAML + sheet 角色 YAML
│   ├── pipeline/              固定步骤编排
│   │   └── steps/             与主链路节点一一对应
│   ├── extraction/            分类、抽字段、校验
│   └── adapters/
│       ├── parsers/           ZIP / PDF / Excel / 图片 / 文本
│       ├── llm/               云 API
│       ├── jobs/              任务存储（内存 + Postgres 预留）
│       └── files/             文件存储（内存 + S3 预留）
└── tests/
```

## 主链路 → 代码

| 流程图节点 | 实现位置 | 本阶段状态 | 后期 Issue 建议 |
|---|---|---|---|
| 接入与安全检查 | `pipeline/steps/ingest.py` | 骨架：大小 / 空文件 | 补 MIME、真实类型 |
| 安全解压 | `adapters/parsers/unpack.py` + `steps/unpack.py` | 骨架：zip 穿越 / 层数 / 体积 | rar/7z、加密包 |
| 按文件类型解析 | `adapters/parsers/` | 文本可用；Excel 全 sheet + 框表/冒号/双行表头/KV/值域（#9 #15 #29）；PDF 需可选依赖；图片未接 OCR | PDF / 扫描件 OCR |
| 统一文档 IR | `domain/ir.py` | Cell 含合并/边框/公式；Sheet 含 key_values / tables / role | 非必要不改契约名 |
| 文档分类 | `extraction/classify.py` + `sheet_role.py` | 文件类型仍占位；sheet 角色看标题/KV/表头（#16） | 新角色加 YAML |
| 字段抽取 | `extraction/head_map.py` + `goods_map.py` + `assemble.py` + `fields.py` | 单 sheet BOX/KV → 表头（#17）；TABLE → 货行并跨表补空（#18）；多摊收成一张报关单（#19）；旧锚点仍给无 sheet 的文本 | PDF 同组装交 #23 |
| 标准化与校验 | `extraction/validate.py` | 骨架：格式 / 证据；业务闸未接 | 规则清单见 [validate-rules.md](validate-rules.md)，确认后由 #20 执行 |
| 包级对账 | `pipeline/steps/reconcile.py` | 同名字段冲突 | 金额、单号跨文件 |
| 自动通过 / 待复核 | `pipeline/steps/route_review.py` | 只打状态 | 复核页另开 Issue |
| FastAPI 交单 | `api/routes.py` + `pipeline/runner.py` | `POST /v1/jobs` 交 `declaration` + `reviews`（#21） | PDF / zip 拼单不改路由 |
| 对眼页 | `api/static/review.html` + `GET /v1/schema` | 只画报关单 + reviews（#44） | 不渲染 IR |
| 持久化接口 | `adapters/jobs/` `adapters/files/` | 内存实现；Postgres/S3 抛未实现 | 需要跨进程时再做 |
| 云 LLM | `adapters/llm/openai_compat.py` | 未配 Key 则跳过 | 换供应商只改这里 |

云 API 分层、报价来源和第一期组合见 [model-survey.md](model-survey.md)（#1）。

## 推荐拆 Issue 的顺序

需求方 case 和字段清单到位后，按这个顺序拆，一次一个 worktree：

1. 字段表按真实清单改 `schema/fields.yaml`（#12）
2. PDF 文本层解析（`parsers/pdf.py`）
3. Excel 框表解析（`parsers/excel.py` + `layout.py`，#9）
4. 报关单规则抽取（锚点 / 表头）
5. LLM API 兜底（提示词 + Schema）
6. 图片 / 扫描件云 OCR 或 VLM
7. 跨文件对账规则
8. Postgres + 对象存储
9. 人工复核页（如需要）

## 模块接口约定

Excel 框表拆分（#9 / #15 / #29）：`adapters/parsers/layout.py` 从格子拆 `key_values` / `tables`，还不映射报关字段。词表在 `schema/layout_vocab.yaml`（#13）：BOX 框表标签、KV 商业单据键、TABLE 表头词。`layout.py` 读文件不再维护 Python 常量。刀法：冒号变体、日期时间不切、双行表头并入 `headers`（`header_rows` 可多行）。多候选先按 id 上的 `value:` 滤形状，再按 `same_cell` > `below` > `right` 决胜。新 xlsx 往哪加见 #31。本地对眼用 `python -m docparse.cli layout file.xlsx`。

名称转 code（#14）：`schema/code_tables.yaml` 全量转录 + `load_code_tables().lookup(表, 名称)`。精确匹配，未知返回空。海关口岸（四位）与港口代码分开。xlsx 原件不入库。俗称别名交 #27。

sheet 角色（#16）：`schema/sheet_roles.yaml` + `extraction/sheet_role.py`。每张 sheet 标 `draft` / `packing` / `invoice` / `contract` / `auxiliary` / `unknown`，并带 `consume`（primary / supplement / exclude）。辅助表和 unknown 的 KV / table 留在 IR，不进下一张报关单。新叫法加 YAML，不按公司写分支。见 [sheet-roles.md](sheet-roles.md)。

表头映射（#17）：`extraction/head_map.py` 吃已拆 `key_values`，按 `fields.yaml` 的 `anchors` / `head_map` 写成 TdecHead 候选。一次一张 sheet，多 sheet 并排放，不覆盖。`agent*` 不从文件填。中文值不转 code。名称+10 位海关代码用 `trailing_code`。运费 / 航次 / 唛码拆分见 #34–#36，发票号槽位见 #37。本地对眼：`python -m docparse.cli head file.xlsx`。见 [head-map.md](head-map.md)。

商品映射（#18）：`extraction/goods_map.py` 吃已拆 `tables`，按 `fields.yaml` 的 `goods.anchors` / `goods_map` / `goods_master` 写成货行。先选主货表，其它可消费 sheet 只补空；对不上的行标来源收成补充项。`auxiliary` / `unknown` 不读。重量未区分当净重，无毛重列再抄一份到毛重。申报要素原文进 `gmodel`，不编 `0|0|...`。箱数不加字段。本地对眼：`python -m docparse.cli goods file.xlsx`。见 [goods-map.md](goods-map.md)。

整单组装（#19）：`extraction/assemble.py` 按 `fields.yaml` 的 `assembly` 收成一张报关单。有 `draft` 抄草单，商业单据只补空并核件毛净；无草单只抄能确定的商业事实，`customs_only` 空着复核。名称转 code；转不出留原文。`agent*` 只来自调用参数。表头只有净重时视同重量，不抄进毛重。本地对眼：`python -m docparse.cli declare file.xlsx`。见 [assemble.md](assemble.md)。

FastAPI 交单（#21）：`POST /v1/jobs` 与 `cli declare` 走同一条 pipeline。调用方参数跟 `caller_params` 走，不写死四个 agent。响应是 Job + `result.declaration` + `result.reviews`。见 [api.md](api.md)。

对眼页（#44）：`GET /review` 静态页 + `GET /v1/schema`。只画报关单和复核证据，不渲染 IR。见 [review.md](review.md)。

抽取后校验（#20）：规则先写在 [validate-rules.md](validate-rules.md) 给业务确认。位数 / 正则 / 容差确认后再进数据文件，引擎只执行，不编造、不改值。

每个 parser 只做一件事：`bytes + filename → DocumentIR`。

每个 pipeline step 只改 `PipelineContext`，不直接读写磁盘。

新存储后端：实现 Protocol，在 factory 注册，配置改 `DOCPARSE_JOB_STORE` / `DOCPARSE_FILE_STORE`。
