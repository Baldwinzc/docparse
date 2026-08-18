# 字段 Schema（占位）

真实字段等需求方给 case 后再填。这里只固定**形状**，让抽取器和校验器可以先接线。

运行时读取 [`src/docparse/schema/fields.yaml`](../src/docparse/schema/fields.yaml)。

## 字段记录

| 键 | 含义 |
|---|---|
| `name` | 程序内字段名 |
| `display_name` | 中文名 |
| `required` | 是否必填 |
| `value_type` | `string` / `date` / `money` / `number` |
| `sources` | 优先从哪些文档类型取 |
| `pattern` | 可选正则 |
| `extractors` | 允许的抽取器，按顺序尝试 |

抽取器约定：

```text
rule        锚点 / 表头 / 正则
llm         云 API 文本结构化抽取
vlm         云 API 视觉模型读局部图（本阶段接口预留）
human       仅人工填写，流水线不得自动写
```

## 结果对象

每个字段输出不是裸字符串，而是：

```json
{
  "name": "customs_declaration_no",
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

需求方字段到位后，优先改 YAML，不要先改流水线代码。
