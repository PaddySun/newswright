"""通知触发守卫语义测试：四类触发的站点开关（关闭=零投递）、去重键形态
（notify_last_sent_<category>_<key>，预算键带站点时区自然日）、聚合哨兵的
降级判定口径（suspect/hard_failed/降频）与轮次计数持久化/恢复清零、通知标题
承载「采集面整体降级」、磁盘用量百分比计量与严格大于阈值判定。

设计依据见 docs/design-index.md「AC-19.2」「AC-19.3」「AC-19.4」「ADR-10」。
"""
import logging
import types
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email import message_from_string

import pytest

from app.models import Direction, Source
from app.pipeline.runner import _update_source_health
from app.siteconfig import get_config, set_config


class FakeSMTP:
    fail = False
    calls: list[dict] = []

    def __init__(self, host, port, timeout=None):
        FakeSMTP.calls.append({"host": host, "port": port})
        if FakeSMTP.fail:
            raise ConnectionRefusedError("[Errno 111] Connection refused")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        pass

    def sendmail(self, from_addr, to_addrs, msg):
        FakeSMTP.calls[-1]["msg"] = msg


@pytest.fixture()
def smtp_monkeypatched(monkeypatch):
    FakeSMTP.calls = []
    FakeSMTP.fail = False
    monkeypatch.setattr("app.notify.smtp.smtplib.SMTP_SSL", FakeSMTP)
    return FakeSMTP


@pytest.fixture()
def smtp_configured(db_session):
    set_config(db_session, "smtp_host", "smtp.example.com")
    set_config(db_session, "smtp_port", 465)
    set_config(db_session, "smtp_from", "bot@example.com")
    set_config(db_session, "smtp_to", ["me@example.com"])


def _error_stats(http_status=None, error="HTTP 404"):
    extra = {"http_status": http_status} if http_status else {}
    return types.SimpleNamespace(error=error, feed_entries=0, inserted=0,
                                 not_modified=False, rate_limited=False,
                                 retry_after=None, extra=extra)


def _seed_direction_with_sources(db, name, count, **source_kwargs):
    d = Direction(name=name, prompt="p", threshold=60)
    db.add(d)
    db.commit()
    for i in range(count):
        db.add(Source(direction_id=d.id, url=f"https://{name}-{i}.example/rss",
                      **source_kwargs))
    db.commit()
    return d


# ---------- 触发开关：关闭 = 零投递（事件仅落日志） ----------


def test_source_failure_switch_off_suppresses_delivery(db_session,
                                                       smtp_monkeypatched,
                                                       smtp_configured):
    set_config(db_session, "notify_on_source_failure", False)
    _seed_direction_with_sources(db_session, "开关方向", 1)
    src = db_session.query(Source).one()
    src.hard_failures = 2
    db_session.commit()
    _update_source_health(db_session, src, _error_stats(404))
    assert src.failure_level == "hard_failed"
    assert FakeSMTP.calls == []


def test_budget_switch_off_suppresses_delivery(db_session,
                                               smtp_monkeypatched,
                                               smtp_configured):
    from app.notify.triggers import notify_budget_exceeded

    set_config(db_session, "notify_on_token_budget", False)
    out = notify_budget_exceeded(db_session, used_tokens=600, budget=500)
    assert out["sent"] is False
    assert FakeSMTP.calls == []


def test_collective_switch_off_suppresses_delivery(db_session,
                                                   smtp_monkeypatched,
                                                   smtp_configured):
    from app.notify.triggers import check_collective_sentinel

    set_config(db_session, "notify_on_collective", False)
    _seed_direction_with_sources(db_session, "哨兵开关", 3,
                                 enabled=True, failure_level="suspect")
    check_collective_sentinel(db_session)
    check_collective_sentinel(db_session)  # 持续第 2 轮：开关关仍零投递
    assert FakeSMTP.calls == []


def test_disk_switch_off_suppresses_delivery(db_session, smtp_monkeypatched,
                                             smtp_configured, monkeypatch):
    from app.notify.triggers import check_disk_usage

    set_config(db_session, "notify_on_disk", False)
    set_config(db_session, "disk_usage_warn_percent", 0)
    monkeypatch.setattr("app.notify.triggers.shutil.disk_usage",
                        lambda path: types.SimpleNamespace(total=1000, free=100))
    check_disk_usage(db_session)
    assert FakeSMTP.calls == []


def test_reconcile_switch_off_suppresses_delivery(db_session,
                                                  smtp_monkeypatched,
                                                  smtp_configured):
    from app.notify.triggers import notify_usage_reconcile_deviation

    set_config(db_session, "notify_on_reconcile", False)
    notify_usage_reconcile_deviation(db_session, month="2026-09",
                                     ledger_units=100, platform_units=130,
                                     deviation_pct=30.0)
    assert FakeSMTP.calls == []


# ---------- 去重键形态：notify_last_sent_<category>_<key> ----------


def test_suspect_transition_uses_own_dedupe_category(db_session,
                                                     smtp_monkeypatched,
                                                     smtp_configured):
    """疑似失效通知的 24h 去重状态必须落在 suspect 类别键下（与硬失效分列）。"""
    _seed_direction_with_sources(db_session, "疑似方向", 1)
    src = db_session.query(Source).one()
    src.empty_rounds = 2
    db_session.commit()
    _update_source_health(db_session, src,
                          _error_stats(error=None, http_status=200))
    assert src.failure_level == "suspect"
    assert len(FakeSMTP.calls) == 1
    assert get_config(db_session,
                      f"notify_last_sent_source_suspect_source-{src.id}")


def test_budget_dedupe_key_carries_site_timezone_date(db_session,
                                                      smtp_monkeypatched,
                                                      smtp_configured):
    """Token 预算通知去重键带站点时区自然日（每自然日至多一次的承载形态）。"""
    from app.notify.triggers import notify_budget_exceeded
    from app.timeline import local_date_key, site_zone

    day = local_date_key(site_zone(db_session))
    notify_budget_exceeded(db_session, used_tokens=600, budget=500)
    assert len(FakeSMTP.calls) == 1
    assert get_config(db_session,
                      f"notify_last_sent_token_budget_daily-{day}")


# ---------- 聚合哨兵：判定口径 / 计数持久化 / 恢复清零 ----------


def test_collective_counts_hard_failed_sources(db_session,
                                               smtp_monkeypatched,
                                               smtp_configured):
    """硬失效源计入聚合降级判定：超半数硬失效持续 2 轮必须通知。"""
    from app.notify.triggers import check_collective_sentinel

    _seed_direction_with_sources(db_session, "硬失效面", 3,
                                 enabled=True, failure_level="hard_failed")
    check_collective_sentinel(db_session)
    out = check_collective_sentinel(db_session)
    assert out["sent"] is True
    assert len(FakeSMTP.calls) == 1


def test_collective_counts_rate_limited_sources(db_session,
                                                smtp_monkeypatched,
                                                smtp_configured):
    """降频源计入聚合降级判定：超半数降频持续 2 轮必须通知。"""
    from app.notify.triggers import check_collective_sentinel

    d = _seed_direction_with_sources(db_session, "降频面", 3, enabled=True)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    for src in db_session.query(Source).filter(Source.direction_id == d.id)[:2]:
        src.rate_limited_until = future
    db_session.commit()
    check_collective_sentinel(db_session)
    out = check_collective_sentinel(db_session)
    assert out["sent"] is True
    assert len(FakeSMTP.calls) == 1


def test_collective_healthy_round_keeps_counter_clear(db_session,
                                                      smtp_monkeypatched,
                                                      smtp_configured):
    """全部源健康时不进入持续计数（轮次计数键保持空/零），也不通知。"""
    from app.notify.triggers import check_collective_sentinel

    _seed_direction_with_sources(db_session, "健康面", 3, enabled=True)
    out = check_collective_sentinel(db_session)
    assert out["sent"] is False
    assert not get_config(db_session, "collective_sentinel_rounds")
    assert FakeSMTP.calls == []


def test_collective_sustained_count_persisted_after_first_round(db_session,
                                                                smtp_monkeypatched,
                                                                smtp_configured):
    """持续计数在首轮即持久化到 site_config（键名 collective_sentinel_rounds，
    重启不丢的承载形态）。"""
    from app.notify.triggers import check_collective_sentinel

    _seed_direction_with_sources(db_session, "持续面", 3,
                                 enabled=True, failure_level="suspect")
    check_collective_sentinel(db_session)
    assert get_config(db_session, "collective_sentinel_rounds") == 1


def test_collective_exactly_half_not_sufficient(db_session,
                                                smtp_monkeypatched,
                                                smtp_configured):
    """恰好一半源降级不构成「超过一半」：持续任意轮数都不通知。"""
    from app.notify.triggers import check_collective_sentinel

    d = _seed_direction_with_sources(db_session, "半数面", 4, enabled=True)
    for src in db_session.query(Source).filter(Source.direction_id == d.id)[:2]:
        src.failure_level = "suspect"
    db_session.commit()
    check_collective_sentinel(db_session)
    check_collective_sentinel(db_session)
    check_collective_sentinel(db_session)
    assert FakeSMTP.calls == []


def test_collective_recovery_resets_sustained_counter(db_session,
                                                      smtp_monkeypatched,
                                                      smtp_configured):
    """降级缓解后连续计数清零：重新降级必须重新累计满 2 轮才再次通知。"""
    from app.notify.triggers import check_collective_sentinel

    d = _seed_direction_with_sources(db_session, "恢复面", 3, enabled=True)
    srcs = db_session.query(Source).filter(Source.direction_id == d.id).all()
    for src in srcs[:2]:
        src.failure_level = "suspect"
    db_session.commit()
    check_collective_sentinel(db_session)
    check_collective_sentinel(db_session)  # 第 1 次通知
    assert len(FakeSMTP.calls) == 1
    for src in srcs:
        src.failure_level = "none"
    db_session.commit()
    check_collective_sentinel(db_session)  # 恢复：计数清零
    for src in srcs[:2]:
        src.failure_level = "suspect"
    db_session.commit()
    # 重新降级第 1 轮：计数必须从 1 重新起算（24h 去重使二次通知不可经
    # SMTP 打桩观测，改以计数键直接观测持续累计的重新起算）
    check_collective_sentinel(db_session)
    assert get_config(db_session, "collective_sentinel_rounds") == 1


def test_collective_notice_subject_carries_degradation_name(db_session,
                                                            smtp_monkeypatched,
                                                            smtp_configured):
    """整体降级通知标题必须承载「采集面整体降级」事件名。"""
    from app.notify.triggers import check_collective_sentinel

    _seed_direction_with_sources(db_session, "标题面", 3,
                                 enabled=True, failure_level="suspect")
    check_collective_sentinel(db_session)
    check_collective_sentinel(db_session)
    assert len(FakeSMTP.calls) == 1
    subject = str(make_header(decode_header(
        message_from_string(FakeSMTP.calls[-1]["msg"])["Subject"])))
    assert "采集面整体降级" in subject
    # 24h 去重状态落在固定类别键（collective_degradation/collective）下
    assert get_config(db_session,
                      "notify_last_sent_collective_degradation_collective")


# ---------- 磁盘阈值：用量计量与严格大于判定 ----------


def test_disk_used_percent_computed_from_volume_usage(db_session,
                                                      smtp_monkeypatched,
                                                      monkeypatch):
    """磁盘用量百分比 =（总-余）/总×100（保留 1 位小数），未超阈值时零投递。"""
    from app.notify.triggers import check_disk_usage

    monkeypatch.setattr("app.notify.triggers.shutil.disk_usage",
                        lambda path: types.SimpleNamespace(total=999, free=333))
    out = check_disk_usage(db_session)
    assert out["used_percent"] == 66.7
    assert FakeSMTP.calls == []


def test_disk_threshold_is_strictly_greater(db_session, smtp_monkeypatched,
                                            smtp_configured, monkeypatch):
    """用量恰等于阈值不算「超过」：零投递、原因归入未超阈值。"""
    from app.notify.triggers import check_disk_usage

    set_config(db_session, "disk_usage_warn_percent", 0)
    monkeypatch.setattr("app.notify.triggers.shutil.disk_usage",
                        lambda path: types.SimpleNamespace(total=1000, free=1000))
    out = check_disk_usage(db_session)
    assert out["sent"] is False
    assert out["used_percent"] == 0.0
    assert FakeSMTP.calls == []


def test_disk_notification_uses_stable_dedupe_key(db_session,
                                                  smtp_monkeypatched,
                                                  smtp_configured,
                                                  monkeypatch):
    """磁盘告警通知的去重状态落在固定类别键（disk_usage/disk）下。"""
    from app.notify.triggers import check_disk_usage

    set_config(db_session, "disk_usage_warn_percent", 0)
    monkeypatch.setattr("app.notify.triggers.shutil.disk_usage",
                        lambda path: types.SimpleNamespace(total=1000, free=100))
    out = check_disk_usage(db_session)
    assert out["sent"] is True
    assert get_config(db_session, "notify_last_sent_disk_usage_disk")
