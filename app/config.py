"""配置读取：Key 与模型名等来自仓库上一级目录的 .env，缺失即报错。

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
ENV_FILE = Path(os.environ.get("NEWSWRIGHT_ENV_FILE", str(PROJECT_ROOT.parent / ".env")))

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
DEEPSEEK_MODEL = _get("DEEPSEEK_MODEL") or "deepseek-chat"
MOARK_BASE_URL = _get("MOARK_BASE_URL") or "https://api.moark.com"
MOARK_JEV_MODEL = _get("MOARK_JEV_MODEL") or "APUS-OpenJev-v1-9B"

# 搜索/排序底座 Key（可选：缺失时对应通道降级关闭，不阻塞启动）
BOCHA_API_KEY = _get("bochaaiAPIKey", "BOCHAAI_API_KEY", "BOCHA_API_KEY")
TENCENT_SECRET_ID = _get("tencentSecretId", "TENCENTCLOUD_SECRET_ID", "TENCENT_SECRET_ID")
TENCENT_SECRET_KEY = _get("tencentSecretKey", "TENCENTCLOUD_SECRET_KEY", "TENCENT_SECRET_KEY")
TENCENT_WSA_HOST = _get("TENCENT_WSA_HOST") or "wsa.tencentcloudapi.com"
TENCENT_WSA_ACTION = _get("TENCENT_WSA_ACTION") or "SearchPro"
TENCENT_WSA_VERSION = _get("TENCENT_WSA_VERSION") or "2025-05-08"

DATABASE_URL = _get("NEWSWRIGHT_DB") or f"sqlite:///{(PROJECT_ROOT / 'newswright.db').as_posix()}"

# 管线可调参数（Demo 固定默认，可被环境变量覆盖）
SCORE_BODY_MAX_CHARS = int(_get("SCORE_BODY_MAX_CHARS") or 4000)
WRITE_READING_SET_K = int(_get("WRITE_READING_SET_K") or 10)
RULE_MIN_BODY_CHARS = int(_get("RULE_MIN_BODY_CHARS") or 200)
RULE_MAX_AGE_DAYS = int(_get("RULE_MAX_AGE_DAYS") or 30)

# 调度（能力①）：默认周期，可被环境变量覆盖
SCHED_FETCH_MINUTES = int(_get("SCHED_FETCH_MINUTES") or 15)
SCHED_HOT_MINUTES = int(_get("SCHED_HOT_MINUTES") or 60)
# 源连续失败退避：连续 FAILED ≥3 次跳过该源，此后每 4 轮放行一次探测
BACKOFF_FAIL_THRESHOLD = int(_get("BACKOFF_FAIL_THRESHOLD") or 3)
BACKOFF_PROBE_EVERY = int(_get("BACKOFF_PROBE_EVERY") or 4)

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
