# 表头映射（BOX / KV → TdecHead）

运行时：`extraction/head_map.py`。目录在 [`fields.yaml`](../src/docparse/schema/fields.yaml) 的 `head`。本地对眼：

```bash
python -m docparse.cli head /绝对路径/表.xlsx
```

本文件只回答「一张已经打好角色的 sheet，原文 KV 怎么变成表头字段」。不切格子（layout）、不认角色（#16）、不拼整单（#19）、不转 code（#14）。

## 输入 / 输出

```text
Sheet.key_values + consume
  → 只处理 consume ≠ exclude
  → key 对 fields.yaml head.anchors（去空白、大小写不敏感）
  → ExtractedField（值先留原文，证据 = sheet 名 + 格子）
```

一份 xlsx 有几张合格 sheet，就调用几次，结果**并排**。草单 `packNo=40` 和箱单上的件数不会在这一层互相覆盖。谁是主、谁补空是 #19。

`auxiliary` / `unknown` 的 KV 留在 IR，本层不读。

## `head_map`

挂在字段上，不写公司分支。

| 值 | 含义 |
|---|---|
| `keep`（默认） | 整格进该字段 |
| `skip` | 本层不映射。`agent*`、由别的字段拆出的 code、不稳拆分 |
| `trailing_code` | 值末尾 10 位海关代码（字母数字）拆给 `split_target`，前面进本字段 |

稳拆只做这一种：`tradeName` / `ownerName`。没有 10 位尾巴就整格当名称，不编造代码。

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
| 语义是新表头字段 | `fields.yaml` 新字段 + anchors | 否（映射器按目录走） |
| 名称+代码粘在一起 | 已有 `trailing_code` | 否 |
| 新的稳拆规则（例如 18 位信用代码） | 新 `head_map` 值 + 拆分函数 | 是，通用规则，不按公司 |
| 运费 / 航次 / 唛码要拆 | #34–#36 | 派工后再动 |
| 跨表谁覆盖谁（表头） | #19 | 否 |
| 商品行跨表补空 | #18 / [goods-map.md](goods-map.md) | 否 |
| 名称要变成海关 code | #14 / #27 / #19 | 否 |
| 发票号要进报关单 | #37 先定落点 | 视目录 |

不要 `if company == "恒信"`。不要在这一层 `lookup(code_tables)`。不要把 key 在 layout 里改写成 `contrNo`。
