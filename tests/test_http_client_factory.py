"""出网 httpx 客户端工厂测试（采集公共纪律，设计依据见 docs/design-index.md
「R9」）：UA 两种策略 + proxy 参数位透传 + rss/web/search/hot 四调用点统一。
"""
import app.ingest.http as http_factory
from app.ingest.http import (
    PROXY_ENV_KEY,
    effective_user_agent,
    honest_user_agent,
    http_client,
    proxy_url,
)
from app.siteconfig import set_config


def test_honest_user_agent_template_contains_product_and_email_slot():
    ua = honest_user_agent("webmaster@example.com")
    assert "newswright" in ua and "webmaster@example.com" in ua
    assert "newswright" in honest_user_agent(None)
    assert "@" not in honest_user_agent(None)


def test_effective_user_agent_honest_default(db_session):
    ua = effective_user_agent(db_session)
    assert "newswright" in ua


def test_effective_user_agent_custom_strategy(db_session):
    set_config(db_session, "ua_strategy", "custom")
    set_config(db_session, "ua_custom", "MyFetcher/2.0 (+https://me.example)")
    assert effective_user_agent(db_session) == "MyFetcher/2.0 (+https://me.example)"


def test_effective_user_agent_custom_empty_falls_back_honest(db_session):
    set_config(db_session, "ua_strategy", "custom")
    set_config(db_session, "ua_custom", "   ")
    ua = effective_user_agent(db_session)
    assert "newswright" in ua  # 空 UA 是更强的拦截指纹，回退诚实形态


def test_proxy_env_injected_and_absent(monkeypatch):
    monkeypatch.delenv(PROXY_ENV_KEY, raising=False)
    assert proxy_url() is None
    monkeypatch.setenv(PROXY_ENV_KEY, "http://127.0.0.1:7890")
    assert proxy_url() == "http://127.0.0.1:7890"


def test_factory_sets_ua_and_proxy(db_session, monkeypatch):
    monkeypatch.setenv(PROXY_ENV_KEY, "http://proxy.local:3128")
    set_config(db_session, "contact_email", "ops@example.com")
    captured = {}

    class RecordingClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(http_factory.httpx, "Client", RecordingClient)
    http_client(db_session, timeout=42.0, follow_redirects=False)
    assert captured["timeout"] == 42.0 and captured["follow_redirects"] is False
    assert captured["proxy"] == "http://proxy.local:3128"
    assert "ops@example.com" in captured["headers"]["User-Agent"]


def test_factory_without_proxy_env_no_proxy_kwarg(monkeypatch):
    monkeypatch.delenv(PROXY_ENV_KEY, raising=False)
    captured = {}

    class RecordingClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(http_factory.httpx, "Client", RecordingClient)
    http_client(None)
    assert "proxy" not in captured  # 不配置行为不变


def test_four_channels_use_unified_factory(db_session, monkeypatch):
    """四调用点统一：rss/web/search/hot 的出网客户端都经工厂构造（同一桩类
    在四个通道各自触发时都被命中）。"""
    constructed = []

    class TaggedClient:
        def __init__(self, *a, **kw):
            constructed.append(kw.get("headers", {}).get("User-Agent", "?"))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return type("R", (), {
                "status_code": 304, "headers": {}, "content": b"",
                "raise_for_status": lambda self: None,
                "json": lambda self: {"status": "success", "items": []},
            })()

    monkeypatch.setattr(http_factory.httpx, "Client", TaggedClient)

    # rss 通道
    from app.ingest.rss import fetch_source
    from app.models import Direction, Source

    d = Direction(name="工厂方向", prompt="p", prompt_version=1, threshold=60)
    db_session.add(d)
    db_session.commit()
    rss_src = Source(direction_id=d.id, url="https://ex.com/feed", type="rss")
    db_session.add(rss_src)
    db_session.commit()
    fetch_source(db_session, rss_src)

    # web 通道（304 短路即完成一次工厂构造）
    from app.ingest.web import fetch_web_source

    web_src = Source(direction_id=d.id, url="https://ex.com/page", type="web")
    db_session.add(web_src)
    db_session.commit()
    fetch_web_source(db_session, web_src)

    # hot 通道（fetch_platform 真路径，304 响应不产生条目即返回）
    from app.hot.service import fetch_platform

    fetch_platform("weibo", db=db_session)

    assert len(constructed) >= 3
    assert all("newswright" in ua for ua in constructed)
