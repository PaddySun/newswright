"""搜索额度闸（能力④B，与 usage_log 同级纪律）。

限制语义：调用前查额度 → 超限本次调用不发出（返回 False，调用方记 SKIPPED_QUOTA），
下轮自然恢复；不抛异常不打断整轮。计数窗口：分钟（YYYY-MM-DDTHH:MM）与日（YYYY-MM-DD）。
"""
from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy.orm import Session

from .. import config
from ..models import SearchQuota


def _provider_limits(provider: str) -> tuple[int, int]:
    """每分钟/每日上限：SEARCH_QUOTA_<PROVIDER>_MINUTE/_DAY 环境变量优先（调用时读取），
    缺省用全局默认值。"""
    p = provider.upper()
    minute = os.environ.get(f"SEARCH_QUOTA_{p}_MINUTE")
    day = os.environ.get(f"SEARCH_QUOTA_{p}_DAY")
    return (
        int(minute) if minute else config.SEARCH_QUOTA_DEFAULT_MINUTE,
        int(day) if day else config.SEARCH_QUOTA_DEFAULT_DAY,
    )


def quota_state(db: Session, provider: str, *, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    minute, day = _provider_limits(provider)
    mkey = now.strftime("%Y-%m-%dT%H:%M")
    dkey = now.strftime("%Y-%m-%d")
    mcount = _count(db, provider, "minute", mkey)
    dcount = _count(db, provider, "day", dkey)
    return {
        "minute": {"limit": minute, "used": mcount},
        "day": {"limit": day, "used": dcount},
        "minute_key": mkey, "day_key": dkey,
    }


def _count(db: Session, provider: str, period: str, key: str) -> int:
    row = db.query(SearchQuota).filter_by(provider=provider, period=period, period_key=key).one_or_none()
    return row.count if row else 0


def check_and_count(db: Session, provider: str, *, now: datetime | None = None) -> tuple[bool, dict]:
    """检查额度并（放行时）预占一格。返回 (allowed, state)；state 为计数后口径。"""
    state = quota_state(db, provider, now=now)
    if state["minute"]["used"] >= state["minute"]["limit"] or state["day"]["used"] >= state["day"]["limit"]:
        return False, state
    now = now or datetime.now()
    for period, key in (("minute", state["minute_key"]), ("day", state["day_key"])):
        row = db.query(SearchQuota).filter_by(provider=provider, period=period, period_key=key).one_or_none()
        if row is None:
            db.add(SearchQuota(provider=provider, period=period, period_key=key, count=1))
        else:
            row.count += 1
    db.commit()
    return True, quota_state(db, provider, now=now)
