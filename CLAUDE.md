# DocParse 开发规范

适用于主仓库（`docparse/`）及所有 worktree（`docparse-*`）。

## 已对齐的产品约束

- 主链路是**固定流水线**，不是 Agent；不引入 LangChain / LangGraph。
- 模型只走**云 API**，不部署本地 LLM / VLM / OCR 大模型。
- 持久化本阶段不实现，只保留 `JobStore` / `FileStore` 接口。
- 流程图以 [docs/flow.html](docs/flow.html) 为准。

## 开发流程（必须）

每次开发按这个顺序，**worktree 绑定一个 Issue**：

```text
1. 先建 Issue（一事一 Issue，写清问题 / 范围 / 验收标准）
2. 从 origin/main 开 worktree + 分支，分支名带 Issue 号
3. 只在该 worktree 里改，不直接动主仓库 main
4. 本地跑通 lint / test
5. 开 PR，描述里写 Closes #编号
6. PR 合并后删除 worktree
```

### 1. 先有 Issue

- 一个 Issue 只做**一件可独立交付**的事（通常对应一个模块，见 [docs/modules.md](docs/modules.md)）。
- 必须写清：要解决什么、改哪些路径、验收标准。
- 没有 Issue 不准开分支。

### 2. Worktree 绑定 Issue

在主仓库目录执行：

```bash
git fetch origin
git worktree add -b feat/12-pdf-parser ../docparse-12-pdf-parser origin/main
```

约定：

| 项 | 规则 | 示例 |
|---|---|---|
| 分支 | `feat/<issue>-<slug>` / `fix/<issue>-<slug>` | `feat/12-pdf-parser` |
| 目录 | 与主仓库同级，`docparse-<issue>-<slug>` | `../docparse-12-pdf-parser` |
| 绑定 | **一个 Issue = 一个 worktree = 一个分支** | 不要把 #12 和 #13 做进同一个 worktree |

不要在 `~/Documents/code/docparse`（主工作树）里直接开发功能。

### 3. PR 与合并

- PR 标题先对齐再创建。
- 描述必须包含 `Closes #编号`。
- 提交作者用 `1018067278@qq.com`，不加 Co-Authored-By Claude。
- push / 建 PR 前先确认。
- 本仓库是个人仓：**CI 绿且确认后合并**。不要直接推 main。

### 4. 建仓例外

仓库初始化（本骨架）可以直接落在 `main`。从第一个功能模块开始，一律走上面的 Issue → worktree → PR。

## 实现时怎么改

- 先看 [docs/modules.md](docs/modules.md)，只改该 Issue 对应的模块目录。
- 字段清单只改 `src/docparse/schema/fields.yaml`，不要把字段写死在流水线里。
- 换存储 / 换模型供应商只加 adapter，不改 `pipeline/`。
- 每个字段必须能带证据；没有证据不能标 `accepted`。
