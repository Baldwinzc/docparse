# 报关单输出字段目录

运行时读取 [`src/docparse/schema/fields.yaml`](../src/docparse/schema/fields.yaml)。

形状对齐 Demo `字段说明.json`；草单上看得到、json 没有的从 `报关字段说明.md` 补。客户原件不进仓库。

本目录只回答「输出什么、从哪类版面来」。名称转 code 见 [code-tables.md](code-tables.md)（#14），BOX/TABLE 别名见 [layout-vocab.md](layout-vocab.md)（#13），映射组装是 #17–#19。

本期**不区分必填 / 选填**，YAML 里 `required` 一律未标。后期再优化。

目录可继续加字段，不锁死。同义词、列名别名（毛重 / G.W.、出货数量）见 [layout-vocab.md](layout-vocab.md)。

## 版面来源

| `layout` | 含义 |
|---|---|
| `box_kv` | 框表 KV（上标签下取值；冒号键值同类） |
| `table_col` | 商品表列。有海关商品表以它为主，箱单 / 发票 / 合同只补充 |
| `caller` | 调用方传入，不解析 |
| `default` | 组装默认值（本期出口 `cusIEFlag=E`） |
| `none` | 不从版面抽，可空 |
| `empty_array` | 输出 `[]`，本期不展开 |

抽不到或不符规则 → `needs_review`，不编造。

## 口岸对照（会上已定）

| 草单标签 | 输出字段 | 码表 | 说明 |
|---|---|---|---|
| 申报地海关 | `customMaster` | 海关口岸代码（四位） | 如 5341 深惠州关、5352 梅沙海关。草单不一定有独立格 |
| 出境关别 / 进境关别 | `iePort` | 海关口岸代码（四位） | 标准表「进/出口口岸」。恒信「莲塘口岸」进这里，**不要**写进 `customMaster` |
| 离境口岸 / 入境口岸 | `ciqEntyPortCode` | 入境/离境口岸 | CIQ 口岸，不是四位关区。半岛参考值 477101 |
| 指运港 / 经停港 | `distinatePort` | 港口代码 | 按中文名精确匹配。`HKG000` 风格与六位特殊监管区共存于同一张表，见 [code-tables.md](code-tables.md) |
| 启运港 | `despPortCode` | 港口代码 | json 漏标；出口草单常空，有则抽 |

## 调用方传入（不解析）

`agentCode` / `agentName` / `agentScc` / `agentCiqCode`：申报单位，调用时传入。

生产销售单位 / 消费使用单位（`owner*`）文件里有就抽，没有就空。

## 表头必须项对照

用户列出的表头格子 → 本目录字段：

| 草单 / 用户说法 | 输出字段 | 版面 |
|---|---|---|
| 预录入编号 | `preEntryId` | box_kv |
| 海关编号 | `entryId` | box_kv |
| 境内发/收货人 | `tradeName` + `tradeCode`（同一格末尾 10 位海关代码，#17 `trailing_code`） | box_kv |
| 出/进境关别 | `iePort` | box_kv |
| 进口日期 / 出口日期 | `ieDate` | box_kv |
| 申报日期 | `declDate`（json/md 未列此键，键名待确认） | box_kv |
| 备案号 | `manualNo` | box_kv |
| 境外收/发货人 | `consignorEname` | box_kv |
| 运输方式 | `cusTrafMode` | box_kv |
| 运输工具名称及航次号 | `trafName`（整格）；航次拆分见 #35 | box_kv |
| 提运单号 | `billNo` | box_kv |
| 货物存放地点 | `goodsPlace` | box_kv |
| 生产销售单位 / 消费使用单位 | `ownerName` + `ownerCode` | box_kv |
| 监管方式 | `supvModeCdde` | box_kv |
| 许可证号 | `licenseNo` | box_kv |
| 启运港 | `despPortCode` | box_kv |
| 合同协议号 | `contrNo` | box_kv |
| 贸易国（地区） | `cusTradeNationCode` | box_kv |
| 运抵国（地区） / 启运国（地区） | `cusTradeCountry` | box_kv |
| 指运港 / 经停港 | `distinatePort` | box_kv |
| 离/入境口岸 | `ciqEntyPortCode` | box_kv |
| 包装种类 | `wrapType` | box_kv |
| 件数 | `packNo` | box_kv |
| 毛重（千克） | `grossWt` | box_kv |
| 净重（千克） | `netWt` | box_kv |
| 成交方式 | `transMode` | box_kv |
| 运费 | `fee*` 本层 skip，拆分见 #34 | box_kv |
| 保费 | `insur*` 本层 skip，拆分见 #34 | box_kv |
| 杂费 | `other*` 本层 skip，拆分见 #34 | box_kv |
| 随附单证及编号 | `attachedDocs`（原文）+ `tdecDocusVoArr`（数组，拆条交后续） | box_kv |
| 标记唛码及备注 | `markNo`（整格）；与备注拆分见 #36。独立「备注」进 `noteS` | box_kv |

json 另有、用户这次没点名但仍收的：`cusIEFlag`、`entryType`、`cutMode`、`customMaster`、`tradeScc`、`tradeCiqCode`、`ownerScc`、`ownerCiqCode`、`promiseItems`。

## 商品必须项对照

| 草单 / 用户说法 | 输出字段 | 版面 |
|---|---|---|
| 项号 | `gno` | table_col |
| 商品编码 | `codeTs` | table_col |
| 商品名称及规格型号 | `gname`（名称） | table_col |
| 申报要素 | `gmodel`（恒信在这一列；规范编码本期留原文） | table_col |
| 品牌 | `brand` | table_col |
| 数量 | `gqty` | table_col |
| 单位 | `gunit` | table_col |
| 单价 | `declPrice` | table_col |
| 总价 | `declTotal` | table_col |
| 币制 | `tradeCurr` | table_col |
| 原产国 | `cusOriginCountry` | table_col |
| 最终目的地（地区） | `destinationCountry` | table_col |
| 境内目的地 | `districtCode`（出口草单常写境内货源地，同一字段） | table_col |

json 另有、用户这次没点名但仍收的：`qty1` / `unit1` / `qty2` / `unit2`、`dutyMode`、`customGrossWet`、`customNetWt`、`exgVersion`。

商品项挂在 `tdecGoodsitemsVoArr`。

## 可忽略（系统主键 / json 明确说可忽略的非业务项）

`dataSource`、`promiseItem1` / `2` / `3`、商品项内部 `id`、`sysBillNo`、`ownerCompanyId` / `Code` / `Name`、`requestId`、`headId`（表头主键）、`decId`。

`brand` **不再忽略**。

## 空数组（本期不展开）

`tdecContasVoArr` 集装箱、`tdecCoplimitVoArr` 企业资质、`tdecEdocRealationVoArr` 电子随附单据、`tdecOthersPacksVoArr` 其他包装、`tdecRequCertVoArr`、`tdecUsersVoArr`、`tdecEcoRelVoArr`、`tdecGoodsitemsVin`。

`tdecDocusVoArr` 随附单证：**不再当空数组忽略**，有字则收。

数组没有值时输出 `[]`，不能是 `null`。

## 相对 json 的增补

| 字段 | 中文 | 理由 |
|---|---|---|
| `declDate` | 申报日期 | 草单有格；json/md 未列键名 |
| `billNo` | 提运单号 | 草单有格 |
| `licenseNo` | 许可证号 | 草单有格 |
| `ieDate` | 进/出口日期 | 草单有「出口日期」 |
| `iePort` | 进/出口口岸 | 草单「出境关别」 |
| `ciqEntyPortCode` | 离境口岸 | json 漏标 |
| `trafName` | 运输工具名称 | 草单有格 |
| `cusVoyageNo` | 航次号 | json 漏标 |
| `despPortCode` | 启运港 | json 漏标 |
| `goodsPlace` | 货物存放地点 | json 漏标 |
| `entryId` | 海关编号 | 草单有格 |
| `preEntryId` | 预录入编号 | 草单有格 |
| `attachedDocs` | 随附单证及编号 | 草单有格 |
| `brand` | 品牌 | 草单商品表有列 |

## 本期不做 / 交给后面 Issue

- 必填 / 选填
- BOX / TABLE 同义词、列名别名（#13，已抽到 `schema/layout_vocab.yaml`）
- 名称转 code（#14，已抽到 `schema/code_tables.yaml`）
- 同一格稳拆（名称+海关代码）在 #17；运费 / 航次 / 唛码见 #34–#36
- 跨表补充、拼整单（#18 / #19）
- 集装箱 / VIN 等块：空数组
- `gmodel` 规范编码（`0|0|...`）先留原文
- json 未列的 `*Name` 名称镜像字段不收
- 客户原件入库

## 流水线结果对象

每个**已抽取**字段仍不是裸字符串：

```json
{
  "name": "entryId",
  "value": null,
  "normalized_value": null,
  "confidence": 0.0,
  "status": "missing",
  "extraction_method": null,
  "evidence": [],
  "validation_errors": []
}
```

`status`：`accepted` | `needs_review` | `missing` | `conflict` | `invalid`

最终交付给调用方的是一张报关单对象（表头 + `tdecGoodsitemsVoArr`），由后续 Issue 组装。本 Issue 只定目录。
