"""web 通道 429 特判测试（BE-5/RG-4）：与 RSS 面同构拦截——stats.rate_limited
置位 + 不进 error + D13 动态降频消费实证（A5：_update_source_health 档位推进、
Retry-After 解析进 until、不计失败退避）。

通道间待遇一致（P1-2）：同样被限流，RSS 面走降频信号，web 面不再抛
HTTPStatusError 计失败退避。非限流错误路径（500）不回退。
设计依据见 docs/design-index.md「RG-4」（BE-5 增补）。

网络纪律：fake http_client（httpx.Headers 保真大小写不敏感语义），零真出网。
"""
from datetime import datetime, timezone

import httpx
import pytest

import app.ingest.web as web_mod
from app.ingest.web import fetch_web_source
from app.models import Direction, Source
from app.pipeline.runner import _update_source_health


class FakeResponse:
    def __init__(self, *, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = httpx.Headers(headers or {})

    def raise_for_status(self):
        # 与真实 httpx 对齐：≥300 一律抛（304/429 判定必须先于本调用）
        if self.status_code >= 300:
            raise httpx.HTTPStatusError(f"{self.status_code}", request=None,
                                        response=None)  # type: ignore


class FakeClient:
    def __init__(self, response):
        self._response = response

    def get(self, url, headers=None):
        return self._response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHttpClientFactory:
    def __init__(self, response):
        self.response = response
        self.kwargs_log = []

    def __call__(self, db=None, *, timeout=60.0, follow_redirects=True, **kw):
        self.kwargs_log.append({"db": db, "timeout": timeout,
                                "follow_redirects": follow_redirects})
        return FakeClient(self.response)


@pytest.fixture()
def web_source(db_session):
    d = Direction(name="WEB 方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://web.example/page", type="web")
    db_session.add(src)
    db_session.commit()
    return db_session, src


def test_web_429_flags_rate_limited_not_error(web_source, monkeypatch):
    """429 → rate_limited 置位 + retry_after 记头值 + 提前 return 不进 error
    （与 rss.py 429 特判同构——限流交给 D13 动态降频，不计失败退避）。"""
    db, src = web_source
    factory = FakeHttpClientFactory(FakeResponse(
        status_code=429, headers={"Retry-After": "120"}))
    monkeypatch.setattr(web_mod, "http_client", factory)
    stats = fetch_web_source(db, src)
    assert stats.rate_limited is True
    assert stats.retry_after == "120"
    assert stats.error is None
    assert stats.not_modified is False
    assert stats.inserted == 0


def test_web_retry_after_header_without_429_flags(web_source, monkeypatch):
    """限流信号双通道（同 RSS 判例）：非 429 响应携带 Retry-After 头同样命中。"""
    db, src = web_source
    factory = FakeHttpClientFactory(FakeResponse(
        status_code=200, headers={"retry-after": "60"}))
    monkeypatch.setattr(web_mod, "http_client", factory)
    stats = fetch_web_source(db, src)
    assert stats.rate_limited is True
    assert stats.retry_after == "60"


def test_web_500_still_counts_as_error(web_source, monkeypatch):
    """回归：非限流错误（5xx）路径不变——raise_for_status 抛错进 stats.error。"""
    db, src = web_source
    factory = FakeHttpClientFactory(FakeResponse(status_code=500))
    monkeypatch.setattr(web_mod, "http_client", factory)
    stats = fetch_web_source(db, src)
    assert stats.error is not None
    assert stats.rate_limited is False


def test_web_429_feeds_d13_ladder(web_source, monkeypatch):
    """A5 消费实证：web 面 429 的真实 stats 喂 _update_source_health——档位+1、
    until 取 Retry-After 解析值、失败退避不计。"""
    db, src = web_source
    factory = FakeHttpClientFactory(FakeResponse(
        status_code=429, headers={"Retry-After": "120"}))
    monkeypatch.setattr(web_mod, "http_client", factory)
    stats = fetch_web_source(db, src)
    _update_source_health(db, src, stats)
    db.refresh(src)
    assert src.rate_level == 1
    until = src.rate_limited_until
    assert until is not None
    secs = (until if until.tzinfo else until.replace(tzinfo=timezone.utc)) \
        - datetime.now(timezone.utc)
    assert 115 <= secs.total_seconds() <= 120.5  # Retry-After 解析进 until
    assert (src.backoff_failures or 0) == 0  # 不计失败退避


def test_web_429_without_retry_after_uses_ladder_default(web_source, monkeypatch):
    """无 Retry-After 头：until 走 D13 档位缺省间隔（解析失败退档位缺省）。"""
    db, src = web_source
    factory = FakeHttpClientFactory(FakeResponse(status_code=429))
    monkeypatch.setattr(web_mod, "http_client", factory)
    stats = fetch_web_source(db, src)
    assert stats.retry_after is None
    _update_source_health(db, src, stats)
    db.refresh(src)
    assert src.rate_level == 1
    assert src.rate_limited_until is not None
