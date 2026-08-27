# sheet 角色

运行时读取 [`src/docparse/schema/sheet_roles.yaml`](../src/docparse/schema/sheet_roles.yaml)。打分器在 `extraction/sheet_role.py`。Excel 拆完 KV / table 后贴标签；`cli layout` 一并打出。

本文件只回答「这张 sheet 在业务上是什么、下一张报关单吃不吃」。不映射 `contrNo`（#17）/ 商品行（#18）。拼整单见 [assemble.md](assemble.md)（#19）。

## 角色与消费

| 角色 | consume | 谁用 | #17 / #18 / #19 |
|---|---|---|---|
| `draft` | `primary` | 海关框表草单 / 出·进境备案清单 | 表头主源；主货表候选。进境镜像键（境内收货人 / 进境关别 / 进境日期 / 消费使用单位 / 入境口岸 / 启运港 / 经停港 / 货物存放地点）已收信号（#82） |
| `declaration_list` | `primary` | 扁平海关表（表头混表头字段 + 货列） | 与 draft 同权：主货表加权 10、overwrite；表头经恒定列映射（`head_from_columns: true`，#67） |
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

`Sheet1` / `1` / `Sheet3` 这种通用名当空，不参与标题分。内容仍能定角色：框表标签够多就是 draft，扁平海关表头够多就是 `declaration_list`，内部编号 / 报关单号就是 auxiliary。

`declaration_list` 只靠表头信号，不写 titles / keys。强表头（申报海关、账册号、申报计量单位、第一法定数量、总件数、总净重、总毛重）各 3 分，弱表头各 1 分。恒信框表草单仍以 draft 胜出（本角色通常 ≤6，draft ≥11）。台账（报关单号 / 报关日期 / 出口发票号）在本角色上为 0。

短词容易误伤时写 `match: exact`。`报关单` 必须 exact：子串会打中「报关单价 / 报关型号」，把对照表抬成 draft。

信号默认子串（去空白、大小写不敏感）。短词容易误伤时写 `match: exact`（`INVOICE` 不打中 `Invoice No.`，`合同` 不打中 `合同号`）。

## 新 xlsx 往哪加

对照 [#31](https://github.com/Baldwinzc/docparse/issues/31)：先 `python -m docparse.cli layout 新表.xlsx` 看版面，再看角色。

| 你看到的现象 | 改哪里 | 动 Python？ |
|---|---|---|
| 表名乱、内容仍是箱单 / 草单 | 不用改，看内容 | 否 |
| 新叫法（「装箱明细」「形式发票」） | `sheet_roles.yaml` 已有 role 下加信号 | 否 |
| 新单据类型（产地证、提单 sheet） | 新 `id` + `consume`；若要当主源再改 `fields.yaml` 的 `role_bonus` / `assembly` | 否（打分器已按目录走） |
| 新的扁平海关表头 | `declaration_list.headers` | 否 |
| 其它角色表头也在列里 | 该角色 `head_from_columns: true` | 否 |
| 新辅助表长相对照 / 台账 | `auxiliary` 加表头或标题 | 否 |
| 对不上 | 保持 unknown，整包复核 | 否 |
| layout 键都没拆出来 | 先补 `layout_vocab.yaml` | 视词表 |

不要 `if company == "恒信"`。不要因为 unknown 里抽出了字就当补充。

## 本阶段不做

- 拼一张报关单（#19）
- unknown 自动降级补空

BOX → TdecHead 见 [head-map.md](head-map.md)（#17）。TABLE → 货行见 [goods-map.md](goods-map.md)（#18）。
