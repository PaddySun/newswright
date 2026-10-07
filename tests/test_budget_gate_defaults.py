"""Token 预算闸缺省与边界测试：不设限语义、小额预算触发、恰等域与空域哨兵。

覆盖口径（AC-21.2 额度降级 + budget 模块口径，设计依据见
docs/design-index.md「AC-21.2」）：
- 预算未配置（默认 0）= 不设限：已消耗 token 也不触发降级；
- 预算 1 是合法配置（>0 即设限），恰等域 used==budget 触发（「已达预算」语义）；
- 打分慢速轮上限可配：配置值生效、未配置回退 20（继续低速不绝停的承载值）；
- 当日汇总空域哨兵 = 0（计量空域零值）。
"""
from datetime import datetime, timezone

from app.models import UsageLog
from app.pipeline.budget import budget_exceeded, score_slow_cap, tokens_used_today
from app.siteconfig import set_config


def _spend(db, tokens, *, call_point="scoring"):
    db.add(UsageLog(provider="stub", model="m", call_point=call_point,
                    prompt_tokens=tokens, ok=True,
                    created_at=datetime.now(timezone.utc)))
    db.commit()


def test_unconfigured_budget_never_triggers(db_session):
    """未配置预算（默认 0）= 不设限：已有消耗也不触发。"""
    _spend(db_session, 1000)
    assert budget_exceeded(db_session) is False


def test_budget_one_token_gates_at_equality(db_session):
    """预算 1 合法且恰等触发：used==budget 即已达预算（>= 语义）。"""
    set_config(db_session, "daily_token_budget", 1)
    _spend(db_session, 1)
    assert budget_exceeded(db_session) is True


def test_score_slow_cap_reads_config_and_defaults_20(db_session):
    """慢速上限配置消费：配置值生效；未配置回退 20。"""
    assert score_slow_cap(db_session) == 20
    set_config(db_session, "score_slow_round_max_items", 5)
    assert score_slow_cap(db_session) == 5


def test_tokens_used_today_empty_database_is_zero(db_session):
    """当日汇总空域哨兵 = 0。"""
    assert tokens_used_today(db_session) == 0
