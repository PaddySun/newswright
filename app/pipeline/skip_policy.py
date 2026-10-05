"""采集调度跳过判定与降频阶梯（纯逻辑，调度与统计展示共用）。

单一判定函数：一个源一轮可能同时命中多种跳过条件，payload.reason 按
「disabled > direction_expired > rate_limited > keyword_exhausted >
hard_failed/suspect_probe > backoff > interval_not_due」优先级取第一个命中。
设计依据见 docs/design-index.md「DT-6」「D13」「D20」「AC-05.5」「AC-04.6」。

skip_reason 返回约定：
- None：正常执行抓取；
- "probe"：处于退避/疑似失效状态但本轮是探测窗口——放行抓取，调用方需推进
  探测轮计数（backoff_skips），使探测节奏按每 N 轮一次维持；
- 其余值为跳过原因（入队侧记入轮次 payload；interval_not_due 在轮次记录中
  沿用 "interval_not_due:<分钟>m" 的既有展示格式）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import config
from ..models import Direction, Source


def _aware(dt: datetime) -> datetime:
    """SQLite 取回的 datetime 可能是 naive——统一按 UTC 处理。"""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def rate_limit_minutes(level: int) -> int:
    """降频缺省间隔档：基准间隔 × 2^档位，封顶上限（429 限流与关键词零收益共用阶梯）。"""
    level = max(int(level or 0), 0)
    return min(config.RATE_LIMIT_BASE_MINUTES * (2 ** level), config.RATE_LIMIT_MAX_MINUTES)


def probe_due(skips: int) -> bool:
    """探测窗口判定：backoff_skips 计入状态内每一轮（含探测轮），每 N 轮放行一次。"""
    return (skips or 0) % config.BACKOFF_PROBE_EVERY == 0


def skip_reason(src: Source, direction: Direction | None, *, now: datetime) -> str | None:
    """返回本源本轮的处置：None=执行，"probe"=执行探测，其余=跳过原因。

    只读源与方向的属性，不落库不改状态（入队侧负责计数推进与记录）。
    direction 传 None 时按"方向可采集"处理（手动路径无方向上下文）。
    """
    if not src.enabled:
        return "disabled"
    if direction is not None and direction.status == Direction.STATUS_EXPIRED:
        return "direction_expired"
    if src.rate_limited_until is not None and _aware(src.rate_limited_until) > now:
        return "rate_limited"
    if src.keyword_limited_until is not None and _aware(src.keyword_limited_until) > now:
        return "keyword_exhausted"
    if src.failure_level == "hard_failed":
        return "hard_failed"
    if src.failure_level == "suspect":
        return "probe" if probe_due(src.backoff_skips or 0) else "suspect_probe"
    if (src.backoff_failures or 0) >= config.BACKOFF_FAIL_THRESHOLD:
        return "probe" if probe_due(src.backoff_skips or 0) else "backoff"
    interval = (src.source_config or {}).get("interval_minutes")
    if interval and src.last_fetched_at:
        if (now - _aware(src.last_fetched_at)).total_seconds() < int(interval) * 60:
            return "interval_not_due"
    return None


def reset_keyword_backoff(db, *, direction_id: int | None = None) -> int:
    """关键词边际降频的恢复事件（hot_batch 关键词更新 / 站长手工刷新 /
    方向提示词升版）：清零搜索源的零收益计数与降频档。返回实际复位了状态的源数。"""
    q = db.query(Source).filter(Source.type == "search")
    if direction_id is not None:
        q = q.filter(Source.direction_id == direction_id)
    n = 0
    for src in q.all():
        if src.keyword_zero_rounds or src.keyword_rate_level or src.keyword_limited_until:
            n += 1
        src.keyword_zero_rounds = 0
        src.keyword_rate_level = 0
        src.keyword_limited_until = None
    db.commit()
    return n
