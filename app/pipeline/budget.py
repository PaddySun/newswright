"""Token 日预算闸（轮次粒度拦截）：增值轮入口按当日用量汇总判定降级，不逐调用。

判定口径：usage_log 当日（UTC 日切）prompt+completion token 汇总 ≥ site_config
daily_token_budget（默认 0 = 不设限）即视为预算触发。触发后按"低优先级先停"
四档秩序降级：探索层暂停 → 嵌入暂停（路由自动回退全量慢速）→ 打分转慢速
（轮上限降为 score_slow_round_max_items，继续低速不绝停）→ 写作需站长确认。
采集与呈现永不参与降级。
设计依据见 docs/design-index.md「AC-21.2」。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import UsageLog
from ..siteconfig import get_config


def tokens_used_today(db: Session) -> int:
    """当日（UTC 日切起点起算）全部外部调用的 token 消耗汇总。"""
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                   microsecond=0)
    used = (
        db.query(func.sum(func.coalesce(UsageLog.prompt_tokens, 0)
                          + func.coalesce(UsageLog.completion_tokens, 0)))
        .filter(UsageLog.created_at >= day_start)
        .scalar()
    )
    return int(used or 0)


def budget_exceeded(db: Session) -> bool:
    """预算闸判定：预算 > 0 且当日汇总已达预算。预算为 0 = 不设限（永 False）。"""
    budget = int(get_config(db, "daily_token_budget") or 0)
    if budget <= 0:
        return False
    return tokens_used_today(db) >= budget


def score_slow_cap(db: Session) -> int:
    """预算触发后的打分慢速轮上限（继续低速不绝停）。"""
    return int(get_config(db, "score_slow_round_max_items") or 20)
