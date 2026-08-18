# 持久化预留

本阶段 `DOCPARSE_JOB_STORE=memory`、`DOCPARSE_FILE_STORE=memory`。进程退出即丢失，仅用于本地把链路跑通。

## 接口

- `JobStore`：`create` / `get` / `update` / `list`
- `FileStore`：`put` / `get` / `exists`（后续加 `delete`、预签名 URL）

实现位置：

```text
adapters/jobs/memory.py      当前
adapters/jobs/postgres.py    预留，未实现
adapters/files/memory.py     当前
adapters/files/s3.py         预留，未实现
```

工厂按配置名选择实现。新增后端时只加一个模块并在工厂注册，不要改 pipeline。

## 建议表结构（后期）

```text
jobs
  id, status, created_at, updated_at, error, result_json

files
  id, job_id, kind(raw|derived), filename, content_type, uri, byte_size

documents
  id, job_id, file_id, document_type, ir_json

fields
  id, job_id, document_id, name, value, confidence, status, method, evidence_json

reviews
  id, job_id, field_id, action, reviewer, note, created_at
```

对象存储路径建议：

```text
s3://bucket/jobs/{job_id}/raw/{file_id}
s3://bucket/jobs/{job_id}/derived/{file_id}
```

数据库只存 URI 和元数据，不存大文件字节。

## 切换条件

出现以下任一情况再实现 Postgres + S3/MinIO：

- 需要跨进程 Worker
- 需要任务可查询、可重放
- 需要人工复核落库
- 单文件超过内存方案可接受的大小
