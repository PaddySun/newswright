# newswright — 全链路最小 Demo（后端，含信息获取扩展）

RSS 抓取 / 定点网页监测 / 搜索关键词 → 去重 → 规则初筛 → 零信任过滤预留位 → LLM 方向打分（含评分理由）→ AI 作者写作（记忆占位符 + 引用硬校验 + 热点风向段）→ 文章/不写落库。另有：APScheduler 定时调度（无人值守）、热榜聚合、博查/腾讯双家搜索底座、四后端相关性排序底座。FastAPI + SQLAlchemy 2.0 + SQLite（ORM 写法保持 PG 可迁移）。

验证结论见仓库外 `doc/草稿与过程文件/全链路demo-验证报告-20260928.md`（V1-V6）与 `doc/草稿与过程文件/信息获取扩展-验证报告-20260928.md`（V7-V11 + Z1，含实测数据）。

## 环境要求

- Python 3.11+（实测 3.13）
- 真实 `.env` 位于**仓库上一级目录**（`../.env`）：
  - 必需：`DeepSeekAPIKey`、`MoarkAPIKey`
  - 搜索/排序（可选，缺失时对应通道降级关闭）：`bochaaiAPIKey`（博查三件套同一把 Key）、`tencentSecretId`/`tencentSecretKey`（腾讯 wsa，CAM 子账号凭据）
  - Key 任何情况下不进 git；`.env` 解析兼容 `KEY=value` 与空格分隔两种形态（config.py 容错）。

## 依赖安装

本仓库用 **venv + pip**（构建机上无 uv；如装了 uv 可 `uv sync` 等价替换）：

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e .      # Linux/macOS: .venv/bin/python
```

## 快速开始（一键全链路）

```bash
.venv/Scripts/python scripts/seed.py          # 幂等：1 方向 + 5 RSS 源 + 3 网页监测页 + 2 搜索关键词 + 1 作者
.venv/Scripts/python scripts/run_demo.py      # 抓取 → 初筛 → 打分 → 写作，全程真实调用
```

## 定时无人值守（能力①）

```bash
.venv/Scripts/python scripts/run_scheduler.py             # 前台常驻：fetch+score 每 15min、hot 每 60min
.venv/Scripts/python scripts/run_scheduler.py --once-fetch  # 只跑一轮（冒烟）
```

调度/执行分离：调度器只把轮次任务置 PENDING，执行走 worker 路径；防重叠（同 kind 上一轮未结束跳过）、连续失败 ≥3 次源退避（每 4 轮放行探测）、每源 interval_minutes 可配。任务状态全程经 pipeline_task 落库。

## API

```bash
.venv/Scripts/python -m uvicorn app.main:app --port 8300
# 本机无鉴权，Swagger: http://127.0.0.1:8300/docs
```

| 端点 | 说明 |
|------|------|
| `POST /pipeline/run` | 跑一轮 抓取→初筛→打分（幂等） |
| `POST /pipeline/write/{author_id}` | 触发某作者写作 |
| `POST /scheduler/run-once/{fetch\|hot}` | 手动触发某轮次（与调度器同路径） |
| `GET /scheduler/status` | 调度器状态 + 最近轮次 |
| `GET /items` | 条目与打分（含 sanitize 状态） |
| `GET /hot/batches?limit=` | 热榜批次 + 关键词提炼（时间序列） |
| `GET /stats/filters?days=` | 被过滤统计（rule/sanitize × 原因 × 占比） |
| `GET /stats/search?days=` | 搜索调用统计（provider×日：次数/成功/失败/限额拦截/延迟） |
| `GET /stats/rank?days=` | 排序调用统计 |
| `GET /articles` · `GET /articles/{id}` · `GET /write-runs/{id}` | 文章 / 写作运行（含 prompt 快照与排序明细 payload） |
| `GET /authors/{id}/memory` · `POST /feedback` | 记忆与反馈回流 |
| `GET /usage/summary` · `GET /tasks?kind=` | 成本归因 / 任务队列 |

## 能力速览

| 能力 | 入口 | 说明 |
|---|---|---|
| ① 定时调度 | `app/scheduler.py` + `scripts/run_scheduler.py` | APScheduler；调度只入队，执行走 DB-as-queue worker |
| ② 网页监测 | `app/ingest/web.py`（source type=web） | etag/内容 sha256 变更检测；版本 guid 全量保存；列表页可选 LLM 抽取（call_point=web_extract） |
| ③ 热榜聚合 | `app/hot/service.py` | newsnow 类聚合 API 多平台全量落 hot_topic → deepseek 提炼 hot_batch（call_point=hot_keywords）；作者 include_hot_brief 注入风向段（不可引用） |
| ④ 搜索底座 | `app/search/`（base/bocha/tencent/registry/quota/pipeline） | "新增子类 + 注册一行"扩展；额度闸（SKIPPED_QUOTA 语义，search_call_log/search_quota 全记） |
| ⑤ 排序底座 | `app/rerank/`（bocha_reranker/bocha_jev/moark_jev/llm） | score 归一化 0-100 + band 三档；阅读集预排序（author.rank_provider/rank_exclude_below，明细落 write_run.payload）；热点候选筛选（HOT_RANK_FILTER，默认关） |
| 0 信任预留位 | `app/ingest/sanitize.py` | 落库前强制流经；SANITIZE_ENABLED 默认 false（pass-through）；REJECTED 全文照存；/stats/filters 统计 |

## 快照：导出与回灌

```bash
.venv/Scripts/python scripts/export_snapshot.py    # 13 张表全量（含被拒全文、调用日志）
.venv/Scripts/python scripts/reload_snapshot.py data/snapshot/<时间戳>
```

## 验证脚本

```bash
.venv/Scripts/python scripts/test_search_providers.py   # V10①②：双家连通+归一化比对
.venv/Scripts/python scripts/run_v11_ranking.py         # V11：排序一致性/排除效果/成本
.venv/Scripts/python -m pytest tests/ -q                # 43 passed
```

## 已知边界

- CISA 源 403（源侧反爬）如实标 FAILED；JS 渲染页无 Playwright（记遗留）。
- bocha_reranker 与"长方向提示词作 query"语义不匹配（V11 实测），需方向专用短查询字段。
- Bocha Jev 限时免费（免费期结束成本风险已标注）；搜索限额默认值为假设档（env 可覆盖）。
- 重复选题治理、Jev 复用连接等待办见验证报告"遗留问题"。
