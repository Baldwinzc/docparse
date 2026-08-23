# 商品映射（TABLE → goods）

运行时：`extraction/goods_map.py`。目录在 [`fields.yaml`](../src/docparse/schema/fields.yaml) 的 `goods` / `goods_master`。本地对眼：

```bash
python -m docparse.cli goods /绝对路径/表.xlsx
```

本文件只回答「已经打好角色的货表，怎么收成一张货表」。不切格子（layout）、不认角色（#16）、不拼整单（#19）、不转 code（#14）。

## 输入 / 输出

```text
Sheet.tables + consume
  → 只处理 consume ≠ exclude
  → 列名对 fields.yaml goods.anchors（去空白、大小写不敏感；英文按词边界）
  → 每张 sheet 先出带角色的货行
  → 按 goods_master 计分选一张主表
  → merge_supplement 默认 false：其它 sheet 不补货行
  → 打开关后才补空；对不上的行标来源收成补充项
```

`auxiliary` / `unknown` 的 table 留在 IR，本层不读。

一份 xlsx 最终只有**一张**货表。箱单 / 发票 / 合同不能另开一张报关单。

## 主货表

不看公司名。看已映射到的列 + 角色加权。

| 信号 | 默认分 | 为什么 |
|---|---|---|
| `gno` 项号 | 5 | 海关商品表 |
| `codeTs` 商品编号 / HS | 5 | 税则号 |
| `gmodel` 申报要素 / 规格 | 4 | 海关专用 |
| `gname` 品名 | 3 | 商业单据也有 |
| 数量 / 单位 / 单价 / 总价 / 币制 | 2 | 用户点名的成交信息 |
| 原产国 / 最终目的国 / 境内目的地 | 2 | 用户点名的国别地 |
| `draft` 角色 | +10 | 有草单时草单优先 |
| `packing` / `invoice` | +1 | 无草单时商业单据可比 |
| `contract` | 0 | 合同货表常缺税号，不当默认主表 |

有草单：草单赢。无草单：HS + 申报要素的箱单通常压过只有品名和价的发票。

## `goods_map`

挂在字段上，不写公司分支。

| 值 | 含义 |
|---|---|
| `keep`（默认） | 整格进该字段 |
| `skip` | 本层不映射 |
| `leading_hs` | 列值前缀 8–10 位数字进 `codeTs`（国光「4821900000纸或…」） |
| `raw_review` | 原文进字段，状态 `needs_review`。申报要素不编 `0\|0\|...` |

## 重量

未区分的「重量 / 重量KG」当净重，进 `customNetWt`。**不进** `qty1`。

| 列的语义 | 字段 |
|---|---|
| 明确净重 / N.W. / 总净重 | `customNetWt` |
| 明确毛重 / G.W. / 总毛重 | `customGrossWet` |
| 未区分的重量 | `customNetWt`；合并后仍无毛重列 → 再抄一份到 `customGrossWet` |
| 法定第一数量 | 才进 `qty1` |

表头整单件毛净交 #19。箱数不加商品字段。

## 跨表补空

`goods_master.merge_supplement` 默认 **false**。有草单时箱单 / 发票项次对不齐，不把箱单数量填进草单空列。

打开关后：对行钥匙按 `goods_master.match_keys` 顺序，默认 `gno` → `codeTs` → `gname` → `gqty`。命中唯一一行就停；同名多行再用数量拆开。合计行（没有项号 / 税号 / 品名）丢掉。

- 主表已有列：**不覆盖**
- 主表空的列：补上，证据带来源 sheet
- 对不上、且有税号或非数字品名：补充项，`source_kind=supplement`，`needs_review` 理由 `unmatched_supplement`
- 合同把项号写进品名列这种脏行：不收

## 以后新 xlsx / 新叫法改哪

对照 [#31](https://github.com/Baldwinzc/docparse/issues/31)。先 `cli layout`，再 `cli goods`。

| 你看到的现象 | 改哪里 | 动 Python？ |
|---|---|---|
| 列名没见过，layout 都没拆出表 | `layout_vocab.yaml` TABLE alias | 否 |
| layout 有了，对不上报关字段 | 已有字段的 `anchors` | 否 |
| 语义是新的商品字段 | `fields.yaml` `goods:` 新字段 + anchors | 否（映射器按目录走） |
| 新单据类型要参与补货 | `sheet_roles.yaml` 加 role，`consume: supplement` | 否 |
| 新辅助表（料号对照） | `auxiliary` 加信号 | 否 |
| 主表判定要加信号（备案序号） | `goods_master.signals` | 否 |
| 要再开跨表补货 | `goods_master.merge_supplement: true`，并先改对行钥匙 | 否 |
| 对行钥匙要加（合同货号） | `goods_master.match_keys` | 否 |
| 一列变两字段（新的稳拆） | 新 `goods_map` 值 + 拆分函数 | 是，通用规则，不按公司 |
| 谁覆盖谁（表头件数 vs 货表加总） | `fields.yaml` `assembly` / [assemble.md](assemble.md) | 否 |
| 名称要变成海关 code | #14 / #27 / #19 | 否 |
| 申报要素要编 `0\|0\|...` | 以后另开；本层只留原文 | 视规则 |

不要 `if company == "恒信"`。不要在这一层 `lookup(code_tables)`。不要把列名在 layout 里改写成 `gno`。
