"""hard_failed 复活路径测试（BE-3/AC-1）：抓取成功轮复位死刑态（failure_since
与探活时钟一并清空）、复活通知恰一次（hard_failed→none 转换点）、suspect 复活
不通知、开关与失效同族（notify_on_source_failure 共用）。

设计依据见 docs/design-index.md「DT-1」「SM-1」（BE-3 增补）。
"""
import types
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Direction, Source
from app.notify import hub
from app.pipeline.runner import _update_source_health
from app.siteconfig import set_config


def _stats(**kw) -> types.SimpleNamespace:
    """最小抓取统计（形态对齐采集器产出的 SourceFetchStats 消费面）。"""
    base = dict(error=None, feed_entries=0, inserted=0, not_modified=False,
                rate_limited=False, retry_after=None, extra={})
    base.update(kw)
    return types.SimpleNamespace(**base)


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
    # BE-2 判例：经 _dispatch→hub 的测试必复位进程内队列/锚点
    hub._reset_for_tests()
    monkeypatch.setattr("app.notify.smtp.smtplib.SMTP_SSL", FakeSMTP)
    return FakeSMTP


@pytest.fixture()
def smtp_configured(db_session):
    set_config(db_session, "smtp_host", "smtp.example.com")
    set_config(db_session, "smtp_port", 465)
    set_config(db_session, "smtp_from", "bot@example.com")
    set_config(db_session, "smtp_to", ["me@example.com"])


@pytest.fixture()
def dead_source(db_session):
    d = Direction(name="复活路径方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://recovery.example/rss",
                 failure_level="hard_failed", hard_failures=3,
                 failure_since=datetime.now(timezone.utc) - timedelta(days=9))
    db_session.add(src)
    db_session.commit()
    return src


def test_success_round_recovers_hard_failed(db_session, dead_source):
    """hard_failed 源非空成功轮：复位 none + failure_since 清空 + 探活时钟
    last_probe_at 一并清空（复活即全新正常态）。"""
    src = dead_source
    src.last_probe_at = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.commit()
    _update_source_health(db_session, src, _stats(feed_entries=5))
    src = db_session.merge(src)
    assert src.failure_level == "none"
    assert src.failure_since is None
    assert src.last_probe_at is None
    assert src.hard_failures == 0 and src.empty_rounds == 0


def test_not_modified_round_recovers_hard_failed(db_session, dead_source):
    """304 轮与非空轮同语义（现状口径保持）：hard_failed 复位。"""
    _update_source_health(db_session, dead_source, _stats(not_modified=True))
    src = db_session.merge(dead_source)
    assert src.failure_level == "none"
    assert src.failure_since is None and src.last_probe_at is None


def test_recovery_notifies_once_and_dedupes(db_session, dead_source,
                                            smtp_monkeypatched,
                                            smtp_configured):
    """复活通知恰一次：hard_failed→none 转换入队 source_recovered 一封；
    去重窗口内二连成功（第二次无转换）不重发。"""
    _update_source_health(db_session, dead_source, _stats(feed_entries=5))
    assert dead_source.failure_level == "none"
    hub.flush(db_session)
    assert len(FakeSMTP.calls) == 1
    import email
    import email.policy

    msg = email.message_from_string(FakeSMTP.calls[0]["msg"],
                                    policy=email.policy.default)
    body = msg.get_content()
    assert "来源已复活恢复采集" in body  # 文案中文（BE-3 任务书 AC-1）
    assert "https://recovery.example/rss" in body
    # 二连成功：状态已 none，无转换不再触发
    _update_source_health(db_session, dead_source, _stats(feed_entries=6))
    hub.flush(db_session)
    assert len(FakeSMTP.calls) == 1


def test_recovery_notification_deduped_within_window(
        db_session, dead_source, smtp_monkeypatched, smtp_configured):
    """复活通知与源失效同去重键 source-{id}：直接二次触发同键被 hub 去重
    （24h 窗口内不重发）。"""
    from app.notify.triggers import notify_source_recovered

    out1 = notify_source_recovered(db_session, dead_source)
    assert out1["queued"] is True
    out2 = notify_source_recovered(db_session, dead_source)
    assert out2.get("queued") is False or out2.get("reason") == "deduped"


def test_suspect_recovery_does_not_notify(db_session, smtp_monkeypatched,
                                          smtp_configured):
    """suspect→none 复活不通知（降频探测恢复非事件，维持现状）。"""
    d = Direction(name="suspect 复活方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://suspect.example/rss",
                 failure_level="suspect")
    db_session.add(src)
    db_session.commit()
    _update_source_health(db_session, src, _stats(feed_entries=5))
    assert src.failure_level == "none"
    hub.flush(db_session)
    assert FakeSMTP.calls == []


def test_recovery_respects_failure_switch(db_session, dead_source,
                                          smtp_monkeypatched,
                                          smtp_configured):
    """复活通知与失效共一开关：notify_on_source_failure 关 → 仅落日志不入队。"""
    set_config(db_session, "notify_on_source_failure", False)
    _update_source_health(db_session, dead_source, _stats(feed_entries=5))
    assert dead_source.failure_level == "none"
    hub.flush(db_session)
    assert FakeSMTP.calls == []


def test_category_registry_has_source_recovered():
    """类别注册表钉面：source_recovered = alert / priority=2（与 reconcile
    同档低紧迫）。"""
    assert hub.CATEGORY_REGISTRY["source_recovered"] == {
        "family": "alert", "priority": 2, "default_min_interval_s": 0}
