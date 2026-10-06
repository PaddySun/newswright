"""通知触发接线测试：设置端点三态、四触发去重、未配置零报错、每日备份。

设计依据见 docs/design-index.md「AC-19.1」「AC-19.2」「AC-19.3」「AC-19.4」。
"""
import logging
import types

import pytest

from app.models import Direction, Source
from app.pipeline.runner import _update_source_health, score_round
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


def _seed_source(db):
    d = Direction(name="通知方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://dead.example/rss")
    db.add(src)
    db.commit()
    return src


# ---------- AC-19.1：设置端点三态 ----------


def test_notify_settings_put_get_and_no_credential_echo(auth_client, db_session):
    r = auth_client.put("/api/settings/notify", json={
        "smtp_host": "smtp.example.com", "smtp_port": 465,
        "smtp_user": "bot@example.com", "smtp_pass": "super-secret-pass",
        "from_addr": "bot@example.com", "to_addrs": ["me@example.com"],
        "notify_on_disk": False,
    })
    assert r.status_code == 200, r.text
    assert r.json()["smtp_configured"] is True
    assert "super-secret-pass" not in r.text
    r2 = auth_client.get("/api/settings/notify")
    assert r2.status_code == 200
    body = r2.json()
    assert body["smtp_configured"] is True  # 凭据只出布尔位
    assert "smtp_pass" not in body and "super-secret-pass" not in r2.text
    assert body["notify_on_disk"] is False


def test_notify_test_endpoint_ok_and_unreachable(auth_client, db_session,
                                                 smtp_monkeypatched,
                                                 smtp_configured):
    r = auth_client.post("/api/settings/notify/test")
    assert r.status_code == 200
    smtp_monkeypatched.fail = True
    r2 = auth_client.post("/api/settings/notify/test")
    assert r2.status_code == 502
    assert r2.json()["code"] == "SMTP_UNREACHABLE"


def test_notify_test_endpoint_unconfigured_502(auth_client):
    r = auth_client.post("/api/settings/notify/test")
    assert r.status_code == 502
    assert r.json()["code"] == "SMTP_UNREACHABLE"


# ---------- 触发①：源失效状态转换（DT-1 挂钩，同源 24h 去重） ----------


def test_hard_fail_transition_notifies_once_per_source(db_session,
                                                       smtp_monkeypatched,
                                                       smtp_configured):
    src = _seed_source(db_session)
    src.hard_failures = 2
    db_session.commit()
    _update_source_health(db_session, src, _error_stats(404))
    assert src.failure_level == "hard_failed"
    assert len(FakeSMTP.calls) == 1
    assert get_config(db_session, "notify_last_sent_source_hard_fail_source-1")
    # 同源再触发（复位后再次达成阈值）→ 24h 去重不重发
    src.failure_level = "none"
    db_session.commit()
    _update_source_health(db_session, src, _error_stats(404))
    assert len(FakeSMTP.calls) == 1  # 去重命中


def test_suspect_transition_notifies(db_session, smtp_monkeypatched,
                                     smtp_configured):
    src = _seed_source(db_session)
    src.empty_rounds = 2
    db_session.commit()
    _update_source_health(db_session, src, _error_stats(
        error=None, http_status=200))
    # 空轮侧：error=None 且 feed_entries=0 → suspect（非 skip_day）
    assert src.failure_level == "suspect"
    assert len(FakeSMTP.calls) == 1


def test_source_failure_unconfigured_logs_only(db_session, smtp_monkeypatched,
                                               caplog):
    src = _seed_source(db_session)
    src.hard_failures = 2
    db_session.commit()
    with caplog.at_level(logging.INFO, logger="newswright.notify"):
        _update_source_health(db_session, src, _error_stats(404))
    assert src.failure_level == "hard_failed"
    assert FakeSMTP.calls == []  # 未配置零 SMTP 调用
    assert any("未配置" in r.message for r in caplog.records)


# ---------- 触发②：Token 日预算（每自然日至多一次） ----------


def test_budget_notification_deduped_within_day(db_session, smtp_monkeypatched,
                                                smtp_configured, monkeypatch):
    from app.models import Item

    d = Direction(name="预算方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://x.com/rss")
    db_session.add(src)
    db_session.commit()
    db_session.add(Item(source_id=src.id, guid="b1", url="https://x.com/1",
                        title="t", content_text="正文", fetch_status="FETCHED",
                        direction_id=d.id, sanitize_status="PASSED"))
    from app.models import UsageLog

    db_session.add(UsageLog(provider="p", model="m", call_point="scoring",
                            prompt_tokens=1000))
    db_session.commit()
    set_config(db_session, "daily_token_budget", 500)

    def fake_score(db, item, direction):
        sr = types.SimpleNamespace(status="OK", passed=True, error=None)
        return sr

    monkeypatch.setattr("app.scoring.service.score_item", fake_score)
    score_round(db_session, triggered_by="test")
    assert len(FakeSMTP.calls) == 1
    # 预算仍超限的第二轮：通知去重（每自然日至多一次）
    score_round(db_session, triggered_by="test")
    assert len(FakeSMTP.calls) == 1


# ---------- 触发③：采集面聚合哨兵（持续 2 轮超半数） ----------


def test_collective_sentinel_requires_two_sustained_rounds(db_session,
                                                           smtp_monkeypatched,
                                                           smtp_configured):
    from app.notify.triggers import check_collective_sentinel

    d = Direction(name="哨兵方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    for i in range(3):
        src = Source(direction_id=d.id, url=f"https://s{i}.example/rss",
                     enabled=True,
                     failure_level="suspect" if i < 2 else "none")
        db_session.add(src)
    db_session.commit()
    out1 = check_collective_sentinel(db_session)
    assert out1["sent"] is False and out1["reason"] == "sustained_1"
    assert len(FakeSMTP.calls) == 0
    out2 = check_collective_sentinel(db_session)  # 持续第 2 轮 → 通知
    assert out2["sent"] is True
    assert len(FakeSMTP.calls) == 1


# ---------- 触发④：磁盘阈值 ----------


def test_disk_threshold_notification(db_session, smtp_monkeypatched,
                                     smtp_configured):
    from app.notify.triggers import check_disk_usage

    set_config(db_session, "disk_usage_warn_percent", 0)  # 阈值 0 → 必触发
    out = check_disk_usage(db_session)
    assert out["sent"] is True
    assert out["used_percent"] > 0
    # 24h 去重：同 key 不重发
    out2 = check_disk_usage(db_session)
    assert out2["sent"] is False and out2["reason"] == "deduped"


# ---------- 每日备份 ----------


def test_daily_backup_tick_creates_backup(tmp_path, db_session, monkeypatch):
    import app.scheduler as sched

    directory = tmp_path / "backups"
    set_config(db_session, "backup_dir", str(directory))
    sched._tick_backup()
    files = list(directory.glob("newswright-backup-*"))
    assert len(files) == 1
    assert files[0].stat().st_size > 0


def test_daily_backup_failure_warns_not_raises(tmp_path, db_session,
                                               monkeypatch, caplog):
    import app.scheduler as sched

    # 备份目录指向一个文件路径 → mkdir/写失败 → WARN 不抛
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    set_config(db_session, "backup_dir", str(blocker / "nested"))
    with caplog.at_level(logging.WARNING):
        sched._tick_backup()  # 不得抛出
    assert any("备份" in r.message for r in caplog.records)
