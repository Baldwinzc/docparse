# FastAPI：一张报关单 JSON

`POST /v1/jobs` 收文件和调用方参数，走与 `cli declare` 同一条 pipeline，交出一张报关单。本层不解析、不认公司。

本地：

```bash
uvicorn docparse.api.app:app --host 127.0.0.1 --port 8088
python -m docparse.cli declare /绝对路径/表.xlsx --agent-code 4403180867 --agent-name 深圳市泰洲物流有限公司
```

## 请求

`multipart/form-data`。

| 部分 | 来源 | 说明 |
|---|---|---|
| `file` | 上传 | 本期 xlsx；以后同一接口接 PDF / zip |
| `agentCode` / `agentName` / `agentScc` / `agentCiqCode` | `fields.yaml` `caller_params` | 不解析。没传则用 YAML `default`（泰洲） |
| `cusIEFlag` | `assembly.defaults` 可覆盖 | 默认 `E`；进口传 `I` |
| `run` | 已有 | 默认 true，同步跑完 |

Form 字段名单从 YAML 生成。未知键忽略，不 400。

每个请求生成 `X-Request-Id`（可自带），写进响应头和 Job。

## 响应

还是 Job 信封：

```text
Job
  status              succeeded | needs_review | failed
  request_id
  caller              请求里收下的调用方参数
  result.declaration  与 cli declare 同一份 JSON（含 _meta）
  result.reviews      字段级 status + 证据（sheet / cell / quote）
  result.package      IR / 旧 fields，调试用
  result.error        仅 failed
```

`declaration` 缺的键空字符串，不删键。合单系统丢掉 `_meta` / `reviews` 即可提交。

## 错误分界

| HTTP | 何时 |
|---|---|
| 400 | 空文件、超大、没带 file |
| 200 + `needs_review` | 缺字段、转不出 code、件毛净对不上 |
| 200 + `failed` | 解析/组装 runner 已接住的失败 |
| 404 | job 不存在 |
| 500 | 没映射到的服务器异常 |

业务失败不是 500。映射只在 `api/errors.py`。

## 以后新 xlsx / 新叫法改哪

| 你看到的现象 | 改哪里 | 动 API Python？ |
|---|---|---|
| 新叫法（装箱明细、形式发票） | `sheet_roles.yaml` / `layout_vocab.yaml` / anchors | 否 |
| 新单据类型要参与拼单 | `assembly.fill` / `role_priority` | 否 |
| 新表头 / 货列 | `fields.yaml` | 否（declaration / reviews 按目录收） |
| 新字段要转 code | 字段写 `code_table` + 码表加行 | 否 |
| 多一个申报单位字段 | `caller_params` 加一项 | 否（Form / OpenAPI 从 YAML 生成） |
| 换默认申报单位 | `caller_params` 的 `default` | 否 |
| 调用方要覆盖进出口标志 | 请求带 `cusIEFlag` | 否 |
| 以后上传 PDF | #22 / #23 parser | 否（同一 `POST /v1/jobs`） |
| zip 多文件拼一张单 | assemble / `extract_fields_step` 主文档选择 | 否（入口已是 list） |
| 校验规则 | #20 数据文件 | 否（同一接口自动带闸） |
| 结构化日志 / 错误码 | `api/errors.py` + request_id | 只改挂钩处 |

不要 `if company == "恒信"`。不要在 `routes.py` 写死 `agent*`。
