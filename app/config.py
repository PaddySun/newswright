"""配置读取：Key 与模型名等来自仓库根目录的 .env（可用 NEWSWRIGHT_ENV_FILE 覆盖），缺失即报错。

.env 解析：先用 python-dotenv；对 dotenv 解析不了的行（如本项目 .env 中腾讯
Key 用空格分隔而非 `=`），用容错解析补齐——按首个 `=`/`:`/空白切分，只补不覆盖。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(os.environ.get("NEWSWRIGHT_ENV_FILE", str(PROJECT_ROOT / ".env")))

load_dotenv(ENV_FILE)


def _tolerant_env_parse(path: Path) -> dict[str, str]:
    """容错解析 .env：兼容 KEY=value 与「KEY value」（空格分隔）两种形态。"""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"\s*[=:]\s*|\s+", line, maxsplit=1)
        if len(parts) == 2 and parts[0] and parts[1]:
            out.setdefault(parts[0], parts[1].strip())
    return out


for _k, _v in _tolerant_env_parse(ENV_FILE).items():
    os.environ.setdefault(_k, _v)


def _get(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v is not None and v.strip():
            return v.strip()
    return None


def _require(*names: str) -> str:
    v = _get(*names)
    if v is None:
        sys.stderr.write(
            f"[config] 缺少必需的环境变量 {names[0]}（应位于 {ENV_FILE}），拒绝启动。\n"
        )
        raise SystemExit(1)
    return v


def _get_bool(name: str, default: bool) -> bool:
    v = _get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


DEEPSEEK_API_KEY = _require("DeepSeekAPIKey", "DEEPSEEK_API_KEY")
MOARK_API_KEY = _require("MoarkAPIKey", "MOARK_API_KEY")

DEEPSEEK_BASE_URL = _get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
# 官方模型 ID（2026-10 文档）：deepseek-flash | deepseek-v4-pro；旧名 deepseek-chat 为
# 兼容别名（响应实报 flash）。默认值改为官方名，.env 旧值仍可覆盖。
DEEPSEEK_MODEL = _get("DEEPSEEK_MODEL") or "deepseek-flash"
# 写作管线 think 路由（官方口径）：思考由 thinking/reasoning_effort 参数控制而非模型名；
# DEEPSEEK_THINKING_MODEL 仅在想换高档模型（如 deepseek-v4-pro）时覆盖，默认随主模型。
DEEPSEEK_THINKING_MODEL = _get("DEEPSEEK_THINKING_MODEL") or DEEPSEEK_MODEL
DEEPSEEK_REASONING_EFFORT = _get("DEEPSEEK_REASONING_EFFORT") or "high"
# 档位路由模式：thinking_params=官方参数路由（默认）；model_name=旧模型名档位
# （仅非官方网关不认 thinking 参数且必须换模型名时使用——此时设 DEEPSEEK_REASONER_MODEL）
DEEPSEEK_TIER_MODE = _get("DEEPSEEK_TIER_MODE") or "thinking_params"
DEEPSEEK_REASONER_MODEL = _get("DEEPSEEK_REASONER_MODEL") or "deepseek-reasoner"
MOARK_BASE_URL = _get("MOARK_BASE_URL") or "https://api.moark.com"
MOARK_JEV_MODEL = _get("MOARK_JEV_MODEL") or "APUS-OpenJev-v1-9B"
# NeoHorse-Jev-4B（EV7 实测新配置；不改变 MOARK_JEV_MODEL 默认行为）
MOARK_JEV_MODEL_NEOHORSE = _get("MOARK_JEV_MODEL_NEOHORSE") or "NeoHorse-Jev-4B"
# moark embedding（能力⑥，检索层接线见 app/retrieval/）：默认模型与单请求批量上限。
# 嵌入禁用语义：环境变量显式置空或 none → 检索层整体回退全量慢速（嵌入不可用路径），
# 未设置则用默认模型。显式空串与未设置必须区分，故不走 _get 的空值归一。
_MOARK_EMBED_MODEL_ENV = os.environ.get("MOARK_EMBED_MODEL")
if _MOARK_EMBED_MODEL_ENV is not None and not _MOARK_EMBED_MODEL_ENV.strip():
    MOARK_EMBED_MODEL = "none"
else:
    MOARK_EMBED_MODEL = _get("MOARK_EMBED_MODEL") or "Qwen3-Embedding-0.6B"
EMBED_BATCH_SIZE = int(_get("EMBED_BATCH_SIZE") or 32)
# 嵌入输入正文截断（标题恒保留）；嵌入向量期望维度（模型选型实测口径）
EMBED_TRUNCATE_CHARS = int(_get("EMBED_TRUNCATE_CHARS") or 2000)
EMBED_DIMENSIONS = int(_get("EMBED_DIMENSIONS") or 1024)
# moark rerank（/v1/rerank，注册不接线）：默认模型
MOARK_RERANK_MODEL = _get("MOARK_RERANK_MODEL") or "Qwen3-Reranker-0.6B"
# moark chat（OpenAI 兼容族备源，/v1/chat/completions）：默认模型=冒烟锁定的
# 跨厂商同族主备对（官方 deepseek-flash ↔ moark deepseek-v4.1-flash）
MOARK_CHAT_MODEL = _get("MOARK_CHAT_MODEL") or "deepseek-v4.1-flash"

# LLM 选源层（治理批 W2）：提供方名归口。默认单候选 deepseek、冷却不启用——
# 默认配置行为零变；候选位与 TTL 冷却是结构就位（跨厂商自动主备切换属后续决策）。
LLM_PROVIDER = _get("LLM_PROVIDER") or "deepseek"
# 有序候选列表（逗号分隔，缺省回落 [LLM_PROVIDER] 单候选形态）
LLM_CANDIDATES = [s.strip() for s in (_get("LLM_CANDIDATES") or "").split(",") if s.strip()]
# 候选失败冷却 TTL 秒数；0=不启用（默认——低流量系统不做自动熔断）
LLM_PROVIDER_COOLDOWN_SECONDS = float(_get("LLM_PROVIDER_COOLDOWN_SECONDS") or 0)

# 嵌入提供方名（选源接线）：默认 moark 行为零变；none/显式空串=禁用哨兵
# （检索层整体回退全量慢速，与 MOARK_EMBED_MODEL 的禁用语义同轨）。
_EMBED_PROVIDER_ENV = os.environ.get("EMBED_PROVIDER")
if _EMBED_PROVIDER_ENV is not None and not _EMBED_PROVIDER_ENV.strip():
    EMBED_PROVIDER = "none"
else:
    EMBED_PROVIDER = _get("EMBED_PROVIDER") or "moark"


# 热点榜单筛选三 env 归口（治理批 W2，读取面等价——调用时读取保持原
# os.environ.get 的读取时机语义，运行时注入立即生效）
def hot_rank_filter_enabled() -> bool:
    """榜单筛选开关（默认关）。"""
    return os.environ.get("HOT_RANK_FILTER", "").lower() in ("1", "true", "yes", "on")


def hot_rank_provider_name() -> str:
    """榜单筛选用的排序提供方名。"""
    return os.environ.get("HOT_RANK_PROVIDER") or "bocha_jev"


def hot_rank_min_score() -> int:
    """榜单筛选的最低保留分（0-100）。"""
    return int(os.environ.get("HOT_RANK_MIN_SCORE") or 40)

# 搜索/排序底座 Key（可选：缺失时对应通道降级关闭，不阻塞启动）
BOCHA_API_KEY = _get("bochaaiAPIKey", "BOCHAAI_API_KEY", "BOCHA_API_KEY")
TENCENT_SECRET_ID = _get("tencentSecretId", "TENCENTCLOUD_SECRET_ID", "TENCENT_SECRET_ID")
TENCENT_SECRET_KEY = _get("tencentSecretKey", "TENCENTCLOUD_SECRET_KEY", "TENCENT_SECRET_KEY")
TENCENT_WSA_HOST = _get("TENCENT_WSA_HOST") or "wsa.tencentcloudapi.com"
TENCENT_WSA_ACTION = _get("TENCENT_WSA_ACTION") or "SearchPro"
TENCENT_WSA_VERSION = _get("TENCENT_WSA_VERSION") or "2025-05-08"

DATABASE_URL = _get("NEWSWRIGHT_DB") or f"sqlite:///{(PROJECT_ROOT / 'newswright.db').as_posix()}"

# D18 凭据纪律（AC-01.1）：初始管理员密码必填、无默认值，缺失即拒绝启动；
# 只进 .env（gitignored），不进 git/文档/日志；首登强制改密。
NEWSWRIGHT_ADMIN_PASSWORD = _require("NEWSWRIGHT_ADMIN_PASSWORD")

# 管线可调参数（Demo 固定默认，可被环境变量覆盖）
SCORE_BODY_MAX_CHARS = int(_get("SCORE_BODY_MAX_CHARS") or 4000)
WRITE_READING_SET_K = int(_get("WRITE_READING_SET_K") or 10)
RULE_MIN_BODY_CHARS = int(_get("RULE_MIN_BODY_CHARS") or 200)
RULE_MAX_AGE_DAYS = int(_get("RULE_MAX_AGE_DAYS") or 30)
# 打分轮突发上限：单轮对单一方向至多打分的条目数；超出部分留给下一轮幂等续跑
# （打分幂等口径：只对尚无 OK 分的条目调 LLM），防积压场景单轮烧穿预算
SCORE_ROUND_MAX_ITEMS = int(_get("SCORE_ROUND_MAX_ITEMS") or 200)

# 调度（能力①）：默认周期，可被环境变量覆盖
SCHED_FETCH_MINUTES = int(_get("SCHED_FETCH_MINUTES") or 15)
SCHED_HOT_MINUTES = int(_get("SCHED_HOT_MINUTES") or 60)
# 独立打分节奏（显式配置键）：score 定时 job 的触发间隔；与 fetch 完成后的
# 联锁触发并存（双形态：新内容低延迟打分 + 无新内容时定时兜底）
SCHED_SCORE_MINUTES = int(_get("SCHED_SCORE_MINUTES") or 15)
# 源连续失败退避：连续 FAILED ≥3 次跳过该源，此后每 4 轮放行一次探测
BACKOFF_FAIL_THRESHOLD = int(_get("BACKOFF_FAIL_THRESHOLD") or 3)
BACKOFF_PROBE_EVERY = int(_get("BACKOFF_PROBE_EVERY") or 4)

# 失效三级判别与动态降频（采集加固）：阈值与缺省间隔档
# 连续 ≥3 轮 404/403/410 → 硬失效；连续 ≥3 轮 200 空内容 → 疑似失效
HARD_FAIL_ROUNDS = int(_get("HARD_FAIL_ROUNDS") or 3)
SUSPECT_EMPTY_ROUNDS = int(_get("SUSPECT_EMPTY_ROUNDS") or 3)
# 死刑源周探活（BE-3/D6）：进入 hard_failed 满 N 天起每轮至多 M 个探活
# （最老优先，防探活排满）；探活尝试后同样冷却 N 天
HARD_FAIL_PROBE_EVERY_DAYS = int(_get("HARD_FAIL_PROBE_EVERY_DAYS") or 7)
HARD_FAIL_PROBE_QUOTA = int(_get("HARD_FAIL_PROBE_QUOTA") or 5)
# 搜索源关键词连续 ≥6 轮零新增 → 边际降频（与 429 降频同构但独立计数）
KEYWORD_EXHAUSTED_ROUNDS = int(_get("KEYWORD_EXHAUSTED_ROUNDS") or 6)
# 降频缺省间隔档：15×2^档位 分钟，上限 240（429 限流与关键词零收益共用阶梯）
RATE_LIMIT_BASE_MINUTES = int(_get("RATE_LIMIT_BASE_MINUTES") or 15)
RATE_LIMIT_MAX_MINUTES = int(_get("RATE_LIMIT_MAX_MINUTES") or 240)
# RSS/web 内容零收益自适应（BE-6/R3.8，HG-3）：健康但连续 N 轮无新增 →
# interval 读时放大 ×2^档（档位封顶 M=×16）；not_modified/error/限流轮不计数。
# 与 suspect/hard_failed 失效阶梯（管失败）、D20（管搜索源关键词零收益）划界。
ZERO_GAIN_THRESHOLD_ROUNDS = int(_get("ZERO_GAIN_THRESHOLD_ROUNDS") or 6)
ZERO_GAIN_MAX_LEVEL = int(_get("ZERO_GAIN_MAX_LEVEL") or 4)

# 零信任过滤（能力预留位，本阶段只做骨架+统计）：默认关=pass-through
SANITIZE_ENABLED = _get_bool("SANITIZE_ENABLED", False)
# 启用时生效的关键词黑名单（逗号分隔；KeywordDenySanitizer 命中即拒）
SANITIZE_DENY_KEYWORDS = [
    kw.strip() for kw in (_get("SANITIZE_DENY_KEYWORDS") or "").split(",") if kw.strip()
]

# 热榜聚合（能力③，BettaFish MindSpider 前半段模式）：newsnow 类聚合 API
HOT_AGG_BASE = _get("HOT_AGG_BASE") or "https://newsnow.busiyi.world/api/s"
HOT_PLATFORMS = [
    p.strip() for p in (_get("HOT_PLATFORMS") or "weibo,zhihu,bilibili,toutiao,github").split(",")
    if p.strip()
]
# 进入关键词提炼的每平台条目上限（全量落库不受限；输入控制成本）
HOT_KEYWORD_INPUT_PER_PLATFORM = int(_get("HOT_KEYWORD_INPUT_PER_PLATFORM") or 20)
# 聚合器候选位（热榜治理批建、BE-6 启用收口）：逗号分隔有序列表，取用按序——
# 首候选失败（重试耗尽或不可重试）→ 下一候选，全败该平台记失败不中断整轮。
# 备源启用形态：.env 配 HOT_AGG_CANDIDATES="https://a.example/api/s,https://b.example/api/s"
# 即多候选按序取用（首候选 5xx/契约违例自动换次候选，落账 provider=胜者）；
# 缺省回落 [HOT_AGG_BASE] 单元素 = 行为零变。
# 设计依据见 docs/design-index.md「HR-2」「HG-2」。
HOT_AGG_CANDIDATES = [
    s.strip() for s in (_get("HOT_AGG_CANDIDATES") or "").split(",") if s.strip()
] or [HOT_AGG_BASE]
# hot 平台连败冷却（BE-6/R3.7，HotCallLog 回读）：最近 N 行全败且最新失败距
# now < M 分钟 → 冷却中（跳过 fetch_platform）。无历史不罚、一次成功断连败、
# 冷却期满自然重试。设计依据见 docs/design-index.md「HG-1」。
HOT_COOLDOWN_STREAK = int(_get("HOT_COOLDOWN_STREAK") or 3)
HOT_COOLDOWN_MINUTES = int(_get("HOT_COOLDOWN_MINUTES") or 30)

# 搜索额度（能力④B）：每分钟/每日上限，按 provider 配置。
# 默认值依据（Demo 假设档，可被环境变量覆盖）：博查按官方定价页充值档位保守估计
# （Web Search 未获实测配额文档，取保守值并如实标注）；腾讯 lite 版按控制台配额页
# 假设档。首次触发 429 时按响应调整。每轮 2 关键词 × 双家 ≪ 默认日上限。
SEARCH_QUOTA_DEFAULT_MINUTE = int(_get("SEARCH_QUOTA_DEFAULT_MINUTE") or 8)
SEARCH_QUOTA_DEFAULT_DAY = int(_get("SEARCH_QUOTA_DEFAULT_DAY") or 200)
# 每 provider 覆盖：SEARCH_QUOTA_<PROVIDER>_MINUTE / _DAY
SEARCH_RESULT_ITEMS_PER_KEYWORD = int(_get("SEARCH_RESULT_ITEMS_PER_KEYWORD") or 10)

# 相关性排序底座（能力⑤）：单次调用候选上限与候选文本截断（对应各家输入限制：
# Bocha reranker 约 512 tokens/文档、Jev 32K ctx/问题、LLM 批量 JSON 输出）
RANK_MAX_CANDIDATES = int(_get("RANK_MAX_CANDIDATES") or 30)
RANK_TEXT_MAX_CHARS = int(_get("RANK_TEXT_MAX_CHARS") or 500)
RANK_JEV_MAX_QUESTIONS = int(_get("RANK_JEV_MAX_QUESTIONS") or 32)
# Bocha Jev（jev.bocha.cn，systemone 协议同族，限时免费——免费期结束后成本风险记录在案）
BOCHA_JEV_BASE_URL = _get("BOCHA_JEV_BASE_URL") or "https://jev.bocha.cn"
BOCHA_JEV_MODEL = _get("BOCHA_JEV_MODEL") or "bocha-jev-v1"

# 出网 proxy 参数位（传输脊）：env HTTPX_PROXY 注入即启用，不配置行为不变。
# 读取归口在此（函数形态=调用时读取——运行时注入立即生效，不做 import 期快照）。
# 设计依据见 docs/design-index.md「TR-1」。
PROXY_ENV_KEY = "HTTPX_PROXY"


def httpx_proxy_url() -> str | None:
    """proxy 参数位的唯一读取点：未配置返回 None（不配置行为不变）。"""
    value = os.environ.get(PROXY_ENV_KEY, "").strip()
    return value or None
