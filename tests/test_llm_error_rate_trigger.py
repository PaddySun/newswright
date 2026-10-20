"""BE-7/PG 族三类触发器本体与 score 轮尾挂点测试。

覆盖（任务书 §五必含用例）：
- notify_provider_switched：category=provider_switched、dedupe=provider-{name}、
  body 含供应商名/状态码/TTL 分钟数/候选链次位去向；
- notify_balance_low：category=balance_low、dedupe=balance-{name}；
- check_llm_error_rate：≥10 样本+超阈触发 / 样本不足不触发 / 低于阈值不触发 /
  24h 去重（二次入队 deduped）；
- 挂点=score_round 尾（哨兵/磁盘同款 summary["llm_error_rate"] 记录）。

hub 判例必载：经触发器的测试 fixture 先 hub._reset_for_tests()（BE-2）。
"""
import pytest

from app.notify import hub
from app.notify.triggers import (
    check_llm_error_rate,
    notify_balance_low,
    notify_provider_switched,
)
from app.siteconfig import set_config
from app.transport.metering import record_usage


class FakeSMTP:
    fail = False
    calls: list[dict] = []

    def __init__(self, host, port, timeout=None):
        FakeSMTP.calls.append({"host": host, "port": port})
        if FakeSMTP.fail:
            raise ConnectionRefusedError("refused")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        pass

    def sendmail(self, from_addr, to_addrs, msg):
        FakeSMTP.calls[-1]["msg"] = msg


@pytest.fixture()
def smtp_ready(db_session, monkeypatch):
    """SMTP 配置+打桩+hub 进程态复位（BE-2 判例）。"""
    hub._reset_for_tests()
    FakeSMTP.calls = []
    monkeypatch.setattr("app.notify.smtp.smtplib.SMTP_SSL", FakeSMTP)
    set_config(db_session, "smtp_host", "smtp.example.com")
    set_config(db_session, "smtp_port", 465)
    set_config(db_session, "smtp_from", "bot@example.com")
    set_config(db_session, "smtp_to", ["me@example.com"])
    return FakeSMTP


def _seed_usage(db, *, total: int, errors: int) -> None:
    for i in range(total):
        record_usage(db, provider="moark", model="m", call_point="scoring",
                     ok=(i >= errors), error=None if i >= errors else "boom")


# ---------- 触发器本体 ----------


def test_notify_provider_switched_dispatch(smtp_ready, db_session):
    out = notify_provider_switched(db_session, name="moark", status=402,
                                   ttl_seconds=1800)
    assert out["queued"] is True
    msg = hub._queue[0]
    assert msg.category == "provider_switched"
    assert msg.dedupe_key == "provider-moark"
    assert "moark" in msg.subject
    # body 三要素：状态码 + TTL 分钟数 + 候选链次位去向（AC-2 钉死）
    assert "402" in msg.body and "30 分钟" in msg.body
    assert "候选链次位" in msg.body


def test_notify_balance_low_dispatch(smtp_ready, db_session):
    out = notify_balance_low(db_session, name="deepseek", amount=4.2, threshold=5)
    assert out["queued"] is True
    msg = hub._queue[0]
    assert msg.category == "balance_low"
    assert msg.dedupe_key == "balance-deepseek"
    assert "4.2" in msg.body


def test_error_rate_insufficient_samples_not_fired(db_session):
    """样本 <10（防小分母）不触发——即使错误率 100%。"""
    _seed_usage(db_session, total=9, errors=9)
    out = check_llm_error_rate(db_session)
    assert out["sent"] is False
    assert out["reason"] == "insufficient_samples"
    assert out["total"] == 9


def test_error_rate_below_threshold_not_fired(smtp_ready, db_session):
    """样本足额但错误率低于阈值（缺省 0.5）不触发。"""
    _seed_usage(db_session, total=20, errors=5)  # 0.25 < 0.5
    out = check_llm_error_rate(db_session)
    assert out["sent"] is False and out["reason"] == "below_threshold"
    assert out["error_rate"] == 0.25


def test_error_rate_high_fires_and_dedupes(smtp_ready, db_session):
    """样本 ≥10 且错误率 ≥0.5 → llm_error_rate_high 入队；24h 去重（二次
    入队 deduped）。"""
    _seed_usage(db_session, total=20, errors=12)  # 0.6 ≥ 0.5
    out = check_llm_error_rate(db_session)
    assert out["queued"] is True
    msg = hub._queue[0]
    assert msg.category == "llm_error_rate_high"
    assert msg.dedupe_key == "llm-error-rate"
    second = check_llm_error_rate(db_session)
    assert second["queued"] is False and second["reason"] == "deduped"


def test_error_rate_threshold_configurable(smtp_ready, db_session):
    """阈值可经 site_config llm_error_rate_warn 调低触发。"""
    set_config(db_session, "llm_error_rate_warn", 0.1)
    _seed_usage(db_session, total=10, errors=2)  # 0.2 ≥ 0.1
    out = check_llm_error_rate(db_session)
    assert out["queued"] is True


# ---------- 挂点：score_round 尾（哨兵/磁盘同款） ----------


def test_score_round_tail_records_error_rate(db_session):
    """score 轮尾顺带评估：summary["llm_error_rate"] 记录判定结果（样本不足
    路径——零调用即可验证挂点在位）。"""
    from app.pipeline.runner import score_round

    summary = score_round(db_session, triggered_by="test")
    assert summary["llm_error_rate"]["reason"] == "insufficient_samples"


def test_score_round_tail_fires_on_high_rate(smtp_ready, db_session):
    """高错误率下轮尾真触发（queued=True 入队）。"""
    from app.pipeline.runner import score_round

    _seed_usage(db_session, total=20, errors=15)
    summary = score_round(db_session, triggered_by="test")
    assert summary["llm_error_rate"]["queued"] is True
