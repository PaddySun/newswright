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
