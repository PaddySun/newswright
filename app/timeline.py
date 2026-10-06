"""时区与日切辅助（site_config timezone 键的唯一解析点）。

时区决策（设计依据见 docs/design-index.md「D16」）：追踪日/自然日/预算日/
expires_at 零点全部取 site_config timezone（默认 Asia/Shanghai）。全部日切
消费点（预算日/通知自然日/TTL 零点/观测窗）统一经本模块解析——单一实现防
多处口径漂移；非法值回退 UTC 并落 WARN（配置错误不阻断服务，可从日志发现）。

滚动窗（如 24h 观测窗）口径注记：滚动窗无零点语义、时区不变式——不参与
日切；接线形态=消费点经 site_zone 取口径时保持滚动语义（当日窗会在本地零点
处出现小分母抖动，非观测本意）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

log = logging.getLogger("newswright.timeline")

_FALLBACK_ZONE = ZoneInfo("UTC")


def resolve_zone(name: str | None) -> ZoneInfo:
    """时区名 → ZoneInfo；空值/非法名回退 UTC 并 WARN。"""
    if not name:
        return _FALLBACK_ZONE
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        log.warning("site_config timezone 非法：%r，已回退 UTC", name)
        return _FALLBACK_ZONE


def site_zone(db: Session) -> ZoneInfo:
    """站点时区（site_config timezone 键；默认 Asia/Shanghai 见 siteconfig.DEFAULTS）。"""
    from .siteconfig import get_config

    return resolve_zone(get_config(db, "timezone"))


def local_day_start(zone: ZoneInfo, *, now_utc: datetime | None = None) -> datetime:
    """该时区"今日零点"对应的 UTC 时刻（预算日/自然日的统一日切起点）。

    例：Asia/Shanghai 且 UTC 10-06 16:30 → 上海已跨日为 10-07 00:30 →
    今日零点（上海 10-07 00:00）= UTC 10-06 16:00。返回 aware UTC datetime，
    可直接与库内 UTC 时间列比较。"""
    now_utc = _aware(now_utc or datetime.now(timezone.utc))
    local_midnight = now_utc.astimezone(zone).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc)


def local_day_start_after(zone: ZoneInfo, days: int,
                          *, now_utc: datetime | None = None) -> datetime:
    """自今日起第 days 天的该时区零点（临时方向 TTL 到期时刻：+7 天 = 第 7 日
    该时区零点）。"""
    now_utc = _aware(now_utc or datetime.now(timezone.utc))
    target_local = (now_utc.astimezone(zone) + timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return target_local.astimezone(timezone.utc)


def local_date_key(zone: ZoneInfo, *, now_utc: datetime | None = None) -> str:
    """该时区的当日日期键（YYYY-MM-DD）——按自然日取键的消费点（通知去重等）。"""
    now_utc = _aware(now_utc or datetime.now(timezone.utc))
    return now_utc.astimezone(zone).strftime("%Y-%m-%d")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
