"""RSS 抓取加固测试：内容嗅探 / bytes-only 喂给 / etag 原样存取。

条款依据：产品书/技术书 RSS 经验增补（内容嗅探：HTTP 200 但响应非 XML → 判
non_xml_response 走失败列、不喂解析器；feedparser 只喂 bytes——编码由 XML 声明
嗅探，httpx 先解码会污染中文源；etag 原样存取，含引号与 W/ 前缀，截断会让
304 永不命中）。设计依据见 docs/design-index.md「B1」「B2」「B7」。
"""
import httpx
import pytest

import app.ingest.rss as rss_mod
from app.ingest.rss import fetch_source, parse_feed_entries
from app.models import Direction, Source


class FakeResp:
    def __init__(self, content, status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"{self.status_code}", request=None, response=None)  # type: ignore


class FakeClient:
    """按序返回预置响应的伪 httpx.Client；记录每次请求头（If-None-Match 断言用）。"""
    responses: list[FakeResp] = []
    sent_headers: list[dict] = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        type(self).sent_headers.append(dict(headers or {}))
        return type(self).responses.pop(0)


@pytest.fixture()
def rss_direction(db_session):
    d = Direction(name="RSS 加固方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://feeds.example/hard.xml", type="rss")
    db_session.add(src)
    db_session.commit()
    return src


def _patch(monkeypatch, *responses):
    FakeClient.responses = list(responses)
    FakeClient.sent_headers = []
    monkeypatch.setattr(rss_mod.httpx, "Client", FakeClient)


_HTML_CHALLENGE = b"<html><head><title>Just a moment...</title></head><body>challenge</body></html>"

_VALID_FEED = ("""<?xml version="1.0"?>
<rss version="2.0"><channel><title>t</title>
  <item><guid>https://ex.com/1</guid><link>https://ex.com/1</link>
  <title>Valid</title><description>正文足够长以通过规则初筛的字节序列。</description></item>
</channel></rss>""").encode("utf-8")


def test_http_200_html_challenge_rejected_as_non_xml(db_session, rss_direction, monkeypatch):
    """HTTP 200 + HTML 挑战页：判 non_xml_response 走失败列，不喂解析器、
    不落条目、不回写协商缓存头（挑战页 etag 会污染后续 304 判定）。"""
    _patch(monkeypatch, FakeResp(_HTML_CHALLENGE, headers={"ETag": '"challenge-etag"'}))
    stats = fetch_source(db_session, db_session.merge(rss_direction))
    assert stats.error is not None and stats.error.startswith("non_xml_response")
    assert stats.feed_entries == 0 and stats.inserted == 0
    src = db_session.merge(rss_direction)
    assert src.etag is None  # 协商缓存头不回写


def test_http_200_html_without_content_type_rejected(db_session, rss_direction, monkeypatch):
    """HTML 响应体且无 Content-Type 声明：同样判 non_xml_response（内容级嗅探兜底）。"""
    _patch(monkeypatch, FakeResp(_HTML_CHALLENGE, headers={}))
    stats = fetch_source(db_session, db_session.merge(rss_direction))
    assert stats.error is not None and stats.error.startswith("non_xml_response")


def test_xml_body_with_unusual_content_type_accepted(db_session, rss_direction, monkeypatch):
    """正文是合法 XML 但 Content-Type 声明异常（部分源站配置错误）：内容级嗅探
    命中即放行，不得因头部声明 alone 误杀真实 feed。"""
    _patch(monkeypatch, FakeResp(_VALID_FEED, headers={"Content-Type": "application/octet-stream"}))
    stats = fetch_source(db_session, db_session.merge(rss_direction))
    assert stats.error is None and stats.inserted == 1


def test_parse_feed_entries_bytes_gbk_encoding():
    """bytes-only：GBK 编码 feed（XML 声明带 encoding）按声明正确解码——
    若上游先 .text 解码再喂入，中文会被错误编码污染。"""
    xml = ('<?xml version="1.0" encoding="gbk"?>'
           '<rss version="2.0"><channel><title>t</title>'
           "<item><guid>https://ex.com/gbk</guid><link>https://ex.com/gbk</link>"
           "<title>中文标题测试</title>"
           "<description>这是足够长的中文正文内容，用于通过规则初筛的字数要求。</description>"
           "</item></channel></rss>").encode("gbk")
    entries = parse_feed_entries(xml)
    assert len(entries) == 1
    assert entries[0].title == "中文标题测试"
    assert "中文正文内容" in entries[0].content_text


def test_fetch_source_never_touches_response_text(db_session, rss_direction, monkeypatch):
    """护栏：抓取路径只喂 bytes（resp.content）——响应对象不带 .text 属性时
    全流程仍可用（一旦代码触碰 .text 即 AttributeError 爆红）。"""
    class BytesOnlyResp(FakeResp):
        @property
        def text(self):  # 故意保留属性但访问即爆红，覆盖"必须不触碰"语义
            raise AssertionError("抓取路径不得触碰 resp.text（bytes-only 纪律）")

    _patch(monkeypatch, BytesOnlyResp(_VALID_FEED))
    stats = fetch_source(db_session, db_session.merge(rss_direction))
    assert stats.error is None and stats.inserted == 1


def test_rss_etag_stored_verbatim_and_sent_back(db_session, rss_direction, monkeypatch):
    """etag 原样存取：含引号与 W/ 前缀逐字符保留；二轮请求 If-None-Match 原样回传
    （截断/去引号会让 304 永不命中）。"""
    etag = 'W/"abc-123-long-etag-value"'
    _patch(monkeypatch, FakeResp(_VALID_FEED, headers={"ETag": etag}))
    stats = fetch_source(db_session, db_session.merge(rss_direction))
    assert stats.error is None
    src = db_session.merge(rss_direction)
    assert src.etag == etag

    _patch(monkeypatch, FakeResp(b"", status_code=304, headers={}))
    fetch_source(db_session, db_session.merge(src))
    assert FakeClient.sent_headers[-1].get("If-None-Match") == etag
