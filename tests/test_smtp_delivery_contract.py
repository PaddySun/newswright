"""SMTP 通道投递契约测试：site_config 配置值（host/port/凭据/发信人）必须原样
进入投递调用，外部 SMTP 连接必须带显式超时，收件配置双键只认 API 写入口键；
configured 布位按「必填四项齐备」判定；24h 去重窗口边界语义（恰好 24 小时
不视为窗口内）。

设计依据见 docs/design-index.md「AC-19.1」「AC-19.2」「ADR-10」。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.notify import get_notifier
from app.notify.smtp import SMTPNotifier
from app.siteconfig import get_config, set_config


class FakeSMTP:
    """smtplib.SMTP_SSL 打桩：记录全部构造参数与认证/信封实参。"""

    calls: list[dict] = []

    def __init__(self, host, port, timeout=None):
        FakeSMTP.calls.append({"host": host, "port": port, "timeout": timeout})

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
def smtp_stub(monkeypatch):
    FakeSMTP.calls = []
    monkeypatch.setattr("app.notify.smtp.smtplib.SMTP_SSL", FakeSMTP)
    return FakeSMTP


def _configure_full(db, *, port=587, with_credentials=True):
    set_config(db, "smtp_host", "smtp.example.com")
    set_config(db, "smtp_port", port)
    if with_credentials:
        set_config(db, "smtp_user", "bot@example.com")
        set_config(db, "smtp_pass", "super-secret-pass")
    set_config(db, "smtp_from", "bot@example.com")
    set_config(db, "smtp_to", ["me@example.com"])


def test_delivery_uses_configured_host_port_and_explicit_timeout(db_session,
                                                                 smtp_stub):
    """发信走 site_config 配置的 host/port（非缺省端口），SMTP 连接必须携带
    显式超时（任意有限值，禁无限等待）。"""
    _configure_full(db_session, port=587)
    out = get_notifier("smtp", db_session).send(
        "标题", "正文", category="fetch_failure", dedupe_key="src-1")
    assert out == {"sent": True}
    call = smtp_stub.calls[-1]
    assert call["host"] == "smtp.example.com"
    assert call["port"] == 587
    assert call["timeout"] is not None and call["timeout"] > 0


def test_delivery_authenticates_with_configured_credentials(db_session,
                                                            smtp_stub):
    """配置了账号密码时投递必须以该凭据认证（配置值原样进入 login 调用）。"""
    _configure_full(db_session)
    out = get_notifier("smtp", db_session).send(
        "标题", "正文", category="fetch_failure", dedupe_key="src-1")
    assert out == {"sent": True}
    call = smtp_stub.calls[-1]
    assert call["user"] == "bot@example.com"
    assert call["password"] == "super-secret-pass"


def test_delivery_envelope_sender_uses_configured_from(db_session, smtp_stub):
    """SMTP 信封发件人必须取 site_config 配置的 smtp_from 值。"""
    _configure_full(db_session)
    get_notifier("smtp", db_session).send(
        "标题", "正文", category="fetch_failure", dedupe_key="src-1")
    assert smtp_stub.calls[-1]["from"] == "bot@example.com"


def test_configured_requires_all_four_mandatory_fields(db_session):
    """configured 布位语义：host/port/发信人/收件列表任一缺失即未配置
    （账号密码可选）；四项齐备才为已配置。"""
    notifier = SMTPNotifier(db_session)
    set_config(db_session, "smtp_to", ["me@example.com"])
    assert notifier.configured() is False  # 仅收件列表
    set_config(db_session, "smtp_port", 465)
    set_config(db_session, "smtp_from", "bot@example.com")
    assert notifier.configured() is False  # 缺 host
    set_config(db_session, "smtp_host", "smtp.example.com")
    assert notifier.configured() is True


def test_dedupe_window_boundary_exactly_24h_is_outside(db_session):
    """去重窗口边界：距上次发送恰好 24 小时不再视为窗口内（可重发）；
    窗口内侧（差 1 秒满 24h）仍判重。"""
    notifier = get_notifier("smtp", db_session)
    key_name = notifier._dedupe_key_name("fetch_failure", "src-1")
    now = datetime.now(timezone.utc)
    set_config(db_session, key_name,
               (now - timedelta(hours=24)).isoformat())
    assert notifier._recently_sent("fetch_failure", "src-1", now=now) is False
    set_config(db_session, key_name,
               (now - timedelta(hours=24) + timedelta(seconds=1)).isoformat())
    assert notifier._recently_sent("fetch_failure", "src-1", now=now) is True
