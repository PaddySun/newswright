# newswright — 全链路最小 Demo（后端，含信息获取扩展）

[![ci](https://github.com/PaddySun/newswright/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/PaddySun/newswright/actions/workflows/ci.yml) [![codecov](https://codecov.io/gh/PaddySun/newswright/graph/badge.svg?token=MRILG7FTLV)](https://codecov.io/gh/PaddySun/newswright) [![mutation](https://github.com/PaddySun/newswright/actions/workflows/mutation.yml/badge.svg)](https://paddysun.github.io/newswright/)

RSS 抓取 / 定点网页监测 / 搜索关键词 → 去重 → 规则初筛 → 零信任过滤预留位 → LLM 方向打分（含评分理由）→ AI 作者写作（记忆占位符 + 引用硬校验 + 热点风向段）→ 文章/不写落库。另有：APScheduler 定时调度（无人值守）、热榜聚合、博查/腾讯双家搜索底座、四后端相关性排序底座。FastAPI + SQLAlchemy 2.0 + SQLite（ORM 写法保持 PG 可迁移）。

验证结论见项目文档（外层）的《全链路demo-验证报告-20260928.md》（V1-V6）与《信息获取扩展-验证报告-20260928.md》（V7-V11 + Z1，含实测数据）。

## 环境要求

- Python 3.11+（实测 3.13）
- 真实 `.env` 位于**仓库根目录**（`./.env`，可复制 `.env.example` 后填入；路径可用 `NEWSWRIGHT_ENV_FILE` 覆盖）：
  - 必需：`DeepSeekAPIKey`、`MoarkAPIKey`、`NEWSWRIGHT_ADMIN_PASSWORD`（初始管理员密码，D18 凭据纪律：必填无默认、缺失即拒绝启动、不进 git/文档；首登强制改密）
  - 搜索/排序（可选，缺失时对应通道降级关闭）：`bochaaiAPIKey`（博查三件套同一把 Key）、`tencentSecretId`/`tencentSecretKey`（腾讯 wsa，CAM 子账号凭据）
  - Key 任何情况下不进 git；`.env` 解析兼容 `KEY=value` 与空格分隔两种形态（config.py 容错）。

## 登录与会话（G1 起）

- API 全部需登录（除 `POST /api/auth/login`、`POST /api/auth/password`）；未携带/过期会话返回 401 `AUTH_REQUIRED`。
- 首登 `must_change_password=true`：改密前一切 API 返回 403 `PASSWORD_CHANGE_REQUIRED`，须先 `POST /api/auth/password` 完成改密。
- 登录限速：连续 5 次失败后第 6 次起 429 `AUTH_RATE_LIMITED`，冷却 15 分钟（成功登录清零；进程内计数，重启清零）。
- 会话保持期限默认 7 天（site_config `session_duration_days` 可调）。

```bash
# 登录（cookie jar 保存会话）
curl -c cookies.txt -X POST http://127.0.0.1:8300/api/auth/login \
  -H "Content-Type: application/json" -d '{"username":"admin","password":"<初始密码>"}'
# 首登改密
curl -b cookies.txt -X POST http://127.0.0.1:8300/api/auth/password \
  -H "Content-Type: application/json" -d '{"old_password":"<初始密码>","new_password":"<新密码>"}'
# 之后全部 API 凭 cookie 访问
curl -b cookies.txt http://127.0.0.1:8300/items
```

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
# API 需登录（见"登录与会话"节）；Swagger: http://127.0.0.1:8300/docs
```

| 端点 | 说明 |
|------|------|
| `POST /api/auth/login` · `POST /api/auth/password` | 登录 / 改密（G1 新增，免守卫豁免） |
| `POST /pipeline/run` | 跑一轮 抓取→初筛→打分（幂等；需登录，下同） |
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
| `GET /stream/b?direction_id=` | 登录态 B 流（OV2 拍板④）：高分排序 + 可调概率穿插低分≥阈值条目，真实评分原样返回（band=low_interleaved 标记） |
| `GET /hot/board?direction_id=` | 热点面板数据契约（OV3 拍板②）：方向关键词 × 打分排序前 N 条搜索结果标题 |
| `GET /stats/overview?days=` | 统计总览（OV4）：Token 按作者×调用点、四类失败口径、阶段成功率 |

## 能力速览

| 能力 | 入口 | 说明 |
|---|---|---|
| ① 定时调度 | `app/scheduler.py` + `scripts/run_scheduler.py` | APScheduler；调度只入队，执行走 DB-as-queue worker |
| ② 网页监测 | `app/ingest/web.py`（source type=web） | etag/内容 sha256 变更检测；版本 guid 全量保存；列表页可选 LLM 抽取（call_point=web_extract） |
| ③ 热榜聚合 | `app/hot/service.py` | newsnow 类聚合 API 多平台全量落 hot_topic → deepseek 提炼 hot_batch（call_point=hot_keywords）；作者 include_hot_brief 注入风向段（不可引用） |
| ④ 搜索底座 | `app/search/`（base/bocha/tencent/registry/quota/pipeline） | "新增子类 + 注册一行"扩展；额度闸（SKIPPED_QUOTA 语义，search_call_log/search_quota 全记） |
| ⑤ 排序底座 | `app/rerank/`（bocha_reranker/bocha_jev/moark_jev/moark_reranker/llm） | score 归一化 0-100 + band 三档；阅读集预排序（author.rank_provider/rank_exclude_below，明细落 write_run.payload）；热点候选筛选（HOT_RANK_FILTER，默认关） |
| ⑥ 向量底座（注册不接线） | `app/embedding/`（base/moark/registry） | EmbeddingProvider 抽象 + moark /v1/embeddings 适配（dimensions 透传/expected_dims 护栏/分批重试）；计量 call_point=embed + item_count；选型实测见 M18-M20 |
| 0 信任预留位 | `app/ingest/sanitize.py` | 落库前强制流经；SANITIZE_ENABLED 默认 false（pass-through）；REJECTED 全文照存；/stats/filters 统计 |
| 写作管线（三阶段） | `app/authors/`（schema/gates/pipeline/importer） | author.json 全量配置驱动；四 draft 模式/修订遍/六门禁/gated·零修订重写/trace 落库；schema 见 `docs/author-json-schema.md` |
| 防蒙蔽穿插（OV2） | `app/api/routes.py::stream_b` | 拍板④：低分≥阈值条目按概率穿插，INTERLEAVE_* env 可调，诚实评分 |
| 热点面板数据（OV3） | `app/api/routes.py::hot_board` | 拍板②数据侧：关键词 × 打分排序前 N 标题 |
| 统计总览（OV4） | `app/api/routes.py::stats_overview` | 仪表盘数据底座：Token 归因 / 四类失败 / 阶段成功率 |
| 端到端串联（OV1） | `scripts/run_e2e.py` | 四通道→打分→写作→C 流一条龙 + 逐通道引用追溯报告（verify/e2e_report.md） |

## 可配置写作管线（第三阶段，M14-M17）

`author.json` 驱动的多阶段写作执行器：作者级 JSON = 全量身份与管线配置（**模型不在 JSON**，DB `Author.model` 绑定）。

```bash
.venv/Scripts/python scripts/import_authors.py config/authors/luxun.json --model deepseek-chat   # 导入（round-trip 校验）
.venv/Scripts/python scripts/run_write_once.py --author 鲁迅                               # 单篇写作
.venv/Scripts/python scripts/run_overnight.py                                             # 夜间批跑（幂等断点续跑）
.venv/Scripts/python scripts/export_writing.py --run 15                                   # 成稿/废稿导出 md
.venv/Scripts/python scripts/morning_report.py --batch ovnight_20260929                   # 夜跑晨报
.venv/Scripts/python scripts/extract_slices.py --top 16 --apply config/authors/tanya.json        # GBK 小说素材切片提取
```

- **管线**：outline（pyramid/variation/sectional/formula）+ draft 四模式（single/rolling/incubate/dictate）+ 修订遍（prune/rhythm；distort/callback/selfrev 占位）+ 六门禁（length/fingerprint/echo_check/citation/copyright/topic_dedup）+ 重写规则（gated_retry 附违规说明 / zero_revision 审计留痕）。
- **引用契约**：正文 markdown `[^K]` 脚注 + 定义行，执行器解析后逐字校验绑定 `article.citations`（item_id + quote）。
- **静态记忆块**：≤3 段 × ≤500 字硬预算注入（round_robin/recency/relevant + head/tail/u U 形放置），copyright n-gram 门禁防原著整段复制。
- **trace 落库**：全节点 trace（输入摘要/输出全文/门禁结果/token/耗时）落 `write_run.payload`——废稿即被拒中间稿，DB 可查。
- **think 路由**：逐节点 reasoner|chat 档位（provider 层按调用传档），JSON 节点恒 chat；档位不可用自动回退并留痕。
- Schema 文档：`docs/author-json-schema.md`；示例：`config/authors/luxun.json`、`config/authors/tanya.json`。

## 快照：导出与回灌

```bash
.venv/Scripts/python scripts/export_snapshot.py    # 13 张表全量（含被拒全文、调用日志）
.venv/Scripts/python scripts/reload_snapshot.py data/snapshot/<时间戳>
```

## 验证脚本

```bash
.venv/Scripts/python scripts/test_search_providers.py   # V10①②：双家连通+归一化比对
.venv/Scripts/python scripts/run_v11_ranking.py         # V11：排序一致性/排除效果/成本
.venv/Scripts/python -m pytest tests/ -q                # 85 passed
```

## 向量与排序选型实测（M18-M20，2026-10-01）

moark 免费档 embedding/reranker/Jev 模型选型实测：数据底座 = morningdeck 运行导出
（6615 条）+ newswright 中文补齐（6812 条语料）。**适配器已落仓、注册不接线**（接线属
正式版决策）。详见项目文档（外层）《向量与排序实测-验证报告-20261001.md》。

- **Embedding 推荐**：主 Qwen3-Embedding-0.6B @1024（20.5ms/条、R@5 最高、1000 条/批、
  MRL 可砍 512 近无损）；质量优先 jina-embeddings-v4（跨语言 R@5 0.978、近重复 AUC 0.919，
  但 427ms/条且免费档 usage 报 0）；备 bge-m3（长文 R@5=1.0、8K 硬报错诚实）。
  Qwen3 家族越大越差（4B/8B sep_auc 反降）。
- **截断口径**：正文 2000 字符（512 已可用，全文直吃 R@1 增益 ≤8pp 且 bge >8192 tok 硬 400）。
- **Rerank**：Qwen3-Reranker-8B/4B **直吃长方向提示词**（ρ≈0.45-0.49 vs 打分），
  短查询全面负相关——V11 bocha_reranker 短查询问题被结构性解决（Qwen3 系特有能力，
  bge-reranker-v2-m3 长短皆负）；band 阈值（0.75/0.20）与 rubric 分带不对齐，只用排序；
  documents ≤25 条/请求。
- **NeoHorse-Jev-4B**：不推荐替代 APUS-9B（安全判定疑似全 REJECT 退化 0.583 vs 0.792、
  分段 0.500 vs 0.667、排序全面弱）；免费（billing_units=0）是唯一优势；
  **16 问/请求为平台级硬限制**（422 `Expected 1..16` 实锤，NeoHorse/APUS 同限）。
- 服务端限制实测：embeddings input ≤1000 条（0.6B）/100 条（4B）；大批按 token 静默
  拆批重编号 index（数量护栏必须开）；6812 条×1024 维仅 ~28MB、暴力检索 0.86ms
  ——万条级无需向量索引。

## 已知边界

- CISA 源 403（源侧反爬）如实标 FAILED；JS 渲染页无 Playwright（记遗留）。
- bocha_reranker 与"长方向提示词作 query"语义不匹配（V11 实测），需方向专用短查询字段。
- Bocha Jev 限时免费（免费期结束成本风险已标注）；搜索限额默认值为假设档（env 可覆盖）。
- 重复选题治理、Jev 复用连接等待办见验证报告"遗留问题"。
