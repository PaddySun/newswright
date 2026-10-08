"""RSS 抓取升级契约测试：出网工厂 db 接线、aware-UTC 时钟取值、首导窗口恰等
边界、摘要富化预采接线、非空列完整性。

覆盖口径（设计依据见 docs/design-index.md「D16」「R9」「AC-04.7」「US-04」）：
- D16 双层口径（2026-10-08 拍板落册）：后端时间取值一律 aware-UTC——模块
  datetime 打桩记录 now() 的 tz 实参，断言全部为 timezone.utc（Windows 无
  tzset 的标签断言等价形态）；
- R9：出网一律经统一工厂（db 实参=UA 策略配置消费）；
- AC-04.7 首导窗口「窗口外」为严格大于：恰 window_days 整为窗内（FETCHED），
  窗外半秒即 ARCHIVED——时钟打桩固定 now 消除微秒漂移；
- US-04 摘要富化预采：enrich_full_text 开启时短条目先抓原文补全再落库——
  富化真实执行（抽取打桩、HTTP 层打桩），自 URL 跳过非终止、(source_id, guid)
  域判定、page_url/db 实参接线均为功能本体；
- fetched_at/fetch_status 非空列完整性（账目 FETCHED 行 fetched_at 恒在）。

网络纪律：fake http_client 返回脚本化 feed/304，不真联网；生产代码零改动。
"""
from datetime import datetime, timedelta, timezone

import pytest

import app.ingest.rss as rss_mod
import app.ingest.web as web_mod
from app.models import Direction, Item, Source

NOW_FIXED = datetime(2026, 10, 8, 4, 0, 0, tzinfo=timezone.utc)
LONG_TEXT = "富化后的完整正文，长度超过短摘要。" * 8


class _UTCProbeDatetime(datetime):
    """记录 now(tz) 实参、行为保真的 datetime 桩。"""

    calls = []

    @classmethod
    def now(cls, tz=None):
        _UTCProbeDatetime.calls.append(tz)
        return datetime.now(tz)


class FixedDatetime(datetime):
    """返回固定 aware 时刻的 datetime 桩（恰等边界消除时钟漂移）。"""

    calls = []

    @classmethod
    def now(cls, tz=None):
        FixedDatetime.calls.append(tz)
        return NOW_FIXED if tz is not None else NOW_FIXED.replace(tzinfo=None)


class FakeResponse:
    def __init__(self, *, status_code=200, content=b"", text="", headers=None):
        self.status_code = status_code
        self.content = content
        self.text = text
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


def _xml(*items: str) -> bytes:
    body = "".join(
        f"<item><title>{t}</title><guid>{g}</guid><link>{link}</link>"
        f"<description>{desc}</description></item>"
        for t, g, link, desc in items)
    return (b"<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>"
            + body.encode("utf-8") + b"</channel></rss>")


@pytest.fixture()
def rss_source(db_session):
    d = Direction(name="RSS 方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://rss.example/feed", type="rss")
    db_session.add(src)
    db_session.commit()
    return db_session, src


def test_fetch_source_wires_db_to_http_factory(rss_source, monkeypatch):
    """304 协商缓存路径同样经统一工厂：db 实参=UA 策略配置消费、时钟 aware-UTC。"""
    db, src = rss_source
    factory = FakeHttpClientFactory(FakeResponse(status_code=304))
    monkeypatch.setattr(rss_mod, "http_client", factory)
    _UTCProbeDatetime.calls = []
    monkeypatch.setattr(rss_mod, "datetime", _UTCProbeDatetime)
    stats = rss_mod.fetch_source(db, src)
    assert stats.not_modified is True
    assert factory.kwargs_log and factory.kwargs_log[0]["db"] is db
    assert all(tz is timezone.utc for tz in _UTCProbeDatetime.calls), \
        "D16：304 快路径的 last_fetched_at 取值同样 aware-UTC"


def test_fetch_source_clock_calls_are_aware_utc(rss_source, monkeypatch):
    """全轮时间取值 aware-UTC（D16）：skipDay 判定/落库/回写各取值点均传 UTC。"""
    db, src = rss_source
    feed_xml = (
        "<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>"
        "<skipdays><day>wednesday</day></skipdays>"
        "<item><title>条目一</title><guid>g-one</guid>"
        "<link>https://rss.example/one</link>"
        "<description>正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。</description></item>"
        "</channel></rss>"
    ).encode("utf-8")
    factory = FakeHttpClientFactory(FakeResponse(content=feed_xml,
                                                 headers={"content-type": "application/xml"}))
    monkeypatch.setattr(rss_mod, "http_client", factory)
    _UTCProbeDatetime.calls = []
    monkeypatch.setattr(rss_mod, "datetime", _UTCProbeDatetime)
    stats = rss_mod.fetch_source(db, src)
    assert stats.inserted == 1
    assert _UTCProbeDatetime.calls, "抓取轮必须产生时间取值"
    assert all(tz is timezone.utc for tz in _UTCProbeDatetime.calls), \
        "D16：后端时间取值一律 aware-UTC（naive 本地时钟为缺陷）"


def test_first_ingest_window_exact_days_is_in(rss_source, monkeypatch):
    """首导窗口恰等边界：恰 7 天条目=窗内 FETCHED（「窗口外」严格大于语义）。"""
    db, src = rss_source
    factory = FakeHttpClientFactory(FakeResponse(content=_xml(
        ("边界条目", "g-edge", "https://rss.example/edge", "边界条目正文，长度足以通过规则初筛。边界条目正文，长度足以通过规则初筛。边界条目正文，长度足以通过规则初筛。边界条目正文，长度足以通过规则初筛。边界条目正文，长度足以通过规则初筛。边界条目正文，长度足以通过规则初筛。边界条目正文，长度足以通过规则初筛。边界条目正文，长度足以通过规则初筛。边界条目正文，长度足以通过规则初筛。边界条目正文，长度足以通过规则初筛。边界条目正文，长度足以通过规则初筛。边界条目正文，长度足以通过规则初筛。")),
        headers={"content-type": "application/xml"}))
    monkeypatch.setattr(rss_mod, "http_client", factory)
    monkeypatch.setattr(rss_mod, "datetime", FixedDatetime)
    monkeypatch.setattr(rss_mod, "_entry_published",
                        lambda entry: NOW_FIXED - timedelta(days=7))
    stats = rss_mod.fetch_source(db, src)
    item = db.query(Item).filter_by(source_id=src.id).one()
    assert item.fetch_status == "FETCHED"


def test_first_ingest_window_half_second_out_is_archived(rss_source, monkeypatch):
    """首导窗口窗外半秒即 ARCHIVED（严格大于的另一半边界）。"""
    db, src = rss_source
    factory = FakeHttpClientFactory(FakeResponse(content=_xml(
        ("窗外条目", "g-out", "https://rss.example/out", "窗外条目正文，长度足以通过规则初筛。窗外条目正文，长度足以通过规则初筛。窗外条目正文，长度足以通过规则初筛。窗外条目正文，长度足以通过规则初筛。窗外条目正文，长度足以通过规则初筛。窗外条目正文，长度足以通过规则初筛。窗外条目正文，长度足以通过规则初筛。窗外条目正文，长度足以通过规则初筛。窗外条目正文，长度足以通过规则初筛。窗外条目正文，长度足以通过规则初筛。窗外条目正文，长度足以通过规则初筛。窗外条目正文，长度足以通过规则初筛。")),
        headers={"content-type": "application/xml"}))
    monkeypatch.setattr(rss_mod, "http_client", factory)
    monkeypatch.setattr(rss_mod, "datetime", FixedDatetime)
    monkeypatch.setattr(rss_mod, "_entry_published",
                        lambda entry: NOW_FIXED - timedelta(days=7, seconds=0.5))
    stats = rss_mod.fetch_source(db, src)
    item = db.query(Item).filter_by(source_id=src.id).one()
    assert item.fetch_status == "ARCHIVED"


def test_fetch_status_and_fetched_at_never_null(rss_source, monkeypatch):
    """两轮抓取（首导+非首导）规则通过条目：fetch_status/fetched_at 非空落库。"""
    db, src = rss_source
    factory = FakeHttpClientFactory(FakeResponse(content=_xml(
        ("条目一", "g-one", "https://rss.example/one", "正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。正文内容足够长，用于通过最小长度规则判定。")),
        headers={"content-type": "application/xml"}))
    monkeypatch.setattr(rss_mod, "http_client", factory)
    stats = rss_mod.fetch_source(db, src)   # 首导轮
    stats2 = rss_mod.fetch_source(db, src)  # 非首导轮（dup_blocked）
    assert stats.failed == 0 and stats2.failed == 0
    item = db.query(Item).filter_by(source_id=src.id).one()
    assert item.fetch_status == "FETCHED"
    assert item.fetched_at is not None


def test_enrich_preflight_real_run(rss_source, monkeypatch):
    """富化预采真实执行：自 URL 跳过非终止，后续短条目被富化、db 接线正确。"""
    db, src = rss_source
    src.source_config = {"enrich_full_text": True}
    db.commit()
    feed = _xml(
        ("自引用", "self", "https://rss.example/feed", "短"),
        ("短条目二", "short2", "https://other.example/two", "短"),
        ("短条目三", "short3", "https://other.example/three", "短"),
    )
    factory = FakeHttpClientFactory(FakeResponse(content=feed,
                                                 headers={"content-type": "application/xml"}))
    monkeypatch.setattr(rss_mod, "http_client", factory)
    web_factory = FakeHttpClientFactory(FakeResponse(
        text="<html><body>page</body></html>"))
    monkeypatch.setattr(web_mod, "http_client", web_factory)
    monkeypatch.setattr(web_mod, "extract_page_markdown", lambda html: LONG_TEXT)
    stats = rss_mod.fetch_source(db, src)
    assert web_factory.kwargs_log, "短条目必须触发富化抓取"
    assert web_factory.kwargs_log[0]["db"] is db
    # 自 URL 条目保持原文（短、走 too_short 拒绝），跨源条目富化生效
    by_guid = {i.guid: i for i in db.query(Item).filter_by(source_id=src.id)}
    assert by_guid["self"].content_text == "短"
    assert by_guid["short2"].content_text == LONG_TEXT
    assert by_guid["short3"].content_text == LONG_TEXT


def test_enrich_preflight_scope_is_per_source(rss_source, monkeypatch):
    """富化已入库判定按 (source_id, guid)：他源同 guid 条目不得误判跳过。"""
    db, src = rss_source
    other_dir = Direction(name="其他方向", prompt="p", threshold=60)
    db.add(other_dir)
    db.commit()
    other_src = Source(direction_id=other_dir.id, url="https://elsewhere.example/f",
                       type="rss")
    db.add(other_src)
    db.commit()
    db.add(Item(source_id=other_src.id, guid="dup-guid",
                url="https://elsewhere.example/1", title="他源同 guid",
                content_text="他源正文", fetch_status="FETCHED",
                direction_id=other_dir.id))
    db.commit()
    src.source_config = {"enrich_full_text": True}
    db.commit()
    factory = FakeHttpClientFactory(FakeResponse(content=_xml(
        ("本源新条目", "dup-guid", "https://rss.example/dup", "短")),
        headers={"content-type": "application/xml"}))
    monkeypatch.setattr(rss_mod, "http_client", factory)
    enrich_log = []

    def fake_enrich(url, current_text, *, page_url, db=None):
        enrich_log.append(url)
        return LONG_TEXT

    monkeypatch.setattr(web_mod, "enrich_entry_text", fake_enrich)
    stats = rss_mod.fetch_source(db, src)
    assert len(enrich_log) == 1, "他源同 guid 不得阻断本源新条目的富化"
