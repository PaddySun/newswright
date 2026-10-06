"""通知通道插件测试：SMTP 打桩三景、24h 去重跨会话持久化、凭据不落日志。

设计依据见 docs/design-index.md「AC-19.1」「AC-19.2」「ADR-10」。
"""
import logging

import pytest

from app.notify import available, default_notifier, get_notifier, register
from app.notify.smtp import SMTPNotifier
from app.siteconfig import get_config, set_config


class FakeSMTP:
    """smtplib.SMTP_SSL 打桩：记录调用，可注入连接失败。"""

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
        FakeSMTP.calls[-1]["user"] = user
        FakeSMTP.calls[-1]["password"] = password

    def sendmail(self, from_addr, to_addrs, msg):
        FakeSMTP.calls[-1]["from"] = from_addr
        FakeSMTP.calls[-1]["to"] = list(to_addrs)
        FakeSMTP.calls[-1]["msg"] = msg


@pytest.fixture()
def smtp_monkeypatched(monkeypatch):
    FakeSMTP.calls = []
    FakeSMTP.fail = False
    monkeypatch.setattr("app.notify.smtp.smtplib.SMTP_SSL", FakeSMTP)
    return FakeSMTP


def _configure_smtp(db):
    set_config(db, "smtp_host", "smtp.example.com")
    set_config(db, "smtp_port", 465)
    set_config(db, "smtp_user", "bot@example.com")
    set_config(db, "smtp_pass", "super-secret-pass")
    set_config(db, "smtp_from", "bot@example.com")
    set_config(db, "smtp_to", ["me@example.com"])


def test_registry_semantics(db_session):
    register("smtp", SMTPNotifier)  # 重复注册幂等
    assert "smtp" in available()
    notifier = get_notifier("smtp", db_session)
    assert isinstance(notifier, SMTPNotifier)
    assert default_notifier(db_session) is not None


def test_smtp_send_success_records_dedupe(db_session, smtp_monkeypatched):
    _configure_smtp(db_session)
    notifier = get_notifier("smtp", db_session)
    out = notifier.send("标题", "正文", category="fetch_failure", dedupe_key="src-1")
    assert out == {"sent": True}
    call = smtp_monkeypatched.calls[-1]
    assert call["host"] == "smtp.example.com" and call["port"] == 465
    assert call["to"] == ["me@example.com"]
    assert get_config(db_session, "notify_last_sent_fetch_failure_src-1")


def test_smtp_unreachable_warns_not_raises(db_session, smtp_monkeypatched, caplog):
    _configure_smtp(db_session)
    smtp_monkeypatched.fail = True
    notifier = get_notifier("smtp", db_session)
    with caplog.at_level(logging.WARNING, logger="newswright.notify"):
        out = notifier.send("标题", "正文", category="fetch_failure", dedupe_key="src-1")
    assert out == {"sent": False, "reason": "deliver_failed"}
    assert any("通知投递失败" in r.message for r in caplog.records)
    # 失败不落去重时间戳（允许恢复后重发）
    assert get_config(db_session, "notify_last_sent_fetch_failure_src-1") is None


def test_unconfigured_event_logged_only(db_session, smtp_monkeypatched, caplog):
    notifier = get_notifier("smtp", db_session)  # 不写任何 smtp_* 键
    with caplog.at_level(logging.INFO, logger="newswright.notify"):
        out = notifier.send("标题", "正文", category="disk", dedupe_key="disk-1")
    assert out == {"sent": False, "reason": "not_configured"}
    assert smtp_monkeypatched.calls == []  # 未配置零 SMTP 调用
    assert any("未配置" in r.message for r in caplog.records)


def test_dedupe_survives_restart_new_session(db_session, smtp_monkeypatched):
    """24h 去重持久化到 site_config：跨"重启"（新 Session）仍生效。"""
    _configure_smtp(db_session)
    get_notifier("smtp", db_session).send("标题", "正文",
                                          category="token_budget", dedupe_key="daily")
    # 模拟重启：全新会话（同库），再次触发同 category/key
    import app.db as appdb

    with appdb.SessionLocal() as fresh_db:
        out = get_notifier("smtp", fresh_db).send(
            "标题", "正文", category="token_budget", dedupe_key="daily")
    assert out == {"sent": False, "reason": "deduped"}
    assert len(smtp_monkeypatched.calls) == 1  # 第二次未触达 SMTP
    # 不同 dedupe_key 不受去重影响
    out2 = get_notifier("smtp", db_session).send(
        "标题", "正文", category="token_budget", dedupe_key="daily-2")
    assert out2 == {"sent": True}


def test_credentials_never_logged(db_session, smtp_monkeypatched, caplog):
    _configure_smtp(db_session)
    smtp_monkeypatched.fail = True
    with caplog.at_level(logging.DEBUG):
        get_notifier("smtp", db_session).send("标题", "正文",
                                              category="fetch_failure",
                                              dedupe_key="src-x")
    assert "super-secret-pass" not in caplog.text
