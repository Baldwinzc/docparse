# 版面词表与别名

运行时读取 [`src/docparse/schema/layout_vocab.yaml`](../src/docparse/schema/layout_vocab.yaml)。`layout.py` 不再维护 Python 词表常量。

本文件只回答「哪些格子算框表标签 / 表头词」。抽出的 key、列名仍是格子原文，不在这里映射到报关字段（那是 #17 / #18）。

## 匹配规则（本期不改刀法）

| 词表 | 怎么比 |
|---|---|
| BOX | 去首尾空白和 `:` / `：` 后**整词相等** |
| TABLE | token 是单元格的**子串**；英文 token 大小写不敏感，且按字母数字词边界（`HS` 不打中 `THIS`） |
| 表头行 | 一行至少 3 个非空格，且至少 **2** 个格子命中 TABLE token |
| 例外 | 一行格子去冒号后**全部**是 BOX 标签（至少 3 个）→ 框表标签横排，不当表头。否则「毛重」进 TABLE 后会把恒信草单 r11 吃成表 |

双行表头（中文行 + 下一行英文翻译）并入 header，交 [#15](https://github.com/Baldwinzc/docparse/issues/15)，本词表只提供英文 token。

## BOX

恒信草单「一般贸易出口」框表标签迁入，并补 #12 对照表里这张出口草单没有的进出口镜像和空格。

中文简称「毛重」「净重」收入 BOX。**G.W. / N.W. 不进 BOX**（样本里只当列名）。

英文商业单据 KV（`Invoice No.`、`Bill To`、`DATE`、`SELLER` / `BUYER`、`CONTRACT NO.`、`SHIPPED PER`）本期不收，后期子 Issue 只补 BOX 英文 KV，TABLE 英文已在本文件。

每条别名的 `source` 写在 YAML 里（哪张表哪格，或 #12 依据）。

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

## 增别名

改 YAML，不必改 Python。`id` 只是分组，不接到 `fields.yaml`。
