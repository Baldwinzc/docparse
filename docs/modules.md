# 模块地图

流程图见 [flow.html](flow.html)。后期每个模块单独建 Issue，在对应 worktree 里实现，不要一次改整条链路。

```text
docparse/
├── docs/                      设计、流程、模块说明
├── src/docparse/
│   ├── api/                   HTTP 入口
│   ├── cli.py                 本地命令行
│   ├── config.py              环境变量
│   ├── domain/                任务 / IR / 字段（稳定契约）
│   ├── schema/                字段表 YAML
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
| 按文件类型解析 | `adapters/parsers/` | 文本可用；PDF/Excel 需可选依赖；图片未接 OCR | 分类型各开 Issue |
| 统一文档 IR | `domain/ir.py` | 已定形状 | 非必要不改 |
| 文档分类 | `extraction/classify.py` | 关键词占位 | 按真实样本补规则 / LLM |
| 字段抽取 | `extraction/fields.py` | 锚点规则 + LLM 接口 | 等字段清单和 case |
| 标准化与校验 | `extraction/validate.py` | 格式 / 必填 / 证据 | 金额、日期、跨字段 |
| 包级对账 | `pipeline/steps/reconcile.py` | 同名字段冲突 | 金额、单号跨文件 |
| 自动通过 / 待复核 | `pipeline/steps/route_review.py` | 只打状态 | 复核页另开 Issue |
| 持久化接口 | `adapters/jobs/` `adapters/files/` | 内存实现；Postgres/S3 抛未实现 | 需要跨进程时再做 |
| 云 LLM | `adapters/llm/openai_compat.py` | 未配 Key 则跳过 | 换供应商只改这里 |

## 推荐拆 Issue 的顺序

需求方 case 和字段清单到位后，按这个顺序拆，一次一个 worktree：

1. 字段表按真实清单改 `schema/fields.yaml`
2. PDF 文本层解析（`parsers/pdf.py`）
3. Excel 解析（`parsers/excel.py`）
4. 报关单规则抽取（锚点 / 表头）
5. LLM API 兜底（提示词 + Schema）
6. 图片 / 扫描件云 OCR 或 VLM
7. 跨文件对账规则
8. Postgres + 对象存储
9. 人工复核页（如需要）

## 模块接口约定

每个 parser 只做一件事：`bytes + filename → DocumentIR`。

每个 pipeline step 只改 `PipelineContext`，不直接读写磁盘。

新存储后端：实现 Protocol，在 factory 注册，配置改 `DOCPARSE_JOB_STORE` / `DOCPARSE_FILE_STORE`。
