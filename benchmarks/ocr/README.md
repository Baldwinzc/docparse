# 云 OCR 引擎实测装置

对应 Issue：[#60](https://github.com/Baldwinzc/docparse/issues/60)。为 #22 选型服务，只测云 API（CLAUDE.md 约束），不装本地 OCR。

## 结构

| 文件 | 作用 |
|---|---|
| `fixtures.py` | 程序渲染仿真出口报关单（GT 精确已知），派生 base / rot90 / rot180 / rot270 / jpeg60 / noise / lowres 七种变体 |
| `engines.py` | 五个云引擎适配器（TextIn 通用、TextIn 报关单、百度、阿里云、腾讯云），纯 httpx + 标准库签名 |
| `metrics.py` | 归一化、CER、字段命中率 |
| `real.py` | 渲染真机样本页（半岛 / 镇发），路径走 `DOCPARSE_OCR_DEMO_DIR`，原件不入仓库 |
| `visualize.py` | 识别框画回原图（`out/viz/`），供人工验收 |
| `run.py` | 编排 CLI |
| `gt_field_map.py` | 夹具 GT 字段名 → TextIn 报关单 API 字段名 |

`out/` 全部产物不入库（图片、原始返回、指标 JSON）。

## 密钥环境变量（不写入仓库）

| 引擎 | 变量 |
|---|---|
| TextIn（两接口同钥） | `TEXTIN_APP_ID`、`TEXTIN_SECRET_CODE` |
| 百度 | `BAIDU_OCR_API_KEY`、`BAIDU_OCR_SECRET_KEY` |
| 阿里云 | `ALIBABA_CLOUD_ACCESS_KEY_ID`、`ALIBABA_CLOUD_ACCESS_KEY_SECRET` |
| 腾讯云 | `TENCENT_SECRET_ID`、`TENCENT_SECRET_KEY` |
| 真机样本目录 | `DOCPARSE_OCR_DEMO_DIR`（默认 `../AI识别Demo`） |
| 指定中文字体 | `OCR_BENCH_FONT`（ttf/ttc 路径，默认自动探测系统字体） |

## 运行

```bash
python -m benchmarks.ocr.run fixtures          # 夹具 + GT → out/
python -m benchmarks.ocr.run real-render       # 真机页 → out/real/
python -m benchmarks.ocr.run call --engine all # 全引擎跑夹具 + 真机
python -m benchmarks.ocr.run call --engine baidu-general --scope fixtures
python -m benchmarks.ocr.run report            # 汇总 → out/report.md
```

## 调用量与费用口径（写死在免费额度内）

夹具 2 页 × 7 变体 = 14 张，真机半岛 2 页 + 镇发 6 页 = 8 张，单引擎一轮 ≤ 22 次调用：

| 引擎 | 免费额度 | 出处 |
|---|---|---|
| TextIn 通用 | 新客 50 页 | [产品页](https://www.textin.com/market/detail/recognize-document-3d1-multipage) |
| TextIn 报关单 | 新客 100 页 | [产品页](https://www.textin.com/market/detail/customs_declaration) |
| 百度标准版 | 每月免费额度 | [价格页](https://cloud.baidu.com/product-price/ocr.html) |
| 阿里云 | 有免费额度（登录控制台确认） | [按量付费](https://help.aliyun.com/zh/ocr/product-overview/pay-as-you-go) |
| 腾讯云 | 1000 次/月 | [计费概述](https://cloud.tencent.com/document/product/866/17619) |

引擎间串行 + 每次调用间隔 1.2s，避免触发 QPS 限制。
