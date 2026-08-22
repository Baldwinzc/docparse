# 组装一张报关单

运行时：`extraction/assemble.py`。策略在 [`fields.yaml`](../src/docparse/schema/fields.yaml) 的 `assembly`。本地对眼：

```bash
python -m docparse.cli declare /绝对路径/表.xlsx
python -m docparse.cli declare /绝对路径/表.xlsx --agent-code 4403180867 --agent-name 深圳市泰洲物流有限公司
```

本文件只回答「多摊表头 + 一张货表怎么收成一张报关单」。不切格子（layout）、不认角色（#16）、不改货表对行（#18）。

## 输入 / 输出

```text
已打角色的 sheets
  → 只处理 consume ≠ exclude
  → 有 draft：表头以草单为准；商业单据只补空，并核件毛净
  → 无 draft：商业单据能确定的抄；customs_only 空着复核，不编
  → 名称能转 code 就转；转不出留原文 + needs_review
  → agent* 只来自 CLI 参数
  → 一张 Declaration / 一份 dec_results 形状 JSON
```

`auxiliary` / `unknown` 的 KV / table 留在 IR，本层不读，不另开一张单。

## `assembly`

按角色，不写公司分支。

| 键 | 含义 |
|---|---|
| `primary_role` | 有这张角色就当草单抄。默认 `draft` |
| `role_priority` | 多摊候选时的先后。默认 draft → packing → invoice → contract |
| `fill` | `overwrite` 覆盖 / `fill` 只补空 / `ignore` 不吃 |
| `reconcile` | 主源已有值时，其它可消费 sheet 对一下。不一致保留主源，打 `needs_review` |
| `customs_only` | 无草单时不从商业单据编。监管方式、征免、口岸、包装种类等 |
| `defaults` | 组装默认值。本期只有出口 `cusIEFlag=E` |
| `weight.net_as_weight` | 只有净重、没有毛重时，净重视同重量，进 `netWt` |
| `weight.copy_net_to_gross` | 必须为 false。净重 ≠ 毛重，不要抄进 `grossWt` |
| `invoice_vocab` | 发票号词表 id。目录无槽（#37），只核对，不映射 |

## 重量

| 表头格子 | 结果 |
|---|---|
| 同时有毛重、净重 | `grossWt` / `netWt` 各填各的 |
| 只有净重 / N.W. | `netWt` 填上；`grossWt` 空 + `net_is_not_gross` |
| 未区分的「重量」 | 视同重量，进 `netWt`；仍不进 `grossWt` |

商品行 `customNetWt` / `customGrossWet` 仍归 #18，本层不改货表。

## 以后新 xlsx / 新叫法改哪

对照 [#31](https://github.com/Baldwinzc/docparse/issues/31)。先 `cli layout`，再 `cli head` / `cli goods`，最后 `cli declare`。

| 你看到的现象 | 改哪里 | 动 Python？ |
|---|---|---|
| 新叫法（装箱明细、形式发票） | `sheet_roles.yaml` / `layout_vocab.yaml` / `fields.yaml` anchors | 否 |
| 新单据类型要参与拼单 | `sheet_roles.yaml` 加 role；`assembly.fill` / `role_priority` | 否 |
| 新辅助表 | `auxiliary` + `consume: exclude` | 否 |
| 新表头字段 | `fields.yaml` 新字段 + anchors | 否（组装器按目录收） |
| 新字段要转 code | 字段上写 `code_table`；码表加行 | 否 |
| 无草单时不要编的海关项 | `assembly.customs_only` | 否 |
| 要对一下的件毛净 / 单号 | `assembly.reconcile` | 否 |
| 发票号要进报关单 | #37 先定落点 | 视目录 |
| 俗称（莲塘口岸、纸箱）要转码 | #27 | 否 |
| 货表净重抄毛重 | #18，不在这里改 | 否 |

不要 `if company == "恒信"`。不要把商业单据上的监管方式 / 口岸编进无草单的单。
