"""配置读取：Key 与模型名等来自仓库上一级目录的 .env，缺失即报错。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(os.environ.get("NEWSWRIGHT_ENV_FILE", str(PROJECT_ROOT.parent / ".env")))

load_dotenv(ENV_FILE)


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


DEEPSEEK_API_KEY = _require("DeepSeekAPIKey", "DEEPSEEK_API_KEY")
MOARK_API_KEY = _require("MoarkAPIKey", "MOARK_API_KEY")

DEEPSEEK_BASE_URL = _get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
DEEPSEEK_MODEL = _get("DEEPSEEK_MODEL") or "deepseek-chat"
MOARK_BASE_URL = _get("MOARK_BASE_URL") or "https://api.moark.com"
MOARK_JEV_MODEL = _get("MOARK_JEV_MODEL") or "APUS-OpenJev-v1-9B"

DATABASE_URL = _get("NEWSWRIGHT_DB") or f"sqlite:///{(PROJECT_ROOT / 'newswright.db').as_posix()}"

# 管线可调参数（Demo 固定默认，可被环境变量覆盖）
SCORE_BODY_MAX_CHARS = int(_get("SCORE_BODY_MAX_CHARS") or 4000)
WRITE_READING_SET_K = int(_get("WRITE_READING_SET_K") or 10)
RULE_MIN_BODY_CHARS = int(_get("RULE_MIN_BODY_CHARS") or 200)
RULE_MAX_AGE_DAYS = int(_get("RULE_MAX_AGE_DAYS") or 30)
