# FastAPI：一张报关单 JSON

两个入口、同一条 pipeline。本层不解析、不认公司。对眼页见 [review.md](review.md)。

| 入口 | 给谁 | 信封 |
|---|---|---|
| `POST /v1/jobs` | 对眼页 | Job + `declaration`（名称 + `_meta`）+ `reviews` |
| `POST /v1/declare` | 合单 | Demo `{code, msg, result, dec_results}`；字段上是 code |

本地：

```bash
PYTHONPATH=src uvicorn docparse.api.app:app --host 127.0.0.1 --port 8088
# 浏览器打开 http://127.0.0.1:8088/review
python -m docparse.cli declare /绝对路径/表.xlsx --agent-code 4403180867 --agent-name 深圳市泰洲物流有限公司
python -m docparse.cli declare /绝对路径/草单.pdf
```

## 请求

两个入口都是 `multipart/form-data`。合单入口忽略 `run`，始终同步跑完。

| 部分 | 来源 | 说明 |
|---|---|---|
| `file` | 上传 | xlsx / xls / PDF / jpg / png；zip 以后拼单 |
| `agentCode` / `agentName` / `agentScc` / `agentCiqCode` | `fields.yaml` `caller_params` | 不解析。没传则用 YAML `default`（泰洲） |
| `cusIEFlag` | `assembly.defaults` 可覆盖 | 默认 `E`；进口传 `I` |
| `run` | 仅 `/v1/jobs` | 默认 true，同步跑完 |

Form 字段名单从 YAML 生成。未知键忽略，不 400。

每个请求生成 `X-Request-Id`（可自带），写进响应头和 Job。

## 对眼响应（`POST /v1/jobs`）

```text
Job
  status              succeeded | needs_review | failed
  request_id
  caller              请求里收下的调用方参数
  result.declaration  与 cli declare 同一份 JSON（含 _meta；字段上是名称）
  result.reviews      字段级 status + 证据（sheet / cell / quote）
  result.package      IR / 旧 fields，调试用
  result.error        仅 failed
```

`declaration` 缺的键空字符串，不删键。

## 合单响应（`POST /v1/declare`）

```text
{
  code          0 有单 / 2 解析失败
  msg
  result        true 仅 code=0
  dec_results   有单时一张报关单；解析失败 null
}
```

`dec_results`：剥 `_meta` / 货行 `_source`；有码的字段写 code；`dataSource` / `promiseItem*` 出口填死；`packName` / `packType` 复制 `wrapType`；货行 `id` 出口生成。策略在 `fields.yaml` `declare_export`。

**有单就交**：`needs_review`（转不出码、缺毛重、gmodel 原文）仍 `code=0` 带 `dec_results`。对眼页继续用 `/v1/jobs` 看复核。只有 runner 接住的解析失败才 `code=2`、`dec_results=null`。

## 错误分界

| HTTP | 何时 |
|---|---|
| 400 | 空文件、超大、没带 file |
| 200 + Job `needs_review` | 对眼：缺字段、转不出 code、件毛净对不上 |
| 200 + `{code:0, dec_results:{...}}` | 合单：有单就交，含待复核字段 |
| 200 + Job `failed` / `{code:2, dec_results:null}` | 解析/组装 runner 已接住的失败 |
| 404 | job 不存在（仅 `/v1/jobs/{id}`） |
| 500 | 没映射到的服务器异常 |

业务失败不是 500。映射只在 `api/errors.py`。合单信封在 `api/export_dec.py`。

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
| 上传 PDF / 图片 | 已接同一入口（#22/#62/#23） | 否 |
| zip 多文件拼一张单 | assemble / `extract_fields_step` 主文档选择 | 否（入口已是 list） |
| 校验规则 | #20 数据文件 | 否（同一接口自动带闸） |
| 合单要多一个忽略键默认值 | `declare_export.constants` | 否 |
| 合单要复制某字段（如 packName） | `declare_export.aliases` | 否 |
| 合单信封 / code 数字 | `api/export_dec.py` | 只改出口 |
| 结构化日志 / 错误码 | `api/errors.py` + request_id | 只改挂钩处 |

不要 `if company == "恒信"`。不要在 `routes.py` 写死 `agent*`。不要把 `/v1/jobs` 改成 Demo 信封。
