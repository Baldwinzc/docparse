# 版面词表与别名

运行时读取 [`src/docparse/schema/layout_vocab.yaml`](../src/docparse/schema/layout_vocab.yaml)。`layout.py` 不再维护 Python 词表常量。

本文件只回答「哪些格子算框表标签 / 商业单据键 / 表头词」。抽出的 key、列名仍是格子原文，不在这里映射到报关字段（那是 #17 / #18）。

## 匹配规则（#15 刀法）

| 词表 | 怎么比 |
|---|---|
| BOX | 去首尾空白和冒号后**整词相等** |
| KV | 同 BOX；大小写不敏感。商业单据键，**不参与**「整行 BOX 不当表头」 |
| TABLE | token 是单元格的**子串**；英文 token 大小写不敏感，且按字母数字词边界（`HS` 不打中 `THIS`） |
| 表头行 | 一行至少 3 个非空格，且至少 **2** 个格子命中 TABLE token |
| 例外 | 一行格子去冒号后**全部**是 BOX 标签（至少 3 个）→ 框表标签横排，不当表头。否则「毛重」进 TABLE 后会把恒信草单 r11 吃成表 |
| 双行表头 | 表头下一行像翻译（≥2 格像列名、不像数字/日期）→ 并入 `headers`（中英文空格拼接），英文行不当 body[0]。`header_row` 仍是第一行，`header_rows` 记下两行 |
| 冒号 | 半角 `:`、全角 `：`、小冒号 `﹕`（U+FE55）、竖排 `︰`。整格已是日期时间则不切；切完左侧像日期时间也不切。值里后续冒号保留 |

几何策略先收集 `same_cell` / `below` / `right`，再按词表 id 上的 `value:` 过滤；剩多个才用 `same_cell` > `below` > `right` 决胜。无 `value:` 的键与 #15 互斥结果一致。新 xlsx 往哪加见 [#31](https://github.com/Baldwinzc/docparse/issues/31)。

`id` 只是分组，不接到 `fields.yaml`。值域约束挂在 id 上，不挂每条 alias。

## BOX

恒信草单「一般贸易出口」框表标签迁入，并补 #12 对照表里这张出口草单没有的进出口镜像和空格。

中文简称「毛重」「净重」收入 BOX。**G.W. / N.W. 不进 BOX / KV**（样本里只当列名）。

每条别名的 `source` 写在 YAML 里（哪张表哪格，或 #12 依据）。

## KV

商业单据键，和 BOX 分开，避免一行三个英文标签被「整行 BOX」当成框表横排。

- 发票号：`Invoice No.`、`INVOICE NO.`、`发票号INVOICE NO.`、`发票/INVOICE NO.`
- 收货：`Bill To`
- 日期：`DATE`、`Date`、`日期DATE`、`日期`
- 买卖方：`SELLER` / `卖方SELLER` / `卖 方`，`BUYER` / `买方BUYER` / `买 方`
- 合同号：`CONTRACT NO.`、`合同号CONTRACT NO.`
- 运输：`SHIPPED PER`、`运输工具 SHIPPED PER`

`same_cell` / `right` 认键时用 `box ∪ kv`。以后 `P.O. No.` 只加 YAML。

## TABLE

恒信草单商品表 r17 的 token 迁入，并补：

- 品名：货物名称、物料名称、Description
- 数量：出货数量、Qty、Q'ty、Quantity
- 重量（草单「重量KG」，未区分毛/净）：重量
- 净重：净重、N.W.、NW
- 毛重：毛重、G.W.、G.W、GW（`G.W` 无第二点，才能打中恒信装箱单 `G.W .(Kg)`）
- 金额：汇总价、总值、Amount、Unit Price
- 编码：商品编码、海关编码、HS
- 产地：原产地、Country of Origin

不加「单位」（防误伤「生产销售单位」）。国光「单位」列靠同行「物料名称 / 出货数量」凑满 2 命中。

## 值域（#29）

只给会撞车的 id 标形状。无 `value:` = 不过滤。公司名、地址、成交方式 / 监管方式不写（像不像合法业务值是 #14 / #17 / #20）。

| type | 本文件挂在 | 值不像则丢 |
|---|---|---|
| `datetime` | `ie_date`、`decl_date`、`date` | 不是 `YYYY-MM-DD` / `YYYY-MM-DD HH:MM[:SS]`（Excel 带 `00:00:00` 也算） |
| `number` | `pack_no`、`gross_wt`、`net_wt` | 不是纯数字 |
| `pattern` | `invoice_no` | 对不上 YAML 里的正则 |
| `date` / `text` | 本阶段不用 | `date` 不吃时间；`text` 等于没约束 |
| 不写 | 其余 id | 与 #15 相同 |

运行时：规范化 key 反查 box ∪ kv 的 id → 过滤 → 剩 1 个就收，剩 0 个该键缺失（不编造）。词表没收的新标签 = 无约束。

单号类只挂了 `invoice_no`。`contr_no` / `contract_no` / `bill_no` 等撞车后再加 YAML，不必改 Python。

## 增别名

改 YAML，不必改 Python。新格子关系（不是新文案）另开刀法 Issue。以后新表对照 [#31](https://github.com/Baldwinzc/docparse/issues/31)。
