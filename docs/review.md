# 报关单对眼页

本地一眼看组装结果，不把 IR 格子摊开。依赖现有 `POST /v1/jobs`，本页不解析。

```bash
cd /Users/baldwin/Desktop/taizhou/docparse
source /Users/baldwin/Desktop/taizhou/docparse/.venv/bin/activate
PYTHONPATH=src uvicorn docparse.api.app:app --host 127.0.0.1 --port 8088
```

打开 [http://127.0.0.1:8088/review](http://127.0.0.1:8088/review)（`/` 同一页）。

页先拉 `GET /v1/schema`（`fields.yaml` 的 display_name / default），再上传走 `POST /v1/jobs`。只画 `declaration` + `reviews`。码表字段主格是名称，旁注 `_meta.codes`。

## 以后新 xlsx / 新叫法改哪

| 你看到的现象 | 改哪里 | 动 HTML / 路由？ |
|---|---|---|
| 新表头 / 货列中文名 | `fields.yaml` display_name | 否 |
| 码表字段要旁注 code | 字段写 `code_table` | 否 |
| 新申报单位字段 | `caller_params` | 否（页按 schema 画输入框） |
| 换默认申报单位 | `caller_params.default` | 否 |
| 复核原因更多 | #20 规则文件 | 否（reviews 原样展示） |
| PDF | #22 / #23 | 否（同一上传口） |

不要在 `review.html` 里写死 `contrNo` / 境内发货人。
