# 合单对接交付

给合单 / 业务对接：怎么在本机跑起来、调哪个口、字段什么意思、要什么 Key。开发模块细节见文末链接，本文不展开流水线。

当前阶段：xlsx / xls / PDF（文字层或扫描）/ jpg / png → 一张出口报关单。主链路是固定流水线，不是 Agent。任务存在内存里，进程退出即丢。客户原件不入库。

**部署前提：纯内网可跑，数据不出网**（#94）。xlsx / xls / 文字层 PDF 全程本地；扫描件 / 图片默认走**本地 OCR 引擎**（PaddleOCR PP-OCRv6 small + doc-ori，#99 / #110），也是纯内网。云 OCR（合合 TextIn）保留为显式备选，云端默认关，只有显式配了密钥**并且**开了闸才外呼。离线部署包与权重分发见第 1 节。

合单请打 **`POST /v1/declare`**。浏览器对眼打 `/v1/jobs`，不要混用信封。

---

## 1. 部署（离线可跑，无需外网）

交付形态沿用 #92：**压缩包解压即用，不写仓库地址**。区别是这次的包比 #92 那次多两样——Python 依赖的 wheel 与 OCR 权重，因为目标机没有外网。三件事按顺序：**打包方打一次包 → 交付方离线装 → 起服务**。

### 1.1 包长什么样

```
docparse-offline-<日期>/
├── docparse/          # 源码：有 pyproject.toml 的那一层（就是 #92 那个压缩包的内容）
├── wheels/            # 全部 Python 依赖的 wheel，离线装用
├── models/            # OCR 权重缓存（PaddleX 格式），离线跑扫描件用
│   └── official_models/
│       ├── PP-OCRv6_small_det/      # 文本检测
│       ├── PP-OCRv6_small_rec/      # 文本识别
│       └── PP-LCNet_x1_0_doc_ori/   # 整页方向分类
├── requirements.txt   # wheels/ 的清单（定版），离线装照它装
├── uv / python/       # 见 1.4：目标机没有 Python 3.11 时用（可选）
└── SHA256SUMS         # models/ 下每个文件的 sha256
```

三条要记住：

- **权重文件不入仓库**（#94 约束）。`models/` 只在交付包里。实测三个模型合计约 **37 MB**（det 9.7 + rec 21 + ori 6.6）。
- **`wheels/` 与目标机绑定，不能换机器复用**：wheel 文件名带 `cp311` 与平台标签，而且 **GPU 机装 `paddlepaddle-gpu`、CPU 机装 `paddlepaddle`**，两个不是同一个包。给 CPU 机打一个 GPU 包等于装了一堆用不上的 CUDA 运行库（实测 GPU 版 `wheels/` 约 **4.1 GB**，大头就是这些 CUDA 库；CPU 版小得多）。
- **权重与依赖是两回事**：xlsx / 文字层 PDF 不需要 `models/`，扫描件 / 图片才需要。只跑前两类的话包可以不含 `models/`。

### 1.2 目标机要什么

| 项 | 要求 | 不满足会怎样 |
|---|---|---|
| 系统 | Linux x86_64 | — |
| Python | **3.11**（3.11 任意小版本都行） | wheel 名里是 `cp311`，3.10 / 3.12 装不了（见 1.4 的兜底） |
| 外网 | **不需要** | — |
| 磁盘 | ≥ 8 GB（wheels 4.1 + venv 约 3 + 权重 0.04） | 装到一半失败 |
| GPU | **可选**。有 NVIDIA 卡走 GPU，没有走 CPU——功能一样，只是慢 | 按 1.5 的 `DOCPARSE_LOCAL_OCR_DEVICE` 显式指定 |

本次实测环境（既是打包机，也是一次验收机）：Ubuntu 20.04、Python 3.11.17、paddlepaddle-gpu 3.3.1（cu126 源）、paddleocr 3.7.0 / paddlex 3.7.2、RTX 4090 24 GB、驱动 580.95.05、500 GB 内存。

### 1.3 打包（打包方做一次，要外网）

在**和目标机同类**的机器上做（GPU 包就在 GPU 机上打）。三步：

```bash
# 0) 先在一个能上网的 venv 里把依赖装全（GPU 机务必按 README「GPU 机器」那条走，
#    不要用 .[local-ocr] extra——它钉的是 CPU 版 paddlepaddle）
pip freeze --exclude-editable > requirements.txt

# 1) 依赖 → wheels/
python -m pip download -d wheels -r requirements.txt \
  --extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/   # 仅 GPU 机需要

# 2) 权重 → models/：跑一次扫描件，让 PaddleX 自己下到默认缓存，再整目录拷出来
python -m docparse.cli declare 任意扫描件.pdf
cp -r ~/.paddlex/official_models models/

# 3) 校验清单
(cd models && find . -type f -exec sha256sum {} + | sort -k2 > ../SHA256SUMS)
```

**权重目录在哪**：PaddleX 3.x 把权重缓存在 `$PADDLE_PDX_CACHE_HOME/official_models/`，该变量不设时默认 `~/.paddlex`。所以第 2 步拷的就是 `~/.paddlex/official_models`，目标机放回去也是这个位置（或用 `PADDLE_PDX_CACHE_HOME` 指过去，见 1.5）。

**为什么必须先跑一次**：权重不会随 `pip install` 落地，是**首次真正识别时**才去模型站拉的（实测会依次试 aistudio → modelscope，每个模型 6 个文件）。这一步是打包方唯一需要外网的地方，做完目标机就再也不需要了。

### 1.4 离线安装（交付方，目标机）

```bash
cd docparse-offline-<日期>

# 0) 先校验权重没坏
(cd models && sha256sum -c ../SHA256SUMS)

# 1) 建 venv（目标机自带 python3.11）
python3.11 -m venv .venv

# 2) 装依赖 —— 只认包里的 wheels/，一个包都不外呼
.venv/bin/pip install --no-index --find-links wheels -r requirements.txt

# 3) 装本项目（-e 是为了以后能改 .env / 词表）
.venv/bin/pip install --no-index --find-links wheels -e docparse
```

第 3 步用 `-e` 装，`wheels/` 里要**带上构建后端**（`hatchling`、`pathspec`、`trove-classifiers`、`editables`、`pluggy`、`packaging`、`tomlkit`、`setuptools`），否则离线时它下不到构建依赖，pip 报 `ERROR: No matching distribution found for hatchling`、uv 报 `docparse = ["hatchling"]`，就停住。

**目标机没有 Python 3.11**：包里带了两个单文件——`uv`（一个静态二进制，不用装）和 `python/`（一份独立的 CPython 3.11，约 96 MB）。用它们建 venv：

```bash
export UV_PYTHON_INSTALL_DIR="$PWD/python"
./uv venv --python 3.11 .venv
./uv pip install --python .venv/bin/python --no-index --find-links wheels -r requirements.txt
./uv pip install --python .venv/bin/python --no-index --find-links wheels -e docparse
```

`uv` 的 `--no-index --find-links` 语义与 pip 相同，同样一个包都不外呼。

### 1.5 启动与访问

```bash
cd docparse-offline-<日期>/docparse
cp .env.example .env

# 权重目录：paddlex 直接读进程环境，写进 .env 它看不见，必须 export
export PADDLE_PDX_CACHE_HOME="$PWD/../models"
# 离线机跳过「探测哪个模型站能连」这一步，省几秒启动等待
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

PYTHONPATH=src .venv/bin/python -m uvicorn docparse.api.app:app \
  --host 0.0.0.0 --port 8088
```

**为什么 `PADDLE_PDX_CACHE_HOME` 要 export 而不是写进 `.env`**：`.env` 只被 `DOCPARSE_*` 那套配置读，paddlex 是直接读进程环境的。要长期跑就写进启动脚本 / systemd unit，别只写 `.env`。

验活与访问：

```bash
curl http://127.0.0.1:8088/health
# {"status":"ok"}
```

对眼页：浏览器打开 http://127.0.0.1:8088/review （`/` 同一页）。

**访问方式**：服务绑 `0.0.0.0:8088`，但云主机一般只对外开了 SSH 端口，8088 从外面直连不到。用 SSH 本地转发，在**你自己电脑**上执行：

```bash
ssh -p <ssh端口> -N -L 8088:127.0.0.1:8088 root@<服务器地址>
# 然后浏览器 / curl 打本机 http://127.0.0.1:8088
curl -s http://127.0.0.1:8088/health
```

要长期常驻、随机器重启拉起来，把上面的启动命令写进 `start.sh`，用 `nohup ./start.sh > service.log 2>&1 &` 拉起（容器里没有 systemd）。

任务和上传文件都在进程内存，**不要当多进程 / 多机部署**，重启即空。

### 1.6 端到端验证（装完必做）

两张件各跑一次，覆盖两条完全不同链路：**xlsx 全程本地规则**，**扫描 PDF 走本地 OCR + 版面重建**。

```bash
cd docparse-offline-<日期>/docparse
export PADDLE_PDX_CACHE_HOME="$PWD/../models"
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

# a) xlsx 草单
PYTHONPATH=src .venv/bin/python -m docparse.cli declare /路径/草单.xlsx

# b) 扫描 PDF（首次会加载权重，比 a 慢；之后再跑就走缓存）
PYTHONPATH=src .venv/bin/python -m docparse.cli declare /路径/扫描件.pdf
```

`cli declare` 打印的是对眼形状（字段上是名称，带 `_meta`），合单信封请走 HTTP `/v1/declare`。

**怎么判断真的通了**（本次实测口径）：

| 检查 | xlsx | 扫描 PDF |
|---|---|---|
| 进程退出码 | `0` | `0` |
| 表头 | `contrNo` / `packNo` / `grossWt` / `netWt` 有值 | 同上，数字与原件一致 |
| 货表 | `tdecGoodsitemsVoArr` 每条有 `codeTs` / `declTotal` | 同上 |
| 关键：**根本不是空的** | 输出里有 `"cusIEFlag": "E"` 起头的一整片字段 | 同上，**不是 `{}`** |

输出是 `{}` 就是没抽到——按 1.7 查。

**更狠的一次验证**（可选，交付时推荐做一遍）：把出网封掉再跑一次 b。最省事的做法是给进程塞一个屏蔽域名解析的 `sitecustomize.py`——Python 启动时会自动 import 它，不用改任何业务代码：

```python
# /任意目录/offlinecheck/sitecustomize.py
import socket
_orig = socket.getaddrinfo
def _blocked(host, *a, **k):
    if host in ("127.0.0.1", "localhost", "::1", None):
        return _orig(host, *a, **k)
    raise socket.gaierror(-2, f"断网验证：拒绝解析 {host!r}")
socket.getaddrinfo = _blocked
```

```bash
PYTHONPATH=/任意目录/offlinecheck:src .venv/bin/python -m docparse.cli declare /路径/扫描件.pdf
```

本次实测口径：封掉解析后，两条路径的退出码、表头、货行数**与联网时逐字段一致**。仓库里另有自动化版本：`tests/test_offline_gate.py`（拦 httpx transport，覆盖纯 xlsx 与扫描 PDF 两条路径，`pytest tests/test_offline_gate.py`）。

### 1.7 故障排查

先看**现象在哪一层**：`/v1/declare` 返回 `{"code":2,"msg":"解析失败"}` 只知道失败了；**具体原因在 `/v1/jobs` 的信封里**——`result.package.documents[].warnings` 有原文，CLI 侧对应的是 `python -m docparse.cli layout` 打的 `warnings`。

| 现象 | 说明 | 怎么处理 |
|---|---|---|
| `本地 OCR 引擎不可用（…）：未安装 paddleocr；pip install -e ".[local-ocr]"` | **依赖没装全**。引擎是懒加载的，缺依赖不崩、不报错，只在这一条 warning 里说 | 按 1.4 补装 `wheels/`。离线机改成 `pip install --no-index --find-links wheels paddleocr paddlepaddle-gpu pillow` |
| `本地 OCR 引擎加载失败（…）：No available model hosting platforms detected. Please check your network connection.` | **权重缺失 + 无外网**——PaddleX 找不到缓存，又连不上模型站 | 权重没放对位置。确认 `models/official_models/` 三个目录都在，且 `PADDLE_PDX_CACHE_HOME` 指到了 `models/`（见 1.5）。空目录、路径写错都会走到这条 |
| `本地 OCR 引擎加载失败（…）：(Unavailable) Cannot read tensor desc size …` | **权重文件坏了 / 拷了一半** | `sha256sum -c SHA256SUMS` 对一遍，重拷 |
| `本地 OCR 识别失败（…）：…Out of memory…` | **显存不足**。引擎加载与识别两处都被同一段兜底接住，所以 OOM 报在哪一步就带哪个前缀 | 换卡 / 腾显存 / 降并发；纯出结果优先就 `DOCPARSE_LOCAL_OCR_DEVICE=cpu` 走 CPU（慢但一定跑得动） |
| `第N页：整页方向分类判定 0°（置信度 …）` | **不是故障**，正常运行信息。方向分类每次都会记一条 | 忽略。旋转页在这里会报非 0 的角度 |
| 输出是 `{}`，且上面几条都没有 | 抽到了但没组装成单 | 看 `/v1/jobs` 的 `reviews`（哪个 sheet、哪个格子），再对 [field-schema.md](field-schema.md) |
| 第一次跑 stdout 混进 `<Response [404]>` 之类的杂行 | PaddleX 下载器探测模型站时打到 stdout 的，**只在首次下载时出现** | 权重放好就不会有；脚本里 `json.load` 前先剥到第一个 `{` |

**降级口径**（对齐 #98）：上面四种引擎故障**一律不抛异常、不编造文字**——那一页识别结果为空，文档继续走下游，最终 `/v1/declare` 给 `code=2`。CPU 路径是 #98 实测过的最低保底：慢，但结果一致。

**别被 `job.status` 骗了**：整页 OCR 全失败时，文档一张 sheet 都没有，也就没有任何字段进复核，`/v1/jobs` 的 `status` 会是 **`succeeded`**，但 `result.declaration` 是 `null`、`/v1/declare` 是 `code=2`。**看到 `succeeded` 不等于抽到了东西**——先确认 `documents[].sheets` 不是 0、`declaration` 不是 `null`。（两者不一致是已知缺口，见下。）

**两个已知缺口**（都不影响本期验收，记在这里免得当成环境问题）：

- 引擎的 warning 只落在 `result.package.documents[].warnings`，**没有并进 `/v1/declare` 的信封**，合单侧看到的就一句干巴巴的「解析失败」；排查必须回头打 `/v1/jobs`。
- 上一条导致「一张 sheet 都没解析出来」时 `status` 仍是 `succeeded`，而不是 `needs_review` / `failed`。

### 1.8 一次实际部署记录（2026-10-06）

本节数字来自**一次真实的离线部署验收**，用来佐证上面几步是可复现的，不是纸面推演。

| 项 | 实测 |
|---|---|
| 机器 | 一台不带外网的 GPU 服务器，Ubuntu 20.04 容器、500 GB 内存、多卡（含 RTX 4090 24 GB）、驱动 580.95.05 |
| 起点 | 只有系统自带的 Python 3.8，**没有 3.11** → 走 1.4 的兜底路线（uv 自带 CPython） |
| 依赖 | paddlepaddle-gpu 3.3.1（cu126）+ paddleocr 3.7.0 + paddlex 3.7.2 + pymupdf 1.28.2 |
| 权重 | 首次识别自动下载 3 个模型共约 **37 MB**，落在 `~/.paddlex/official_models/` |
| 依赖包体积 | GPU 版 wheelhouse 117 个文件、**4.1 GB**；自带 CPython + uv 另约 **142 MB** |
| 第一轮：xlsx 草单（程序造的恒信结构件） | 退出码 0；`tradeName` / `contrNo=HDX2026-251` / `packNo=40` / `grossWt=296.46` / `netWt=218.375` 均有值；HTTP `/v1/declare` 给 `code=0`，`supvModeCdde` 转成 `0110`、`cusTrafMode` 转成 `4` |
| 第二轮：扫描 PDF（程序造的仿真报关单，无文字层） | 退出码 0；`packNo=120`、`grossWt=1459.62`、`netWt=485.00`、`contrNo=EX-20260824-01`、3 条货行带 `codeTs` / `declTotal` / `tradeCurr`；HTTP `/v1/declare` 给 `code=0`，耗时约 13 s（含模型加载，热跑约 15 s 的 CLI 含解释器启动） |
| 断网复验 | 封掉域名解析后，两条路径退出码、表头、货行数与联网时**逐字段一致** |
| 离线包复装 | 两条路线各在一个全新 venv 里从 `wheels/` + `models/` 装完并跑通扫描件，结果与上面完全一致：① 自带 `python3.11` + pip；② 包里的 `uv` + 独立 CPython |

**没覆盖到的**：真实显存打满没在本机复现（卡被别的任务占着，不便压满），OOM 那一行是按同一处兜底代码路径 + 单测写的；多卡并发与吞吐不属本文，看 [capacity-benchmark.md](capacity-benchmark.md)。

---

## 2. 环境变量与 Key

复制 `.env.example` 为 `.env`。前缀一律 `DOCPARSE_`。

**默认不出网**：`DOCPARSE_ALLOW_CLOUD` 默认 `false`，云 OCR 与云 LLM **连请求都不构造**——下面两处云端 Key 填了也不外发（#94 / #100 硬闸）。要外呼必须显式把它改 `true`，这一步是刻意的。

| 变量 | 何时要 | 没有会怎样 |
|---|---|---|
| `DOCPARSE_ALLOW_CLOUD` | **要外呼就必须设 `true`**（云 OCR 或云 LLM 任一） | 保持 `false`（默认）时两个云 client 都不发 HTTP，只登记告警、文档进 `needs_review`；xlsx / 文字层 PDF / 本地 OCR 不受影响 |
| `DOCPARSE_OCR_ENGINE` | 扫描件 / 图片用哪个引擎：`local`（默认，纯内网）或 `textin`（云，显式选才走） | 默认 `local`，指本地 PaddleOCR，**不读下面的 TextIn 密钥、也不外呼** |
| `DOCPARSE_LOCAL_OCR_DEVICE` | `auto`（默认，有 CUDA 用 gpu，否则 cpu）/ `cpu` / `gpu` | 默认 `auto`。显存不足或缺权重时显式写 `cpu` 是保底 |
| `DOCPARSE_TEXTIN_APP_ID` | 扫描件 PDF、jpg/png 要**走云**时（本地引擎 #99 已默认接管，一般不必） | 流水线不崩、**也不外呼**；该页没有文字，后续字段空、对眼页 `needs_review` |
| `DOCPARSE_TEXTIN_SECRET_CODE` | 同上 | 同上 |
| `DOCPARSE_LLM_LOCAL_API_KEY` | **本期合单不需要** | 规则抽不到的字段保持空，不调模型，**不外呼** |
| `DOCPARSE_LLM_ENGINE` | 要用模型时：`local`（默认，内网 vLLM / Ollama）或 `cloud` | 保持 `local`：指内网端点，**同样要开 `DOCPARSE_ALLOW_CLOUD`** 才发请求 |
| `DOCPARSE_LLM_LOCAL_BASE_URL` / `DOCPARSE_LLM_LOCAL_MODEL` | `llm_engine=local` 时 | 默认 `http://127.0.0.1:11434/v1` + `qwen3:4b`；本地端点通常不鉴权，KEY 可留空 |
| `DOCPARSE_LLM_BASE_URL` / `DOCPARSE_LLM_MODEL` / `DOCPARSE_LLM_API_KEY` | 仅 `llm_engine=cloud` 时 | 走云端 OpenAI 兼容口，**必须配 Key**，且仍要开 `DOCPARSE_ALLOW_CLOUD`（#101） |

**不在 `.env` 里、但要 export 的两个**（paddlex 直接读进程环境，`.env` 只被 `DOCPARSE_*` 那套读）：

| 变量 | 设成什么 | 不设会怎样 |
|---|---|---|
| `PADDLE_PDX_CACHE_HOME` | 权重目录的**绝对路径**（交付包里是 `.../models`） | 回落到 `~/.paddlex`；离线机上那里是空的 → 权重缺失，扫描件整页抽空 |
| `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` | `True` | 每次启动多一次「探测哪个模型站能连」的等待；离线机上必然失败但会被兜住 |

xlsx / 有文字层的 PDF 本来就不出网。扫描件现在**默认走本地引擎**（#99：PaddleOCR PP-OCRv6 small + doc-ori），不配 TextIn、不开闸也能跑；引擎 / 权重不可用时该页抽空、不崩、不编字，最终 `/v1/declare` 给 `code=2`（现象与排查见 §1.7）。零外呼这件事有留在仓库的自动化验证：`tests/test_offline_gate.py`（拦 httpx transport，覆盖纯 xlsx 与扫描 PDF 两条路径）。

申请：合合 TextIn 开放平台 → 通用文字识别（多页）`https://api.textin.com/ai/service/v2/recognize/multipage`。选型记录见 [ocr-benchmark.md](ocr-benchmark.md)（历史基线）。QPS 超限（官方 40306）只告警不重试。**纯内网部署的打包 / 离线安装 / 权重分发见第 1 节。**

不要配、本期也接不上：

| 变量 | 说明 |
|---|---|
| `DOCPARSE_JOB_STORE` / `DOCPARSE_FILE_STORE` | 保持 `memory`。写成 `postgres` / `s3` 会直接报未实现 |
| `DOCPARSE_DATABASE_URL` / `DOCPARSE_S3_*` | 预留，未实现 |

其它默认：上传上限 100 MB（超限 HTTP 400）。zip 层数 / 体积闸已留，**zip 多文件拼一张单尚未交付**。

---

## 3. 接口一览

| 方法 | 路径 | 给谁 |
|---|---|---|
| `GET` | `/health` | 探活 |
| `POST` | `/v1/declare` | **合单主入口** |
| `POST` | `/v1/jobs` | 对眼页；同步跑完返回 Job |
| `GET` | `/v1/jobs/{id}` | 查一次任务（内存，重启失效） |
| `GET` | `/v1/jobs` | 列出内存里的任务 |
| `GET` | `/v1/schema` | 对眼页字段中文名 |
| `GET` | `/review` 或 `/` | 静态对眼页 |
| `GET` | `/openapi.json` | Swagger 描述 |

每个请求会带 `X-Request-Id`（可自带，没有则生成），写进响应头。

合单对接 **只需要** `/health` + `/v1/declare`。OpenAPI 文档：起服务后打开 http://127.0.0.1:8088/docs 。

---

## 4. 合单入口 `POST /v1/declare`

`multipart/form-data`，同步跑完。忽略 `run`。

### 请求

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | xlsx / xls / pdf / jpg / png。文件名带对后缀 |
| `agentCode` | 否 | 10 位申报单位海关代码。不传则泰洲 `4403180867` |
| `agentName` | 否 | 申报单位名称。默认「深圳市泰洲物流有限公司」 |
| `agentScc` | 否 | 18 位信用代码。默认 `914403000539716870` |
| `agentCiqCode` | 否 | 检验检疫代码。默认 `4700910159` |
| `cusIEFlag` | 否 | `E` 出口（默认）/ `I` 进口。本期按出口做 |

申报单位**不从文件解析**，只认请求或 YAML 默认。生产销售单位（`owner*`）文件里有就抽。未知 form 键忽略，不 400。

```bash
curl -s http://127.0.0.1:8088/v1/declare \
  -F "file=@/绝对路径/草单.xlsx" \
  -F "agentCode=4403180867" \
  -F "agentName=深圳市泰洲物流有限公司"
```

### 响应信封

对齐 Demo 识别结果（`code` / `msg` / `result` / `dec_results`）。

```json
{
  "code": 0,
  "msg": "操作成功",
  "result": true,
  "dec_results": { }
}
```

| `code` | `result` | `dec_results` | 何时 |
|---|---|---|---|
| `0` | `true` | 一张报关单 | 抽出了单（含待复核字段） |
| `2` | `false` | `null` | 解析/组装失败 |
| HTTP 400 | FastAPI `{"detail":"..."}` | — | 没带 file、空文件、超过 100 MB |
| HTTP 500 | `{"detail":"internal error"}` | — | 未映射的服务器异常 |

业务失败不是 500。缺字段、转不出海关码、件毛净对不上：**仍然 `code=0` 交单**，空着的键是 `""`，不删键。对眼页用 `/v1/jobs` 看复核原因。

`dec_results` 相对对眼 JSON 的差别：

- 没有 `_meta`、货行没有 `_source`
- 能转上海关码的字段输出 **code**（`supvModeCdde` 为 `"0110"` 不是「一般贸易」）；转不出则留原文
- 出口填死：`dataSource="7"`，`promiseItem1/2/3="0"`
- `packName` / `packType` 复制 `wrapType`
- 每条货生成 `id`（UUID），不进抽取、每次请求不同

完整契约见 [api.md](api.md)。

---

## 5. `dec_results` 字段要点

完整目录、锚点、码表见 [field-schema.md](field-schema.md) 与 [`src/docparse/schema/fields.yaml`](../src/docparse/schema/fields.yaml)。这里只列合单会碰到的键。抽不到就是 `""`，不编造。本期不区分必填/选填。

### 调用方（请求传入）

| 键 | 含义 |
|---|---|
| `agentCode` | 10 位申报单位海关代码 |
| `agentName` | 申报单位名称 |
| `agentScc` | 18 位信用代码 |
| `agentCiqCode` | 检验检疫代码 |

### 表头常用

| 键 | 含义 | 备注 |
|---|---|---|
| `cusIEFlag` | 进出口类型 | 默认 `E` |
| `entryType` | 报关单类型 | 参考常为 `M`，草单常空 |
| `contrNo` | 合同协议号 | |
| `tradeName` / `tradeCode` / `tradeScc` / `tradeCiqCode` | 境内收发货人 | 名称格末尾 10 位海关码会拆到 `tradeCode` |
| `consignorEname` | 境外收发货人英文名称 | 出口「境外收货人」；进境「境外发货人」同一字段 |
| `ownerName` / `ownerCode` / `ownerScc` / `ownerCiqCode` | 生产销售 / 消费使用单位 | 文件里有就抽 |
| `customMaster` | 申报地海关 | 四位关区，如 `5341` |
| `iePort` | 进/出口口岸 | 草单「出境关别 / 进境关别」。**不要**和申报地海关混 |
| `ciqEntyPortCode` | 入境/离境口岸 | CIQ，不是四位关区 |
| `distinatePort` | 经停港 / 指运港 | 如 `HKG000` |
| `despPortCode` | 启运港 | 出口常空 |
| `cusTrafMode` | 运输方式 | code，如公路 `4` |
| `trafName` / `cusVoyageNo` | 运输工具名称 / 航次 | 同一格时整格先挂名称，拆航次见已知缺口 |
| `billNo` | 提运单号 | |
| `manualNo` | 备案号 | |
| `licenseNo` | 许可证号 | |
| `supvModeCdde` | 监管方式 / 贸易方式 | 字段名按 Demo 原样（Cdde）。一般贸易 `0110` |
| `cutMode` | 征免性质 | 一般征税 `101` |
| `cusTradeNationCode` | 贸易国别 | 三位国别码 |
| `cusTradeCountry` | 启运(运抵)国 | 出口=运抵国 |
| `wrapType` | 包装种类 | `packName` / `packType` 与此相同 |
| `packNo` | 件数 | |
| `grossWt` / `netWt` | 毛重 / 净重（公斤） | 只有净重则毛重空着，不把净重抄进毛重 |
| `transMode` | 成交方式 | FOB=`3` |
| `feeMark` / `feeRate` / `feeCurr` | 运费 | 同格未拆，常空 |
| `insurMark` / `insurRate` / `insurCurr` | 保费 | 同上 |
| `otherMark` / `otherRate` / `otherCurr` | 杂费 | 同上 |
| `markNo` | 标记唛码 | 抽不到不编 `N/M` |
| `noteS` | 备注 | |
| `goodsPlace` | 货物存放地点 | |
| `entryId` / `preEntryId` | 海关编号 / 预录入编号 | 未申报常空 |
| `declDate` / `ieDate` | 申报日期 / 进(出)口日期 | 不是同一个字段 |
| `attachedDocs` | 随附单证原文 | 结构化数组见空数组 |
| `promiseItems` | TCS 承诺事项 | 常空 |

码表精确匹配中文名。俗称（「莲塘口岸」「纸箱」）转不出码时字段留原文，不瞎填。俗称别名尚未做（#27）。

### 商品 `tdecGoodsitemsVoArr[]`

| 键 | 含义 |
|---|---|
| `gno` | 项号 |
| `codeTs` | HS 商品编号 |
| `gname` | 品名 |
| `gmodel` | 规格 / 申报要素 **原文**。本期不编 `0\|0\|...` |
| `brand` | 品牌 |
| `gqty` / `gunit` | 成交数量 / 成交单位 |
| `declPrice` / `declTotal` / `tradeCurr` | 单价 / 总价 / 币制 |
| `qty1` / `unit1` / `qty2` / `unit2` | 法定数量与单位 |
| `cusOriginCountry` | 原产国 |
| `destinationCountry` | 最终目的国 |
| `districtCode` | 境内货源地 / 目的地（区划码） |
| `ciqDestCode` | 目的地检验检疫码（从双码前缀拆出） |
| `dutyMode` | 征免方式（与表头 `cutMode` 不是同一个） |
| `customGrossWet` / `customNetWt` | 行毛重 / 行净重（json 原字段名 Wet） |
| `exgVersion` | 加工成品单耗版本号，一般贸易常空 |
| `id` | 出口生成的 UUID |

有海关商品表以它为主；箱单 / 发票只补空，不另出一张报关单。

### 出口填死 / 空数组

| 键 | 值 |
|---|---|
| `dataSource` | `"7"` |
| `promiseItem1` / `2` / `3` | `"0"` |

下列合单 Demo 有、本期不展开，输出 `[]`：`tdecContasVoArr`（集装箱）、`tdecCoplimitVoArr`、`tdecDocusVoArr`、`tdecEdocRealationVoArr`、`tdecOthersPacksVoArr`、`tdecRequCertVoArr`、`tdecUsersVoArr`、`tdecEcoRelVoArr`、`tdecGoodsitemsVin`。国光那种已填集装箱的样本，这边仍是空数组。

系统主键不解析、不输出：`sysBillNo`、`ownerCompanyId` / `Code` / `Name`、`requestId`、`headId`、`decId`。

---

## 6. 对眼页（可选）

合单不要依赖这个口。本地看抽得对不对：

1. http://127.0.0.1:8088/review
2. 上传同一份文件
3. 页走 `POST /v1/jobs`：字段上是 **中文名**，旁边才是 code；并列出 `reviews`（哪张 sheet、哪个格子）

Job 里还有 `result.package`（版面 IR），合单不要吃。

---

## 7. 已知限制（交接时要说清）

- **zip 多文件拼一张单**：未交付。请单文件上传。
- **`gmodel`**：申报要素原文，不编规范 `0|0|材质|...`。
- **运费 / 保费 / 杂费、航次、唛码与备注**：常与别的字写在同一格，尚未拆成 Mark/Rate/Curr、`trafName`+`cusVoyageNo`、`markNo`+`noteS`（#34–#36）。
- **发票号**：目录无槽位（#37），对不上只复核，不塞进现有字段。
- **俗称转码**（莲塘口岸、纸箱）：码表精确匹配，转不出留原文（#27）。
- **币制等码表**：客户参数表缺 sheet，有的字段转不出 code。
- **内存存储**：不能多实例、不能重启后查单。
- **扫描件的本地 OCR 已是默认路径**（#99 / #110：PaddleOCR PP-OCRv6 small + doc-ori）。要跑扫描件就得有 `models/` 里的权重，否则整页抽空（现象与处置见 §1.7）。合合 TextIn 仍在，但要显式选 `DOCPARSE_OCR_ENGINE=textin` **并且**开 `DOCPARSE_ALLOW_CLOUD`，是备选不是默认。
- **引擎的 warning 不进 `/v1/declare` 信封**，也不改 `job.status`：整页 OCR 全失败时 `/v1/jobs` 仍报 `succeeded`，只是 `declaration` 为 `null`。排查看 `documents[].warnings`（见 §1.7）。
- **不按公司写解析器**：新叫法加 YAML 词表 / 锚点，不要 `if 恒信`。
- **客户原件不进 git**。测试夹具在 `tests/`，真机样本在对接方本地；OCR 权重同样不入仓库（在交付包的 `models/` 里）。

---

## 8. 建议联调顺序

1. `GET /health`
2. 上传一份 xlsx 草单（恒信结构即可）→ `code=0`，看 `contrNo`、`tdecGoodsitemsVoArr`、`agentName`
3. 同一文件再打 `/v1/jobs`，对照中文名和 reviews
4. 传扫描 PDF → 应有 `dec_results`，不再是 `null`。**默认走本地 OCR**，前提是 `models/` 权重在位（§1.4 / §1.5）；返回 `{}` 或 `code=2` 先按 §1.7 查
5. 不传 `file` → 400

字段对不上先看对眼页的格子证据，再对 [field-schema.md](field-schema.md) 的锚点，不要先改合单字段名。

---

## 9. 还要往下看时

| 问题 | 文档 |
|---|---|
| 部署 / 离线安装 / 权重分发 | 本文 §1 |
| 故障排查（引擎、权重、显存、外呼） | 本文 §1.7 |
| HTTP 细节 / 错误分界 | [api.md](api.md) |
| 每个字段从哪类格子来 | [field-schema.md](field-schema.md) |
| 名称怎么转 code | [code-tables.md](code-tables.md) |
| 多张表怎么收成一张单 | [assemble.md](assemble.md) |
| 对眼页 | [review.md](review.md) |
| 模块与流水线 | [modules.md](modules.md) |
| 本地 OCR 实测与选型（#97 / #110） | [local-ocr-benchmark.md](local-ocr-benchmark.md) |
| 容量与规格实测（#98，供采购） | [capacity-benchmark.md](capacity-benchmark.md) |
| OCR 云基线（#60，历史对照） | [ocr-benchmark.md](ocr-benchmark.md) |
| 开发约定（Issue / worktree / PR） | [CLAUDE.md](../CLAUDE.md) |

## 10. 以后换引擎 / 换权重 / 换交付形态改哪

| 改动 | 改哪 | 动不动 Python |
|---|---|---|
| 换 / 加 OCR 引擎档位 | 加一个 client 实现 `OcrClient` 协议，在 `adapters/parsers/registry` 侧的 `get_ocr_client` 登记 | 动（只加不改，下游零改动） |
| 换选定的 PaddleOCR 档位（如 small → tiny） | `adapters/parsers/local_ocr.py` 顶部的 `DET_MODEL` / `REC_MODEL` | 动（改常量） |
| 换方向分类模型 | 同上 `ORI_MODEL` | 动（改常量） |
| 权重换版本 / 加一份 | 交付包 `models/official_models/` 与 `SHA256SUMS`；重跑 §1.3 第 2 步 | 不动 |
| 权重放别的位置 | 部署侧改 `PADDLE_PDX_CACHE_HOME`（**不写 `.env`**） | 不动 |
| CPU / GPU 切换 | `.env` 的 `DOCPARSE_LOCAL_OCR_DEVICE` | 不动 |
| 交付包里加东西（如新样本、新校验工具） | §1.1 的目录结构 + §1.3 打包步骤 | 不动 |
| 把 `PADDLE_PDX_*` 收进 `.env` | 要改 `config.py`（新增设置项 + 在懒加载前写进 `os.environ`），再把上一行两条挪进 `.env.example` | 动 |
| 新增依赖 | `pyproject.toml`；**同时重打 `wheels/`**，否则离线机装不上 | 动 |
