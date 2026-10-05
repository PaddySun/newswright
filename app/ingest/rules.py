"""确定性规则初筛（代码，零模型）。

口径（任务书 §5.2）：
- 正文长度 < 阈值（默认 200 字符，按字符数统一口径，不分语言）→ 拒；
- 黑名单关键词（可配，默认空）命中标题或正文 → 拒；
- 发布时间距今 > N 天（默认 30）→ 拒；缺发布时间不拒（记 null，不算过期）。
- 日志/中文/英文混排不做语言过滤。
日期过期必须在代码层做（JEV 实证：模型做日期减法全盲）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .. import config


@dataclass
class RuleResult:
    passed: bool
    reason: str | None = None


def apply_rules(
    *,
    title: str,
    content_text: str,
    published_at: datetime | None,
    min_chars: int | None = None,
    max_age_days: int | None = None,
    blacklist: list[str] | None = None,
    now: datetime | None = None,
    ignore_expiry: bool = False,
) -> RuleResult:
    """确定性规则初筛。

    ignore_expiry=True：跳过发布时间过期判定（首导轮的日期上限由打分窗口接替，
    过期规则对新源首导不生效）；长度与黑名单两类垃圾规则照常生效。
    """
    min_chars = config.RULE_MIN_BODY_CHARS if min_chars is None else min_chars
    max_age_days = config.RULE_MAX_AGE_DAYS if max_age_days is None else max_age_days
    blacklist = blacklist or []
    now = now or datetime.now(timezone.utc)

    if len(content_text.strip()) < min_chars:
        return RuleResult(False, f"too_short:{len(content_text.strip())}<{min_chars}")

    joined = f"{title}\n{content_text}"
    for kw in blacklist:
        if kw and kw in joined:
            return RuleResult(False, f"blacklist:{kw}")

    if published_at is not None and not ignore_expiry:
        pub = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
        age_days = (now - pub).total_seconds() / 86400
        if age_days > max_age_days:
            return RuleResult(False, f"expired:{age_days:.0f}d>{max_age_days}d")

    return RuleResult(True)
