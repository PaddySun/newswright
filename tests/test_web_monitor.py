"""M9 测试：定点网页监测——变更检测（etag/哈希）、版本 guid、规则/sanitize 接入。"""
import hashlib
from datetime import datetime, timezone

import httpx
import pytest

import app.ingest.web as web
from app.ingest.web import fetch_web_source
from app.models import Direction, Item, Source


HTML_A = "<html><head><title>News A</title></head><body>" + "<p>" + "内容A" * 100 + "</p></body></html>"
HTML_B = "<html><head><title>News A updated</title></head><body>" + "<p>" + "内容B变化" * 100 + "</p></body></html>"


class FakeResp:
    def __init__(self, text, status_code=200, headers=None):
        self.text = text
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"{self.status_code}", request=None, response=None)  # type: ignore


class FakeClient:
    """按序返回预置响应的伪 httpx.Client。"""
    responses: list[FakeResp] = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        return FakeClient.responses.pop(0)


@pytest.fixture()
def web_source(db_session):
    d = Direction(name="DW", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://ex/page", type="web",
                 source_config={"monitor_words": ["关键词X"]})
    db_session.add(src)
    db_session.commit()
    return src


def _patch(monkeypatch, *responses):
    FakeClient.responses = list(responses)
    monkeypatch.setattr("app.ingest.http.httpx.Client", FakeClient)


def test_first_fetch_and_hash_unchanged_skip(db_session, web_source, monkeypatch):
    _patch(monkeypatch, FakeResp(HTML_A), FakeResp(HTML_A), FakeResp(HTML_B))
    # 首抓：change_type=first_fetch，item 带版本 guid
    s1 = fetch_web_source(db_session, web_source)
    assert not s1.not_modified and s1.inserted == 1 and s1.error is None
    assert s1.extra["change_type"] == "first_fetch"
    h1 = hashlib.sha256(HTML_A.encode()).hexdigest()
    it = db_session.query(Item).filter_by(source_id=web_source.id).one()
    assert it.guid == f"https://ex/page#v-{h1[:12]}" and it.sanitize_status == "PASSED"

    # 二轮同内容 → 哈希对比短跳（etag 缺失走 sha256 兜底）
    web_source2 = db_session.merge(web_source)
    s2 = fetch_web_source(db_session, web_source2)
    assert s2.not_modified and s2.inserted == 0

    # 三轮内容变化 → 新版本新条目，旧条目保留（全量保存）
    web_source3 = db_session.merge(web_source)
    s3 = fetch_web_source(db_session, web_source3)
    assert not s3.not_modified and s3.inserted == 1
    assert s3.extra["change_type"] == "content_changed"
    h3 = hashlib.sha256(HTML_B.encode()).hexdigest()
    items = db_session.query(Item).filter_by(source_id=web_source.id).order_by(Item.id).all()
    assert len(items) == 2 and items[1].guid == f"https://ex/page#v-{h3[:12]}"


def test_etag_priority_304_style_skip(db_session, web_source, monkeypatch):
    """服务端返回 etag：二轮带同 etag → 短跳（即使内容字段也变了也不该重复入库）。"""
    _patch(monkeypatch, FakeResp(HTML_A, headers={"ETag": 'W/"v1"'}))
    s1 = fetch_web_source(db_session, web_source)
    assert s1.inserted == 1
    web_source2 = db_session.merge(web_source)
    _patch(monkeypatch, FakeResp(HTML_A, headers={"ETag": 'W/"v1"'}))
    s2 = fetch_web_source(db_session, web_source2)
    assert s2.not_modified and s2.inserted == 0
    assert web_source2.etag == 'W/"v1"'


def test_monitor_words_alert_in_payload(db_session, web_source, monkeypatch):
    html = "<html><head><title>T</title></head><body><p>" + "正文出现关键词X了" * 30 + "</p></body></html>"
    _patch(monkeypatch, FakeResp(html))
    s = fetch_web_source(db_session, db_session.merge(web_source))
    assert s.extra.get("alert_words") == ["关键词X"]


def test_http_error_recorded(db_session, web_source, monkeypatch):
    _patch(monkeypatch, FakeResp("", status_code=500))
    # FakeResp 无 raise_for_status → 直接构造异常路径
    class ErrClient(FakeClient):
        def get(self, url, headers=None):
            raise httpx.HTTPStatusError("500", request=None, response=None)  # type: ignore

    monkeypatch.setattr("app.ingest.http.httpx.Client", ErrClient)
    s = fetch_web_source(db_session, db_session.merge(web_source))
    assert s.error and s.inserted == 0


def test_extract_page_markdown_real():
    """trafilatura 真实抽取（纯代码路径）。"""
    html = "<html><head><title>T</title></head><body><article>" + "<p>这是一段足够长的正文。</p>" * 40 + "</article></body></html>"
    md = web.extract_page_markdown(html)
    assert "足够长" in md


def test_versioned_guid_uses_configured_url_not_redirect_target(db_session, web_source, monkeypatch):
    """监测 guid 的 URL 分量 = 配置 URL 归一化（非重定向最终 URL）——源站改跳转
    策略不得产生双 guid 条目。响应对象携带与配置不同的最终 URL 时，guid 仍以
    配置 URL 构造（响应的 url 属性只出现于真实 httpx 重定向后的对象上）。"""
    class RedirectedResp(FakeResp):
        url = "https://cdn.example/other-path"  # 模拟 follow_redirects 后的最终 URL

    _patch(monkeypatch, RedirectedResp(HTML_A))
    s = fetch_web_source(db_session, web_source)
    assert s.inserted == 1
    it = db_session.query(Item).filter_by(source_id=web_source.id).one()
    assert it.guid.startswith("https://ex/page#v-")
    assert "cdn.example" not in it.guid


def test_rss_style_etag_500_char_not_truncated(db_session, web_source, monkeypatch):
    """etag 列宽 ≥500：接近列宽上限的原样 etag（含引号与 W/ 前缀）完整存取。"""
    long_etag = 'W/"' + "e" * 494 + '"'  # 500 字符整
    _patch(monkeypatch, FakeResp(HTML_A, headers={"ETag": long_etag}))
    s = fetch_web_source(db_session, db_session.merge(web_source))
    assert s.inserted == 1
    src = db_session.merge(web_source)
    assert src.etag == long_etag  # 逐字符保留，未截断/未去引号
