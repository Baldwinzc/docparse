# 表头映射（BOX / KV / 平表恒定列 → TdecHead）

运行时：`extraction/head_map.py`。目录在 [`fields.yaml`](../src/docparse/schema/fields.yaml) 的 `head`。本地对眼：

```bash
python -m docparse.cli head /绝对路径/表.xlsx
```

本文件只回答「一张已经打好角色的 sheet，原文怎么变成表头字段」。不切格子（layout）、不认角色（#16）、不拼整单（#19）、不转 code（#14）。

## 输入 / 输出

```text
Sheet.key_values / 恒定列 + consume
  → 只处理 consume ≠ exclude
  → key / 表头列名 对 fields.yaml head.anchors（键归一化，见下）
  → ExtractedField（值先留原文，证据 = sheet 名 + 格子）
```

一份 xlsx 有几张合格 sheet，就调用几次，结果**并排**。草单 `packNo=40` 和箱单上的件数不会在这一层互相覆盖。谁是主、谁补空是 #19。

`auxiliary` / `unknown` 的 KV 留在 IR，本层不读。

## 平表恒定列（#67）

报关平表（一行一商品）没有框表 KV，表头级信息全在列里。第二条路径「表列 → 表头」：

| 规则 | 说明 |
|---|---|
| 触发 | 角色 `head_from_columns: true`（[`sheet_roles.yaml`](../src/docparse/schema/sheet_roles.yaml)，目前仅 `declaration_list`）。框表角色不开，防商品表常量列误伤 |
| 表 | 复用该 sheet 的最佳商品表（[`goods-map.md`](goods-map.md) 同一张） |
| 恒定 | 该列非空值集合无冲突（只一个值）即恒定。合计列只填首行（通达2「总件数=272」只在第一行）也算 |
| 行级防线 | 每行变化的列（件数 / 净重 / 毛重）值集合 >1，不出表头 |
| 单行表 | 整表只有一行数据时恒定无法佐证，取值但标 `needs_review`（`single_row_column`） |
| 证据 | 表头格 + 首个值格；发射复用 KV 路径（`trailing_code` / 纯码路由同样生效） |
| 优先级 | 同字段 BOX KV 先、列后（`found` 先到先得） |

配套：表尾冒号注记行（通达2 R52「境内发货人:…」）不进表体，格子留给 same_cell KV（layout 层 `_is_note_row`）。

## 键归一化（#66）

键与锚点两侧都过 `schema/textnorm.py`，值永远不动：

| 现象 | 例子 | 折成 |
|---|---|---|
| 去全部空白（含换行） | `毛 重` / `毛重\n（公斤）` | `毛重(公斤)` |
| 全角括号统一半角 | `贸易国（地区）` | `贸易国(地区)` |
| 键尾剥「（≤6 位字母数字）」码 | `贸易方式（0110）` | `贸易方式` |
| 括号里不是字母数字不剥 | `贸易国（地区）` / `毛重（公斤）` | 保持 |
| 繁体字**不**转换 | `淨重` | `淨重`（靠 alias 收，不做简繁映射） |

## `head_map`

挂在字段上，不写公司分支。

| 值 | 含义 |
|---|---|
| `keep`（默认） | 整格进该字段 |
| `skip` | 本层不映射。`agent*`、由别的字段拆出的 code、不稳拆分 |
| `trailing_code` | 值末尾 10 位海关代码（字母数字）拆给 `split_target`，前面进本字段 |

稳拆只做这一种：`tradeName` / `ownerName`。没有 10 位尾巴就整格当名称，不编造代码。

## 纯代码值路由（#66）

`trailing_code` 字段的值整体是码（可带括号壳）时不当名称：

| 值形状 | 落点 |
|---|---|
| 整体 10 位海关码（GSC 经营单位 `440356K004`） | `split_target`（tradeCode / ownerCode）；name 留空标 `pure_code_value` 待复核 |
| 整体 18 位信用代码（GSRUA `91330206MA2818T42Q`） | `scc_target`（tradeScc / ownerScc）；name 同上 |
| `（码）`括号壳 | 剥壳按码处理 |
| 名称+尾码（恒信 `…公司441394164D`） | 原 `trailing_code` 拆法不变 |

## 出口商业单据（不是某家公司）

报关单没有 seller / buyer 槽。本期只做出口：

| 商业单据键 | 进哪个字段 |
|---|---|
| 卖方 / SELLER / 卖 方 | `tradeName` 补充候选 |
| 买方 / BUYER / 买 方 / Bill To | `consignorEname` 补充候选 |
| 合同号 / CONTRACT NO. | `contrNo` |
| Invoice No. | **不进表头**（目录无槽，见 #37） |

新叫法加 `anchors`，不要 `if 国光`。进口对调另开范围。

## 刻意不做（记账 Issue）

| 格子 | 本层 | 以后 |
|---|---|---|
| 运费 / 保费 / 杂费 | skip | #34 |
| 运输工具名称及航次号 | 整格 `trafName` | #35 |
| 标记唛码及备注 | 整格 `markNo`；独立「备注」进 `noteS` | #36 |
| 发票号 | 不映射 | #37 |
| FOB / 公路运输 / 莲塘口岸 | 留中文 | #14 / #19 / #27 |
| 申报单位 `agent*` | 不从文件填 | #21 |

## 以后新 xlsx / 新叫法改哪

对照 [#31](https://github.com/Baldwinzc/docparse/issues/31)。先 `cli layout`，再 `cli head`。

| 你看到的现象 | 改哪里 | 动 Python？ |
|---|---|---|
| 键的叫法没见过，layout 都没拆出 | `layout_vocab.yaml` alias | 否 |
| layout 有了，对不上报关字段 | 已有字段的 `anchors` | 否 |
| 键带空白 / 换行 / 全角括号 / 尾码（`贸易方式（0110）`） | 已被键归一化吃掉，不用管 | 否 |
| 平表新表头级列叫法（恒定列） | 已有字段的 `anchors` | 否 |
| 恒定列判定想收紧（比如要求 ≥2 行同值） | `head_map.py` 常量 | 是 |
| 其它角色也要走表列路径 | `sheet_roles.yaml` 该角色 `head_from_columns: true` | 否 |
| 表尾冒号注记行误伤数据行 | `layout.py` `_is_note_row` | 是，通用规则 |
| 新的「标签（码）」写法剥不掉 | `textnorm.py` 剥码正则 | 是，常量 |
| 值是纯码 / 括号码，新形状 | `head_map.py` 值路由规则 | 是，通用规则 |
| 语义是新表头字段 | `fields.yaml` 新字段 + anchors | 否（映射器按目录走） |
| 名称+代码粘在一起 | 已有 `trailing_code` | 否 |
| 新的稳拆规则（例如 18 位信用代码） | 新 `head_map` 值 + 拆分函数 | 是，通用规则，不按公司 |
| 运费 / 航次 / 唛码要拆 | #34–#36 | 派工后再动 |
| 跨表谁覆盖谁（表头） | `fields.yaml` `assembly` / [assemble.md](assemble.md) | 否 |
| 商品行跨表补空 | #18 / [goods-map.md](goods-map.md) | 否 |
| 名称要变成海关 code | #14 / #27 / #19 | 否 |
| 值本身已是合法 code（iePort=5304） | assemble 反查兜底已接受，不用管 | 否 |
| 发票号要进报关单 | #37 先定落点 | 视目录 |

不要 `if company == "恒信"`。不要在这一层 `lookup(code_tables)`。不要把 key 在 layout 里改写成 `contrNo`。
