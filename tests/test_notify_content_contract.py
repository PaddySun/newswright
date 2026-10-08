"""通知内容承载与投递门槛契约测试（AC-19.5，2026-10-08 拍板条款）。

覆盖口径（设计依据见 docs/design-index.md「AC-19.5」「AC-19.2」「AC-19.3」
「AC-19.4」）：
- 内容承载：任一触发条件达成且 SMTP 已配置时，邮件须承载事件主题与正文
  （空主题/空正文投递视同无效通知）——通道层 send、派发层、五类触发
  （源失效/预算/对账/聚合哨兵/磁盘）的 subject/body 构造与透传环节均断言
  内容非空且承载事件原文；
- MIME 头形态符合 RFC 5322：Subject/From/To 头名在位、头值非空、多收件人
  邮箱列表为逗号+空格分隔的标准形态；
- 投递认证门槛=账号与密码齐备方可登录：半凭据（有账号无密码）配置不得发起
  登录；未通过认证的会话被服务器拒收（桩按真实 SMTP 语义：未登录会话的
  sendmail 以 530 拒绝），投递失败留痕（不落去重时间戳、允许恢复后重发）。

网络纪律：FakeSMTP 捕获 sendmail 消息原文（email 解析断言），不真联网；
生产代码零改动。
"""
import email
import smtplib
import types

import pytest

from app.models import Direction, Source
from app.notify import default_notifier, get_notifier
from app.notify.smtp import SMTPNotifier
from app.notify.triggers import (
    check_collective_sentinel,
    check_disk_usage,
    notify_budget_exceeded,
    notify_source_failure,
    notify_usage_reconcile_deviation,
)
from app.siteconfig import get_config, set_config


class ContractSMTP:
    """smtplib.SMTP_SSL 桩（真实服务器语义：未认证会话的 sendmail 以 530 拒绝）。"""

    calls: list[dict] = []
    fail = False

    def __init__(self, host, port, timeout=None):
        ContractSMTP.calls.append({"host": host, "port": port})
        self._logged_in = False
        self._login_log = []
        if ContractSMTP.fail:
            raise ConnectionRefusedError("[Errno 111] Connection refused")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self._login_log.append((user, password))
        ContractSMTP.calls[-1]["login"] = list(self._login_log)
        if not password:
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 credentials required")
        self._logged_in = True

    def sendmail(self, from_addr, to_addrs, msg):
        if not self._logged_in:
            # 真实 SMTP 语义：未通过认证的会话不允许发信（RFC 4954 / 530 响应）
            raise smtplib.SMTPSenderRefused(530, b"5.7.0 Authentication required",
                                            from_addr)
        ContractSMTP.calls[-1]["from"] = from_addr
        ContractSMTP.calls[-1]["to"] = list(to_addrs)
        ContractSMTP.calls[-1]["msg"] = msg


@pytest.fixture()
def smtp_stubbed(monkeypatch):
    ContractSMTP.calls = []
    ContractSMTP.fail = False
    monkeypatch.setattr("app.notify.smtp.smtplib.SMTP_SSL", ContractSMTP)
    return ContractSMTP


@pytest.fixture()
def smtp_ready(db_session):
    set_config(db_session, "smtp_host", "smtp.example.com")
    set_config(db_session, "smtp_port", 465)
    set_config(db_session, "smtp_user", "bot@example.com")
    set_config(db_session, "smtp_pass", "super-secret-pass")
    set_config(db_session, "smtp_from", "bot@example.com")
    set_config(db_session, "smtp_to", ["me@example.com", "other@example.com"])


def _last_message(stub):
    import email.policy

    raw = stub.calls[-1]["msg"]
    if isinstance(raw, bytes):
        return email.message_from_bytes(raw, policy=email.policy.default)
    return email.message_from_string(raw, policy=email.policy.default)


def _assert_valid_delivery(msg: email.message.Message) -> str:
    """AC-19.5 投递有效性：主题/正文承载非空、RFC 5322 头形态完整。"""
    subject = msg["Subject"]
    sender = msg["From"]
    recipients = msg["To"]
    body = msg.get_content()
    assert subject is not None and subject.strip() != "", "空主题投递=无效通知"
    assert sender is not None and sender.strip() != "", "空发件人投递=无效通知"
    assert recipients is not None and recipients.strip() != "", "空收件人投递=无效通知"
    assert body is not None and body.strip() != "", "空正文投递=无效通知"
    return subject


def test_channel_send_carries_subject_and_body(db_session, smtp_stubbed, smtp_ready):
    """通道层内容承载：send 的主题与正文原样进入邮件（含收件人列表形态）。"""
    notifier = get_notifier("smtp", db_session)
    out = notifier.send("事件主题承载验证", "事件正文承载验证",
                        category="fetch_failure", dedupe_key="carry-1")
    assert out["sent"] is True
    msg = _last_message(smtp_stubbed)
    subject = _assert_valid_delivery(msg)
    assert "事件主题承载验证" in subject
    assert "事件正文承载验证" in msg.get_content()
    assert msg["To"] == "me@example.com, other@example.com"  # RFC 5322 邮箱列表


def test_source_failure_notification_content(db_session, smtp_stubbed, smtp_ready):
    """源失效通知链：主题承载来源 URL、正文承载失效语义。"""
    set_config(db_session, "notify_on_source_failure", True)
    d = Direction(name="内容方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://content.example/feed",
                 last_error="HTTPError: 500")
    db_session.add(src)
    db_session.commit()
    out = notify_source_failure(db_session, src, level="hard_failed")
    assert out["sent"] is True
    msg = _last_message(smtp_stubbed)
    subject = _assert_valid_delivery(msg)
    assert "https://content.example/feed" in subject
    assert "硬失效" in subject
    assert "来源 id" in msg.get_content() and "HTTPError: 500" in msg.get_content()


def test_budget_notification_content(db_session, smtp_stubbed, smtp_ready):
    """预算通知链：主题承载日期键、正文承载消耗与降级秩序语义。"""
    set_config(db_session, "notify_on_token_budget", True)
    out = notify_budget_exceeded(db_session, used_tokens=1200, budget=1000)
    assert out["sent"] is True
    msg = _last_message(smtp_stubbed)
    _assert_valid_delivery(msg)
    assert "Token 日预算" in msg["Subject"]
    body = msg.get_content()
    assert "1200" in body and "1000" in body


def test_reconcile_notification_content(db_session, smtp_stubbed, smtp_ready):
    """对账偏差通知链：主题承载月份与偏差、正文承载双方账目数值。"""
    set_config(db_session, "notify_on_reconcile", True)
    out = notify_usage_reconcile_deviation(db_session, month="2026-09",
                                           ledger_units=100, platform_units=130,
                                           deviation_pct=30.0)
    assert out["sent"] is True
    msg = _last_message(smtp_stubbed)
    _assert_valid_delivery(msg)
    assert "2026-09" in msg["Subject"]
    body = msg.get_content()
    assert "130" in body and "100" in body


def test_collective_sentinel_notification_content(db_session, smtp_stubbed,
                                                  smtp_ready):
    """聚合哨兵通知链：主题为钉名的「采集面整体降级」、正文承载状态计数。"""
    set_config(db_session, "notify_on_collective", True)
    d = Direction(name="哨兵方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    for i in range(3):
        db_session.add(Source(direction_id=d.id, url=f"https://s{i}.example/f",
                              enabled=True, failure_level="hard_failed"))
    db_session.commit()
    # 第一轮：未满持续轮次不投递；第二轮：触发整体降级通知
    check_collective_sentinel(db_session)
    out = check_collective_sentinel(db_session)
    assert out["sent"] is True
    msg = _last_message(smtp_stubbed)
    _assert_valid_delivery(msg)
    assert "采集面整体降级" in msg["Subject"]
    assert "3" in msg.get_content()


def test_disk_notification_content(db_session, smtp_stubbed, smtp_ready, monkeypatch):
    """磁盘通知链：主题承载用量、正文承载阈值与剩余空间。"""
    set_config(db_session, "notify_on_disk", True)
    set_config(db_session, "disk_usage_warn_percent", 80)
    monkeypatch.setattr("app.notify.triggers.shutil.disk_usage",
                        lambda path: types.SimpleNamespace(total=1000, free=100))
    out = check_disk_usage(db_session)
    assert out["sent"] is True
    msg = _last_message(smtp_stubbed)
    _assert_valid_delivery(msg)
    assert "磁盘用量" in msg["Subject"]
    body = msg.get_content()
    assert "90.0" in body and "80.0" in body


def test_half_credentials_never_attempt_login_and_refuse_delivery(db_session,
                                                                   smtp_stubbed):
    """半凭据门槛：有账号无密码不得发起登录；未认证会话被服务器拒收并留痕。"""
    set_config(db_session, "smtp_host", "smtp.example.com")
    set_config(db_session, "smtp_port", 465)
    set_config(db_session, "smtp_user", "bot@example.com")
    set_config(db_session, "smtp_from", "bot@example.com")
    set_config(db_session, "smtp_to", ["me@example.com"])
    # smtp_pass 有意不配置——半凭据形态
    notifier = get_notifier("smtp", db_session)
    out = notifier.send("标题", "正文", category="fetch_failure",
                        dedupe_key="half-cred")
    assert out["sent"] is False  # 投递被拒（未认证会话 530）
    logins = ContractSMTP.calls[-1].get("login", []) if ContractSMTP.calls else []
    assert all(password for _u, password in logins), \
        "AC-19.5：账号与密码齐备方可登录（不得以空密码发起登录）"
    assert get_config(db_session, "notify_last_sent_fetch_failure_half-cred") is None
