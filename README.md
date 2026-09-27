# newswright — 全链路最小 Demo（后端）

RSS 抓取 → 去重 → 规则初筛 → LLM 方向打分（含评分理由）→ AI 作者写作（记忆占位符 + 引用硬校验）→ 文章/不写落库。FastAPI + SQLAlchemy 2.0 + SQLite（ORM 写法保持 PG 可迁移）。

验证结论见仓库外 `doc/草稿与过程文件/全链路demo-验证报告-20260928.md`（V1-V6 全部通过，含实测数据）。

## 环境要求

- Python 3.11+（实测 3.13）
- 真实 `.env` 位于**仓库上一级目录**（`../.env`），必含变量：`DeepSeekAPIKey`、`MoarkAPIKey`（变量名占位见 `.env.example`）。缺失即启动失败，Key 任何情况下不进 git。

## 依赖安装

本仓库用 **venv + pip**（构建机上无 uv；如装了 uv 可 `uv sync` 等价替换）：

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e .      # Linux/macOS: .venv/bin/python
```

## 快速开始（一键全链路）

```bash
.venv/Scripts/python scripts/seed.py          # 幂等：灌入 1 个演示方向 + 5 个固定 RSS 源 + 1 个演示作者
.venv/Scripts/python scripts/run_demo.py      # 抓取 → 初筛 → 打分 → 写作，全程真实调用
```

`run_demo` 会打印逐源统计（feed 条目数 / 入库 / 去重拦截 / 规则拒绝 / 失败），写作产物与不写卡全部落库。

## API 方式触发（FastAPI）

```bash
.venv/Scripts/python -m uvicorn app.main:app --port 8300
# 本机无鉴权，Swagger: http://127.0.0.1:8300/docs
```

| 端点 | 说明 |
|------|------|
| `POST /pipeline/run` | 跑一轮 抓取→初筛→打分（幂等：重跑不重复打分） |
| `POST /pipeline/write/{author_id}` | 触发某作者写作（阅读集→记忆→引用校验→文章/不写落库） |
| `GET /items?direction_id=&status=&limit=` | 条目与打分（含评分理由、提示词版本、模型） |
| `GET /articles` · `GET /articles/{id}` | 文章列表/详情（含 citations） |
| `GET /authors/{id}/memory` | 作者记忆条目（feedback/topic 模块） |
| `GET /write-runs/{id}` | 写作运行详情（含 prompt 全文快照） |
| `POST /feedback` | `{article_id, verdict: like\|dislike, comment?}` → 自动转写为作者记忆 |
| `GET /usage/summary` | 按 call_point/model 聚合 token 与次数（成本归因） |
| `GET /tasks?kind=` | pipeline_task 队列状态（DB 即队列） |

## 快照：导出与回灌（断网/换库可复跑实验）

```bash
.venv/Scripts/python scripts/export_snapshot.py    # 导出全量到 data/snapshot/<时间戳>/*.jsonl（已 gitignore，磁盘留存）
.venv/Scripts/python scripts/reload_snapshot.py data/snapshot/<时间戳>   # 回灌重建（跳过网络抓取）
```

回灌后无需重新抓取即可复跑打分与写作实验。

## V1 独立验证（moark Jev /v1/systemone 适配器）

```bash
.venv/Scripts/python scripts/test_jev_adapter.py   # 真实语料 13 条 KEEP/REJECT+band，输出 verify/V1_jev_adapter_results.json
```

## 测试

```bash
.venv/Scripts/python -m pytest tests/ -q    # 11 passed：建表/去重/规则/引用校验/占位符
```

## 目录导览

```
app/
├── config.py            # 读 ../.env（缺失即退出）+ 管线参数
├── db.py / models.py    # SQLAlchemy 2.0 全部表（10 张）
├── providers/           # base(计量/重试/usage_log) + deepseek + moark_jev(systemone)
├── ingest/              # rss 抓取去重 + rules 确定性初筛（零模型）
├── scoring/             # 方向打分：单次 LLM + strict JSON + 提示词版本绑定（prompts/score_v1.md）
├── authors/             # 写作：阅读集+记忆占位符+引用硬校验+skip；memory.py 占位符/反馈回流
├── pipeline/runner.py   # 编排：任务状态全经 pipeline_task 落库
└── api/routes.py        # 最小 API
scripts/                 # seed / run_demo / 快照导出回灌 / V1 与 V2、V5 验证脚本
verify/                  # V1/V2/V5 验证结果 JSON（入 git）
```

## 已知边界

- CISA 源 403（源侧反爬），管线如实标 FAILED；arXiv 周末无新条目属源正常状态。
- 单次 LLM 成本纪律优先：重复选题、Jev 复用连接等待办见验证报告"遗留问题"。
