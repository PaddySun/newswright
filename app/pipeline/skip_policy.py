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

from datetime import datetime, timedelta, timezone

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


def hard_failed_probe_due(src: Source, *, now: datetime) -> bool:
    """死刑源探活窗口（BE-3/D6）：进入 hard_failed 满 HARD_FAIL_PROBE_EVERY_DAYS
    天，且最近一次探活尝试（last_probe_at，成败都记账）也已冷却同期——两钟
    皆满才 due。failure_since 语义是「进入当前失效态的时间」，不得挪作探活
    时钟；缺 failure_since 的历史行保守不探。纯函数不知配额（配额放行在
    enqueue 层），skip_reason 的 hard_failed 分支不因此改变。"""
    if src.failure_level != "hard_failed" or src.failure_since is None:
        return False
    window = timedelta(days=config.HARD_FAIL_PROBE_EVERY_DAYS)
    if now - _aware(src.failure_since) < window:
        return False
    if src.last_probe_at is not None and now - _aware(src.last_probe_at) < window:
        return False
    return True


def is_stale_dead(src: Source, *, now: datetime, stale_days: int) -> bool:
    """陈旧死源判定（BE-3/D6）：hard_failed 且进入失效态超 stale_days 天——
    聚合哨兵与体检载荷的降级分子出清判据（只影响呈现口径，不改源状态本体
    与 enabled 分母）。suspect 与缺 failure_since 的历史行永不出清。"""
    if src.failure_level != "hard_failed" or src.failure_since is None:
        return False
    return (now - _aware(src.failure_since)) > timedelta(days=stale_days)


def effective_interval_minutes(base_minutes: int, zero_gain_level: int) -> int:
    """RSS/web 零收益读时放大（BE-6/R3.8，HG-3）：base × 2^zero_gain_level，
    档位封顶 ZERO_GAIN_MAX_LEVEL（缺省 4=×16）。纯读取计算——不改
    source_config 用户值（呈现面用同函数保持口径一致）。"""
    level = min(max(int(zero_gain_level or 0), 0), config.ZERO_GAIN_MAX_LEVEL)
    return int(base_minutes) * (2 ** level)


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
        # 零收益读时放大（HG-3）：effective = interval × 2^zero_gain_level——
        # 用户配置值不动，仅判定时放大；无 interval 配置的源本就不进此分支
        effective = effective_interval_minutes(interval, src.zero_gain_level or 0)
        if (now - _aware(src.last_fetched_at)).total_seconds() < effective * 60:
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
