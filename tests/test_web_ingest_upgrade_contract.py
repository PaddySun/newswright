"""定点网页监测升级契约测试：出网工厂 db 接线、aware-UTC 时钟取值、非空列
完整性、富化函数护栏（协议前缀/同页护栏/更长才采用）。

覆盖口径（设计依据见 docs/design-index.md「D16」「R9」「AC-05.1」「能力②」）：
- D16 双层口径：后端时间取值一律 aware-UTC（304 快路径/not_modified 路径/
  条目落库/轮末回写各取值点）；
- R9：单页与富化出网均经统一工厂（db 实参=UA 策略配置消费）；
- 富化护栏（模块 docstring 钉）：仅 http(s) 条目富化；条目 URL=页面 URL 不
  富化（抓回同内容无增量）；全文比现文本更长才采用；
- fetched_at/fetch_status 非空列完整性。

网络纪律：fake http_client 返回脚本化响应，不真联网；生产代码零改动。
"""
from datetime import datetime, timezone

import pytest

import app.ingest.web as web_mod
from app.ingest.web import enrich_entry_text, fetch_web_source
from app.models import Direction, Item, Source

NOW_FIXED = datetime(2026, 10, 8, 4, 0, 0, tzinfo=timezone.utc)
LONG_TEXT = "富化后的完整正文，长度超过短摘要。" * 8


class _UTCProbeDatetime(datetime):
    calls = []

    @classmethod
    def now(cls, tz=None):
        _UTCProbeDatetime.calls.append(tz)
        return datetime.now(tz)


class FakeResponse:
    def __init__(self, *, status_code=200, text="", content=b"", headers=None):
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, response, log):
        self._response = response
        self.log = log

    def get(self, url, headers=None):
        self.log.append({"url": url, "headers": headers})
        return self._response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHttpClientFactory:
    def __init__(self, response):
        self.response = response
        self.kwargs_log = []
        self.gets = []

    def __call__(self, db=None, *, timeout=60.0, follow_redirects=True, **kw):
        self.kwargs_log.append({"db": db, "timeout": timeout,
                                "follow_redirects": follow_redirects})
        return FakeClient(self.response, self.gets)


PAGE_HTML = "<html><head><title>监测页</title></head><body>页面正文内容。</body></html>"


@pytest.fixture()
def web_source(db_session):
    d = Direction(name="WEB 方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://web.example/page", type="web")
    db_session.add(src)
    db_session.commit()
    return db_session, src


def test_fetch_web_source_wires_db_on_304(web_source, monkeypatch):
    """304 快路径经统一工厂：db 实参=UA 策略配置消费、时钟 aware-UTC（D16）。"""
    db, src = web_source
    factory = FakeHttpClientFactory(FakeResponse(status_code=304))
    monkeypatch.setattr(web_mod, "http_client", factory)
    _UTCProbeDatetime.calls = []
    monkeypatch.setattr(web_mod, "datetime", _UTCProbeDatetime)
    stats = fetch_web_source(db, src)
    assert stats.not_modified is True
    assert factory.kwargs_log and factory.kwargs_log[0]["db"] is db
    assert all(tz is timezone.utc for tz in _UTCProbeDatetime.calls), \
        "D16：304 快路径的 last_fetched_at 取值同样 aware-UTC"


def test_fetch_web_source_clock_calls_are_aware_utc(web_source, monkeypatch):
    """not_modified（etag 未变）与正常变更轮的时间取值均 aware-UTC（D16）。"""
    db, src = web_source
    factory = FakeHttpClientFactory(FakeResponse(
        text=PAGE_HTML, headers={"etag": '"v1"'}))
    monkeypatch.setattr(web_mod, "http_client", factory)
    monkeypatch.setattr(web_mod, "extract_page_markdown", lambda html: "监测页正文内容，长度足以通过规则初筛。" * 12)
    monkeypatch.setattr(web_mod, "_published_date", lambda html: None)
    # 第一轮：首抓落库（变更轮）；第二轮：etag 相同→not_modified 路径
    _UTCProbeDatetime.calls = []
    monkeypatch.setattr(web_mod, "datetime", _UTCProbeDatetime)
    stats = fetch_web_source(db, src)
    assert stats.inserted == 1
    stats2 = fetch_web_source(db, src)
    assert stats2.not_modified is True
    assert _UTCProbeDatetime.calls
    assert all(tz is timezone.utc for tz in _UTCProbeDatetime.calls), \
        "D16：后端时间取值一律 aware-UTC（naive 本地时钟为缺陷）"


def test_single_page_item_integrity(web_source, monkeypatch):
    """单页条目 fetched_at/fetch_status 非空落库（非空列完整性）。"""
    db, src = web_source
    factory = FakeHttpClientFactory(FakeResponse(
        text=PAGE_HTML, headers={"etag": '"v1"'}))
    monkeypatch.setattr(web_mod, "http_client", factory)
    monkeypatch.setattr(web_mod, "extract_page_markdown", lambda html: "监测页正文内容，长度足以通过规则初筛。" * 12)
    monkeypatch.setattr(web_mod, "_published_date", lambda html: None)
    stats = fetch_web_source(db, src)
    assert stats.failed == 0
    item = db.query(Item).filter_by(source_id=src.id).one()
    assert item.fetch_status == "FETCHED"
    assert item.fetched_at is not None


def test_enrich_real_run_https(web_source, monkeypatch):
    """https 条目富化真实执行：db 接线、显式有限超时与跟随语义、更长全文被采用。"""
    db, src = web_source
    web_factory = FakeHttpClientFactory(FakeResponse(text="<html>full</html>"))
    monkeypatch.setattr(web_mod, "http_client", web_factory)

    def fake_extract(html):
        assert html is not None and html.strip(), "抽取实参必须为真实响应体"
        return LONG_TEXT

    monkeypatch.setattr(web_mod, "extract_page_markdown", fake_extract)
    out = enrich_entry_text("https://full.example/article", "短摘要",
                            page_url="https://web.example/page", db=db)
    assert out == LONG_TEXT
    call = web_factory.kwargs_log[0]
    assert call["db"] is db
    assert isinstance(call["timeout"], (int, float))  # §4.2 显式有限超时
    assert call["follow_redirects"] is True
    assert web_factory.gets[0]["url"] == "https://full.example/article"


def test_enrich_real_run_http(web_source, monkeypatch):
    """http 条目同样在富化域内（协议前缀判定同时覆盖两种 scheme）。"""
    db, src = web_source
    web_factory = FakeHttpClientFactory(FakeResponse(text="<html>full</html>"))
    monkeypatch.setattr(web_mod, "http_client", web_factory)
    monkeypatch.setattr(web_mod, "extract_page_markdown", lambda html: LONG_TEXT)
    out = enrich_entry_text("http://full.example/article", "短摘要",
                            page_url="https://web.example/page", db=db)
    assert out == LONG_TEXT


def test_enrich_same_page_url_guard(web_source, monkeypatch):
    """条目 URL=页面 URL 不富化（护栏：抓回同一内容无增量）。"""
    db, src = web_source
    web_factory = FakeHttpClientFactory(FakeResponse(text="<html>same</html>"))
    monkeypatch.setattr(web_mod, "http_client", web_factory)
    monkeypatch.setattr(web_mod, "extract_page_markdown", lambda html: LONG_TEXT)
    out = enrich_entry_text("https://web.example/page", "短摘要",
                            page_url="https://web.example/page", db=db)
    assert out == "短摘要"
    assert web_factory.gets == []  # 未发起任何抓取


def test_enrich_equal_length_keeps_original(web_source, monkeypatch):
    """等长文本不采用（「更长才采用」）：原文保留。"""
    db, src = web_source
    web_factory = FakeHttpClientFactory(FakeResponse(text="<html>eq</html>"))
    monkeypatch.setattr(web_mod, "http_client", web_factory)
    monkeypatch.setattr(web_mod, "extract_page_markdown",
                        lambda html: "X" * len("Y" * 30))
    original = "Y" * 30
    out = enrich_entry_text("https://full.example/a", original,
                            page_url="https://web.example/page", db=db)
    assert out == original


def test_llm_extract_entries_enrich_wires_db(web_source, monkeypatch):
    """列表页 LLM 抽取路径：过短条目经富化补全——富化出网携带请求级会话（R9）。"""
    db, src = web_source
    src.source_config = {"llm_extract": True}
    db.commit()
    factory = FakeHttpClientFactory(FakeResponse(
        text=PAGE_HTML, headers={"etag": '"v1"'}))
    monkeypatch.setattr(web_mod, "http_client", factory)
    monkeypatch.setattr(web_mod, "extract_page_markdown", lambda html: LONG_TEXT)
    monkeypatch.setattr(web_mod, "_published_date", lambda html: None)
    entry = {"title": "列表条目一", "url": "https://entry.example/one",
             "summary": "短", "date": ""}
    monkeypatch.setattr(web_mod, "llm_extract_entries",
                        lambda db, **kw: [web_mod.WebPayload(
                            guid="e1", url="https://entry.example/one",
                            title="列表条目一", published_at=None,
                            content_text="短")])
    stats = fetch_web_source(db, src)
    assert stats.feed_entries == 1
    assert len(factory.kwargs_log) >= 2, "主抓取+富化两次出网工厂调用"
    assert all(c["db"] is db for c in factory.kwargs_log),         "R9：主抓取与富化出网均携带请求级会话（UA 策略配置消费）"
    item = db.query(Item).filter_by(source_id=src.id).one()
    assert item.content_text == LONG_TEXT  # 富化生效（短摘要被补全）
