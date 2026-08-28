# 合单对接交付

给合单 / 业务对接：怎么在本机跑起来、调哪个口、字段什么意思、要什么 Key。开发模块细节见文末链接，本文不展开流水线。

当前阶段：xlsx / xls / PDF（文字层或扫描）/ jpg / png → 一张出口报关单。主链路是固定流水线，不是 Agent。任务存在内存里，进程退出即丢。客户原件不入库。

合单请打 **`POST /v1/declare`**。浏览器对眼打 `/v1/jobs`，不要混用信封。

---

## 1. 本机部署

需要：Python 3.11+，能访问外网（扫描件走合合 TextIn）。没有 Docker 配方，按单机 uvicorn 即可。解压收到的压缩包，进入项目根目录（有 `pyproject.toml` 的那一层）：

```bash
cd <解压后的项目目录>
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
# 扫描件 PDF / 图片：在 .env 填 TextIn（见第 2 节）
# 只测 xlsx 可以先不填

PYTHONPATH=src uvicorn docparse.api.app:app --host 127.0.0.1 --port 8088
```

`pip install -e ".[dev]"` 已含 Excel（openpyxl / xlrd）和 PDF（pymupdf）。生产最小集也可以 `pip install -e ".[excel,pdf]"`，再另装 uvicorn。

验活：

```bash
curl http://127.0.0.1:8088/health
# {"status":"ok"}
```

对眼页：浏览器打开 http://127.0.0.1:8088/review （`/` 同一页）。

不经 HTTP、本地看一张单：

```bash
python -m docparse.cli declare /绝对路径/表.xlsx
python -m docparse.cli declare /绝对路径/草单.pdf
```

CLI 打印的是对眼形状（字段上是名称，带 `_meta`），不是合单信封。合单请走 HTTP `/v1/declare`。

默认只绑 `127.0.0.1:8088`。要局域网访问把 `--host` 改成 `0.0.0.0`。任务和上传文件都在进程内存，**不要当多进程 / 多机部署**，重启即空。

---

## 2. 环境变量与 Key

复制 `.env.example` 为 `.env`。前缀一律 `DOCPARSE_`。

| 变量 | 何时要 | 没有会怎样 |
|---|---|---|
| `DOCPARSE_TEXTIN_APP_ID` | 扫描件 PDF、jpg/png | 流水线不崩；该页没有文字，后续字段空、对眼页 `needs_review` |
| `DOCPARSE_TEXTIN_SECRET_CODE` | 同上 | 同上 |
| `DOCPARSE_LLM_API_KEY` | **本期合单不需要** | 规则抽不到的字段保持空，不调模型 |
| `DOCPARSE_LLM_BASE_URL` / `DOCPARSE_LLM_MODEL` | 仅配了 LLM Key 时 | 默认走 OpenAI 兼容口 |

xlsx / 有文字层的 PDF **不必** TextIn。扫描件（半岛 SJ25084373 这类）必须配，否则抽空。

申请：合合 TextIn 开放平台 → 通用文字识别（多页）`https://api.textin.com/ai/service/v2/recognize/multipage`。选型记录见 [ocr-benchmark.md](ocr-benchmark.md)。QPS 超限（官方 40306）只告警不重试。

不要配、本期也接不上：

| 变量 | 说明 |
|---|---|
| `DOCPARSE_JOB_STORE` / `DOCPARSE_FILE_STORE` | 保持 `memory`。写成 `postgres` / `s3` 会直接报未实现 |
| `DOCPARSE_DATABASE_URL` / `DOCPARSE_S3_*` | 预留，未实现 |

其它默认：上传上限 100 MB（超限 HTTP 400）。zip 层数 / 体积闸已留，**zip 多文件拼一张单尚未交付**。

---

## 3. 接口一览

| 方法 | 路径 | 给谁 |
|---|---|---|
| `GET` | `/health` | 探活 |
| `POST` | `/v1/declare` | **合单主入口** |
| `POST` | `/v1/jobs` | 对眼页；同步跑完返回 Job |
| `GET` | `/v1/jobs/{id}` | 查一次任务（内存，重启失效） |
| `GET` | `/v1/jobs` | 列出内存里的任务 |
| `GET` | `/v1/schema` | 对眼页字段中文名 |
| `GET` | `/review` 或 `/` | 静态对眼页 |
| `GET` | `/openapi.json` | Swagger 描述 |

每个请求会带 `X-Request-Id`（可自带，没有则生成），写进响应头。

合单对接 **只需要** `/health` + `/v1/declare`。OpenAPI 文档：起服务后打开 http://127.0.0.1:8088/docs 。

---

## 4. 合单入口 `POST /v1/declare`

`multipart/form-data`，同步跑完。忽略 `run`。

### 请求

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | xlsx / xls / pdf / jpg / png。文件名带对后缀 |
| `agentCode` | 否 | 10 位申报单位海关代码。不传则泰洲 `4403180867` |
| `agentName` | 否 | 申报单位名称。默认「深圳市泰洲物流有限公司」 |
| `agentScc` | 否 | 18 位信用代码。默认 `914403000539716870` |
| `agentCiqCode` | 否 | 检验检疫代码。默认 `4700910159` |
| `cusIEFlag` | 否 | `E` 出口（默认）/ `I` 进口。本期按出口做 |

申报单位**不从文件解析**，只认请求或 YAML 默认。生产销售单位（`owner*`）文件里有就抽。未知 form 键忽略，不 400。

```bash
curl -s http://127.0.0.1:8088/v1/declare \
  -F "file=@/绝对路径/草单.xlsx" \
  -F "agentCode=4403180867" \
  -F "agentName=深圳市泰洲物流有限公司"
```

### 响应信封

对齐 Demo 识别结果（`code` / `msg` / `result` / `dec_results`）。

```json
{
  "code": 0,
  "msg": "操作成功",
  "result": true,
  "dec_results": { }
}
```

| `code` | `result` | `dec_results` | 何时 |
|---|---|---|---|
| `0` | `true` | 一张报关单 | 抽出了单（含待复核字段） |
| `2` | `false` | `null` | 解析/组装失败 |
| HTTP 400 | FastAPI `{"detail":"..."}` | — | 没带 file、空文件、超过 100 MB |
| HTTP 500 | `{"detail":"internal error"}` | — | 未映射的服务器异常 |

业务失败不是 500。缺字段、转不出海关码、件毛净对不上：**仍然 `code=0` 交单**，空着的键是 `""`，不删键。对眼页用 `/v1/jobs` 看复核原因。

`dec_results` 相对对眼 JSON 的差别：

- 没有 `_meta`、货行没有 `_source`
- 能转上海关码的字段输出 **code**（`supvModeCdde` 为 `"0110"` 不是「一般贸易」）；转不出则留原文
- 出口填死：`dataSource="7"`，`promiseItem1/2/3="0"`
- `packName` / `packType` 复制 `wrapType`
- 每条货生成 `id`（UUID），不进抽取、每次请求不同

完整契约见 [api.md](api.md)。

---

## 5. `dec_results` 字段要点

完整目录、锚点、码表见 [field-schema.md](field-schema.md) 与 [`src/docparse/schema/fields.yaml`](../src/docparse/schema/fields.yaml)。这里只列合单会碰到的键。抽不到就是 `""`，不编造。本期不区分必填/选填。

### 调用方（请求传入）

| 键 | 含义 |
|---|---|
| `agentCode` | 10 位申报单位海关代码 |
| `agentName` | 申报单位名称 |
| `agentScc` | 18 位信用代码 |
| `agentCiqCode` | 检验检疫代码 |

### 表头常用

| 键 | 含义 | 备注 |
|---|---|---|
| `cusIEFlag` | 进出口类型 | 默认 `E` |
| `entryType` | 报关单类型 | 参考常为 `M`，草单常空 |
| `contrNo` | 合同协议号 | |
| `tradeName` / `tradeCode` / `tradeScc` / `tradeCiqCode` | 境内收发货人 | 名称格末尾 10 位海关码会拆到 `tradeCode` |
| `consignorEname` | 境外收发货人英文名称 | 出口「境外收货人」；进境「境外发货人」同一字段 |
| `ownerName` / `ownerCode` / `ownerScc` / `ownerCiqCode` | 生产销售 / 消费使用单位 | 文件里有就抽 |
| `customMaster` | 申报地海关 | 四位关区，如 `5341` |
| `iePort` | 进/出口口岸 | 草单「出境关别 / 进境关别」。**不要**和申报地海关混 |
| `ciqEntyPortCode` | 入境/离境口岸 | CIQ，不是四位关区 |
| `distinatePort` | 经停港 / 指运港 | 如 `HKG000` |
| `despPortCode` | 启运港 | 出口常空 |
| `cusTrafMode` | 运输方式 | code，如公路 `4` |
| `trafName` / `cusVoyageNo` | 运输工具名称 / 航次 | 同一格时整格先挂名称，拆航次见已知缺口 |
| `billNo` | 提运单号 | |
| `manualNo` | 备案号 | |
| `licenseNo` | 许可证号 | |
| `supvModeCdde` | 监管方式 / 贸易方式 | 字段名按 Demo 原样（Cdde）。一般贸易 `0110` |
| `cutMode` | 征免性质 | 一般征税 `101` |
| `cusTradeNationCode` | 贸易国别 | 三位国别码 |
| `cusTradeCountry` | 启运(运抵)国 | 出口=运抵国 |
| `wrapType` | 包装种类 | `packName` / `packType` 与此相同 |
| `packNo` | 件数 | |
| `grossWt` / `netWt` | 毛重 / 净重（公斤） | 只有净重则毛重空着，不把净重抄进毛重 |
| `transMode` | 成交方式 | FOB=`3` |
| `feeMark` / `feeRate` / `feeCurr` | 运费 | 同格未拆，常空 |
| `insurMark` / `insurRate` / `insurCurr` | 保费 | 同上 |
| `otherMark` / `otherRate` / `otherCurr` | 杂费 | 同上 |
| `markNo` | 标记唛码 | 抽不到不编 `N/M` |
| `noteS` | 备注 | |
| `goodsPlace` | 货物存放地点 | |
| `entryId` / `preEntryId` | 海关编号 / 预录入编号 | 未申报常空 |
| `declDate` / `ieDate` | 申报日期 / 进(出)口日期 | 不是同一个字段 |
| `attachedDocs` | 随附单证原文 | 结构化数组见空数组 |
| `promiseItems` | TCS 承诺事项 | 常空 |

码表精确匹配中文名。俗称（「莲塘口岸」「纸箱」）转不出码时字段留原文，不瞎填。俗称别名尚未做（#27）。

### 商品 `tdecGoodsitemsVoArr[]`

| 键 | 含义 |
|---|---|
| `gno` | 项号 |
| `codeTs` | HS 商品编号 |
| `gname` | 品名 |
| `gmodel` | 规格 / 申报要素 **原文**。本期不编 `0\|0\|...` |
| `brand` | 品牌 |
| `gqty` / `gunit` | 成交数量 / 成交单位 |
| `declPrice` / `declTotal` / `tradeCurr` | 单价 / 总价 / 币制 |
| `qty1` / `unit1` / `qty2` / `unit2` | 法定数量与单位 |
| `cusOriginCountry` | 原产国 |
| `destinationCountry` | 最终目的国 |
| `districtCode` | 境内货源地 / 目的地（区划码） |
| `ciqDestCode` | 目的地检验检疫码（从双码前缀拆出） |
| `dutyMode` | 征免方式（与表头 `cutMode` 不是同一个） |
| `customGrossWet` / `customNetWt` | 行毛重 / 行净重（json 原字段名 Wet） |
| `exgVersion` | 加工成品单耗版本号，一般贸易常空 |
| `id` | 出口生成的 UUID |

有海关商品表以它为主；箱单 / 发票只补空，不另出一张报关单。

### 出口填死 / 空数组

| 键 | 值 |
|---|---|
| `dataSource` | `"7"` |
| `promiseItem1` / `2` / `3` | `"0"` |

下列合单 Demo 有、本期不展开，输出 `[]`：`tdecContasVoArr`（集装箱）、`tdecCoplimitVoArr`、`tdecDocusVoArr`、`tdecEdocRealationVoArr`、`tdecOthersPacksVoArr`、`tdecRequCertVoArr`、`tdecUsersVoArr`、`tdecEcoRelVoArr`、`tdecGoodsitemsVin`。国光那种已填集装箱的样本，这边仍是空数组。

系统主键不解析、不输出：`sysBillNo`、`ownerCompanyId` / `Code` / `Name`、`requestId`、`headId`、`decId`。

---

## 6. 对眼页（可选）

合单不要依赖这个口。本地看抽得对不对：

1. http://127.0.0.1:8088/review
2. 上传同一份文件
3. 页走 `POST /v1/jobs`：字段上是 **中文名**，旁边才是 code；并列出 `reviews`（哪张 sheet、哪个格子）

Job 里还有 `result.package`（版面 IR），合单不要吃。

---

## 7. 已知限制（交接时要说清）

- **zip 多文件拼一张单**：未交付。请单文件上传。
- **`gmodel`**：申报要素原文，不编规范 `0|0|材质|...`。
- **运费 / 保费 / 杂费、航次、唛码与备注**：常与别的字写在同一格，尚未拆成 Mark/Rate/Curr、`trafName`+`cusVoyageNo`、`markNo`+`noteS`（#34–#36）。
- **发票号**：目录无槽位（#37），对不上只复核，不塞进现有字段。
- **俗称转码**（莲塘口岸、纸箱）：码表精确匹配，转不出留原文（#27）。
- **币制等码表**：客户参数表缺 sheet，有的字段转不出 code。
- **内存存储**：不能多实例、不能重启后查单。
- **不按公司写解析器**：新叫法加 YAML 词表 / 锚点，不要 `if 恒信`。
- **客户原件不进 git**。测试夹具在 `tests/`，真机样本在对接方本地。

---

## 8. 建议联调顺序

1. `GET /health`
2. 上传一份 xlsx 草单（恒信结构即可）→ `code=0`，看 `contrNo`、`tdecGoodsitemsVoArr`、`agentName`
3. 同一文件再打 `/v1/jobs`，对照中文名和 reviews
4. 配上 TextIn 后传扫描 PDF（如 SJ25084373）→ 应有 `dec_results`，不再是 `null`
5. 不传 `file` → 400

字段对不上先看对眼页的格子证据，再对 [field-schema.md](field-schema.md) 的锚点，不要先改合单字段名。

---

## 9. 还要往下看时

| 问题 | 文档 |
|---|---|
| HTTP 细节 / 错误分界 | [api.md](api.md) |
| 每个字段从哪类格子来 | [field-schema.md](field-schema.md) |
| 名称怎么转 code | [code-tables.md](code-tables.md) |
| 多张表怎么收成一张单 | [assemble.md](assemble.md) |
| 对眼页 | [review.md](review.md) |
| 模块与流水线 | [modules.md](modules.md) |
| OCR 选型 | [ocr-benchmark.md](ocr-benchmark.md) |
| 开发约定（Issue / worktree / PR） | [CLAUDE.md](../CLAUDE.md) |
