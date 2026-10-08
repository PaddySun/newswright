"""出网 UA 策略契约测试：策略键配置消费与 honest 模板形态。

覆盖口径（设计依据见 docs/design-index.md「R9」，模块 docstring 契约）：
- effective_user_agent：honest=诚实模板（产品名+联系邮箱位）；custom=自配串、
  空串回退 honest（空 UA 是更强的拦截指纹）——custom 空配置与 contact_email
  配置的消费面；
- honest_user_agent：未配邮箱=只有产品标识（不得出现 contact 位）；配邮箱=
  邮箱进入 UA。

纯函数+内存站点配置，零出网；生产代码零改动。
"""
import pytest

from app.ingest.http import effective_user_agent, honest_user_agent
from app.siteconfig import set_config

HONEST_BASE_MARK = "newswright/1.0"


def test_custom_empty_falls_back_to_honest(db_session):
    """custom 策略 + ua_custom 空白：回退 honest 模板（不得让空串/垃圾值出网）。"""
    set_config(db_session, "ua_strategy", "custom")
    set_config(db_session, "ua_custom", "   ")
    ua = effective_user_agent(db_session)
    assert HONEST_BASE_MARK in ua
    assert "XXXX" not in ua


def test_custom_empty_fallback_keeps_contact_email(db_session):
    """custom 空回退 honest 时联系邮箱位仍按站点配置携带。"""
    set_config(db_session, "ua_strategy", "custom")
    set_config(db_session, "ua_custom", "")
    set_config(db_session, "contact_email", "ops@example.com")
    ua = effective_user_agent(db_session)
    assert "contact: ops@example.com" in ua


def test_honest_carries_configured_contact_email(db_session):
    """honest 策略：contact_email 配置进入 UA（策略键配置消费）。"""
    set_config(db_session, "ua_strategy", "honest")
    set_config(db_session, "contact_email", "bot@example.com")
    ua = effective_user_agent(db_session)
    assert "contact: bot@example.com" in ua


def test_honest_without_email_has_no_contact_slot():
    """未配邮箱（None）：UA 只有产品标识，不出现 contact 位。"""
    ua = honest_user_agent(None)
    assert HONEST_BASE_MARK in ua
    assert "contact" not in ua


def test_honest_with_email_appends_contact():
    """配邮箱：邮箱原文进入 UA 的 contact 位。"""
    ua = honest_user_agent("bot@example.com")
    assert "contact: bot@example.com" in ua
    assert HONEST_BASE_MARK in ua
