# DocParse

多格式单据解析骨架：用户上传压缩包 / PDF / Excel / 图片，流水线解析出报关单号等业务字段。

当前阶段是**框架层**。需求方尚未给出真实样本和字段清单，因此：

- 主链路是确定性流水线，不是 Agent，也不引入 LangChain / LangGraph
- 模型只通过云 API 调用，不部署本地大模型
- 持久化先不实现，接口和数据模型已预留，后续可换成 PostgreSQL + 对象存储

## 快速开始

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

uvicorn docparse.api.app:app --reload --port 8088
```

健康检查：

```bash
curl http://127.0.0.1:8088/health
```

同步解析一份本地文件（不经过 HTTP）：

```bash
python -m docparse.cli parse path/to/file.zip
```

## 文档

- [流程图](docs/flow.html)（浏览器用 `file://` 打开本地文件）
- [设计文档](docs/design.md)
- [模块地图](docs/modules.md)（后期按模块拆 Issue）
- [字段 Schema 占位](docs/field-schema.md)
- [持久化预留](docs/persistence.md)
- [开发规范](CLAUDE.md)

## 开发流程

```text
Issue → worktree（绑定该 Issue）→ 实现模块 → PR（Closes #）→ 合并
```

一个 Issue = 一个 worktree = 一个分支。不要在主仓库 `main` 上直接改功能。细节见 [CLAUDE.md](CLAUDE.md)。

## 仓库约定

- GitHub 个人账号：`Baldwinzc`
- 提交邮箱：`1018067278@qq.com`
