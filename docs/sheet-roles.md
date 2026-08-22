# sheet 角色

运行时读取 [`src/docparse/schema/sheet_roles.yaml`](../src/docparse/schema/sheet_roles.yaml)。打分器在 `extraction/sheet_role.py`。Excel 拆完 KV / table 后贴标签；`cli layout` 一并打出。

本文件只回答「这张 sheet 在业务上是什么、下一张报关单吃不吃」。不映射 `contrNo` / 商品行（那是 #17 / #18），不拼整单（#19）。

## 角色与消费

| 角色 | consume | 谁用 | #17 / #18 / #19 |
|---|---|---|---|
| `draft` | `primary` | 海关草单 | 表头主源；主货表候选 |
| `packing` | `supplement` | 箱单 | 只补空；核对件毛净 |
| `invoice` | `supplement` | 发票 | 只补空 |
| `contract` | `supplement` | 合同 | 只补空 |
| `auxiliary` | `exclude` | 对照码 / 内部货号 / 历史台账 | 不读、不当主货表 |
| `unknown` | `exclude` | 对不上 | 格子留在 IR，不自动补 |

`auxiliary` 和 `unknown` 都是 exclude：KV / table **不丢**，只是组装不吃。错分成 `unknown` 比错分成 `packing` 安全。

## 怎么打分

不看公司名。文件名只加 `filename_weight`（默认 1），不能单独过 `min_score`（默认 3）。

```text
标题（sheet 名 + 前几行格子）
+ 已拆 KV 键
+ 已拆表头
+ 辅助表：两列对照形（lookup_pairs）
+ 文件名弱提示
→ 最高分且比第二名高、且 ≥ min_score
→ 否则 unknown + exclude
```

`Sheet1` / `1` / `Sheet3` 这种通用名当空，不参与标题分。内容仍能定角色：框表标签够多就是 draft，内部编号 / 报关单号就是 auxiliary。

信号默认子串（去空白、大小写不敏感）。短词容易误伤时写 `match: exact`（`INVOICE` 不打中 `Invoice No.`，`合同` 不打中 `合同号`）。

## 新 xlsx 往哪加

对照 [#31](https://github.com/Baldwinzc/docparse/issues/31)：先 `python -m docparse.cli layout 新表.xlsx` 看版面，再看角色。

| 你看到的现象 | 改哪里 | 动 Python？ |
|---|---|---|
| 表名乱、内容仍是箱单 / 草单 | 不用改，看内容 | 否 |
| 新叫法（「装箱明细」「形式发票」） | `sheet_roles.yaml` 已有 role 下加信号 | 否 |
| 新单据类型（产地证、提单 sheet） | 新 `id` + `consume` | 否（打分器已按目录走） |
| 新辅助表长相对照 / 台账 | `auxiliary` 加表头或标题 | 否 |
| 对不上 | 保持 unknown，整包复核 | 否 |
| layout 键都没拆出来 | 先补 `layout_vocab.yaml` | 视词表 |

不要 `if company == "恒信"`。不要因为 unknown 里抽出了字就当补充。

## 本阶段不做

- 跨表补货（#18）
- 拼一张报关单（#19）
- unknown 自动降级补空

BOX → TdecHead 见 [head-map.md](head-map.md)（#17）。
