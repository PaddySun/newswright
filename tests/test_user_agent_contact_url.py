"""UA 真链接测试（BE-4/AC-4，P1-1）：honest_user_agent 增 contact_url 参
（非空→`+{url}` 替换 `+https://localhost` 占位）；effective_user_agent 读
site_config public_base_url（strip 后非空才传——复用既有键不加新键；空值
保持占位形态）。UA 是被抓站管理员唯一申诉/识别通道，占位符是「无主爬虫」
信号。
设计依据见 docs/design-index.md「TG-4」（BE-4 增补）。
"""
import pytest

from app.siteconfig import set_config
from app.transport.http import effective_user_agent, honest_user_agent
from app.ingest.http import honest_user_agent as reexported_honest  # re-export 面不回退


PLACEHOLDER = "+https://localhost"


# ---------- honest_user_agent 模板 ----------


def test_contact_url_replaces_placeholder():
    ua = honest_user_agent("ops@example.com", contact_url="https://news.example.com")
    assert "+https://news.example.com" in ua
    assert "contact: ops@example.com" in ua
    assert "localhost" not in ua


def test_without_contact_url_keeps_placeholder():
    ua = honest_user_agent("ops@example.com")
    assert PLACEHOLDER in ua


def test_blank_contact_url_keeps_placeholder():
    """空串/纯空白 URL=未配置语义，保持占位形态。"""
    assert PLACEHOLDER in honest_user_agent(None, contact_url="  ")
    assert PLACEHOLDER in honest_user_agent("ops@example.com", contact_url="")


def test_no_email_with_contact_url():
    """无邮箱有 URL：产品名+真链接，无 contact 段。"""
    ua = honest_user_agent(None, contact_url="https://news.example.com")
    assert "+https://news.example.com" in ua
    assert "contact:" not in ua
    assert "localhost" not in ua


def test_reexport_face_signature_intact():
    """ingest.http 薄 re-export 面与实现同体（增参不破坏既有 import 面）。"""
    assert reexported_honest is honest_user_agent
    assert "+" in reexported_honest("x@example.com", contact_url="https://a.example")


# ---------- effective_user_agent 策略解析 ----------


def test_effective_ua_uses_public_base_url(db_session):
    """public_base_url 非空 → UA 含真链接、占位消失。"""
    set_config(db_session, "contact_email", "ops@example.com")
    set_config(db_session, "public_base_url", "https://newswright.example")
    ua = effective_user_agent(db_session)
    assert "+https://newswright.example" in ua
    assert "localhost" not in ua


def test_effective_ua_blank_public_base_url_keeps_placeholder(db_session):
    """public_base_url 空/未配置 → 保持占位（缺省键值即空串）。"""
    set_config(db_session, "contact_email", "ops@example.com")
    assert PLACEHOLDER in effective_user_agent(db_session)


def test_effective_ua_custom_strategy_unaffected(db_session):
    """custom 策略自配串照旧直通（真链接只作用于 honest 模板）。"""
    set_config(db_session, "ua_strategy", "custom")
    set_config(db_session, "ua_custom", "MyFetcher/2.0 (+https://me.example)")
    set_config(db_session, "public_base_url", "https://ignored.example")
    assert effective_user_agent(db_session) == "MyFetcher/2.0 (+https://me.example)"


def test_effective_ua_custom_empty_falls_back_honest_with_url(db_session):
    """custom 空 UA 回退 honest 形态时同样拼真链接（空 UA 是更强的拦截指纹）。"""
    set_config(db_session, "ua_strategy", "custom")
    set_config(db_session, "ua_custom", "   ")
    set_config(db_session, "public_base_url", "https://fallback.example")
    ua = effective_user_agent(db_session)
    assert "+https://fallback.example" in ua
    assert "localhost" not in ua


def test_effective_ua_db_none_placeholder():
    """db=None（honest 无邮箱形态）保持占位。"""
    assert PLACEHOLDER in effective_user_agent(None)
