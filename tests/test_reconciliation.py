"""采集账目等式测试：每源 feed_entries = inserted + dup_blocked + rule_rejected
+ failed + archived，无静默缺条；分桶口径写死。

口径：inserted = 实际落 item 表的行（含 DUP 行）；dup_blocked = (source_id,guid)
唯一约束拦截及同一 feed 内重复 guid（均不落行）；failed = 抓取异常（不落行仅
payload 计数）；rule_rejected / archived = 落行状态。
设计依据见 docs/design-index.md「AC-05.1」。
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import app.ingest.rss as rss_mod
from app.ingest.rss import fetch_source
from app.models import Direction, Item, Source


class FakeResp:
    def __init__(self, content, status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})
        self.text = (content.decode("utf-8", errors="replace")
                     if isinstance(content, bytes) else str(content))

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"{self.status_code}", request=None, response=None)  # type: ignore


class FakeClient:
    responses: list[FakeResp] = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        return type(self).responses.pop(0)


_LONG = "正文足够长以通过规则初筛。" * 30


def _item(guid: str, title: str, *, body: str = _LONG, days_old: float | None = None,
          link: str | None = None) -> str:
    link = link or f"https://ex.com/{guid}"
    pub = ("" if days_old is None else
           f"<pubDate>{(datetime.now(timezone.utc) - timedelta(days=days_old)).strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>")
    return (f"<item><guid>{guid}</guid><link>{link}</link>"
            f"<title>{title}</title>{pub}<description>{body}</description></item>")


def _feed(*items: str) -> bytes:
    return (f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>t</title>{''.join(items)}
    </channel></rss>""").encode()


@pytest.fixture()
def source(db_session):
    from app.models import Direction

    d = db_session.query(Direction).filter_by(name="账目方向").one_or_none()
    if d is None:
        d = Direction(name="账目方向", prompt="p", threshold=60)
        db_session.add(d)
        db_session.commit()
    src = Source(direction_id=d.id, url="https://feeds.example/ledger.xml", type="rss",
                 source_config={"first_ingest_days": 1})
    db_session.add(src)
    db_session.commit()
    return src


def _fetch(db_session, monkeypatch, src, feed: bytes):
    FakeClient.responses = [FakeResp(feed)]
    monkeypatch.setattr("app.ingest.http.httpx.Client", FakeClient)
    return fetch_source(db_session, src)


def _assert_balanced(stats) -> None:
    assert stats.feed_entries == (stats.inserted + stats.dup_blocked
                                  + stats.rule_rejected + stats.failed + stats.archived)


def test_buckets_balanced_full_mixture(db_session, source, monkeypatch):
    """混合场景账目平衡：首导轮含窗口归档 1、垃圾拒绝 1、新入库 2（其一为 DUP 行）、
    同 feed 重复 guid 拦截 1。（guid 用非 URL 形态：feedparser 会把 permalink 型
    guid 当 base 解析相对 link，URL 型 guid+同值 link 的组合会被拼接改写。）"""
    feed = _feed(
        _item("g-a", "正常入库", days_old=0.1),
        _item("g-b", "窗口外归档", days_old=400),
        _item("g-c", "过短垃圾", body="太短", days_old=0.1),
        _item("g-d", "同文跨源", link="https://ex.com/g-a", days_old=0.1),
        _item("g-a", "feed 内重复 guid", days_old=0.1),
    )
    stats = _fetch(db_session, monkeypatch, source, feed)
    assert stats.feed_entries == 5
    assert stats.archived == 1 and stats.rule_rejected == 1
    assert stats.dup_blocked == 1  # feed 内重复 guid（不落行）
    # DUP 行落库计入 inserted（另一条为窗口外归档前先落库的正常行 + DUP 行）
    dup_rows = db_session.query(Item).filter_by(source_id=source.id,
                                                fetch_status="DUP").all()
    assert len(dup_rows) == 1 and dup_rows[0].duplicate_of is not None
    _assert_balanced(stats)


def test_dup_rows_counted_in_inserted(db_session, source, monkeypatch):
    """分桶口径：DUP 语义近重复行计入 inserted（实际落 item 表的行）。"""
    # 预置同方向另一源已有一条同 URL 指纹条目 → 新源条目判 DUP 落行
    from app.ingest.fingerprint import url_fingerprint

    d2 = Source(direction_id=source.direction_id, url="https://feeds.example/other.xml",
                type="rss")
    db_session.add(d2)
    db_session.commit()
    fp = url_fingerprint("https://ex.com/shared")
    db_session.add(Item(source_id=d2.id, guid="o1", url="https://ex.com/shared",
                        title="Origin", content_text=_LONG, fetch_status="FETCHED",
                        direction_id=source.direction_id, fingerprint=fp))
    db_session.commit()

    stats = _fetch(db_session, monkeypatch, source,
                   _feed(_item("https://ex.com/shared?utm_source=x", "重复条目")))
    assert stats.inserted == 1 and stats.dup_blocked == 0  # DUP 行在 inserted 桶
    _assert_balanced(stats)


def test_failed_no_row_counts_in_payload(db_session, source, monkeypatch):
    """failed = 抓取异常（不落行仅 payload 计数）：等式仍平衡、该条目无行。"""
    original_sanitize = rss_mod.run_sanitize

    def flaky_sanitize(target):
        if "boom" in (target.title or ""):
            raise RuntimeError("模拟单条入库异常")
        return original_sanitize(target)

    monkeypatch.setattr(rss_mod, "run_sanitize", flaky_sanitize)
    stats = _fetch(db_session, monkeypatch, source, _feed(
        _item("https://ex.com/ok-1", "正常条目", days_old=0.1),
        _item("https://ex.com/boom", "boom 条目", days_old=0.1),
    ))
    assert stats.failed == 1
    assert db_session.query(Item).filter_by(source_id=source.id,
                                            guid="https://ex.com/boom").one_or_none() is None
    _assert_balanced(stats)


def test_fetch_error_round_balances_trivially(db_session, source, monkeypatch):
    """整源抓取失败轮：feed_entries=0 且无任何落库，等式平凡成立（不静默缺条）。"""
    class ErrClient(FakeClient):
        def get(self, url, headers=None):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.ingest.http.httpx.Client", ErrClient)
    stats = fetch_source(db_session, source)
    assert stats.error is not None and stats.feed_entries == 0
    _assert_balanced(stats)


def test_search_channel_attribution_ledger(db_session, source, monkeypatch):
    """搜索归因：条目带 source_keyword，同源按关键词可聚合（逐词新增率数据面）。"""
    import app.search.pipeline as search_pipeline
    import app.search.registry as registry
    from app.search.base import SearchResult

    d_kw = Source(direction_id=source.direction_id, url="search://fakeprov/词甲",
                  type="search", source_config={"keyword": "词甲", "provider": "fakeprov"})
    db_session.add(d_kw)
    db_session.commit()
    results = [SearchResult(title=f"r{i}", url=f"https://ex.com/kw/{i}",
                            snippet="摘要" * 150, content="全文" * 200,
                            published_at=None, raw={}) for i in range(2)]
    monkeypatch.setattr(registry, "get_provider", lambda name, db=None: type("P", (), {
        "name": name, "search": lambda self, q, count=10, **kw: results})())
    stats = search_pipeline.fetch_search_source(db_session, d_kw)
    assert stats.inserted == 2
    rows = db_session.query(Item).filter_by(source_id=d_kw.id).all()
    assert all(it.source_keyword == "词甲" for it in rows)


# ---------- F2 增补：web / search 通道账目等式（与 RSS 同式同口径） ----------

def _web_html(title: str, body: str) -> str:
    return (f"<!DOCTYPE html><html><head><title>{title}</title></head><body>"
            f"<article><p>{body}</p></article></body></html>")


def _fetch_web(db_session, monkeypatch, src, html: str):
    import app.ingest.web as web_mod

    FakeClient.responses = [FakeResp(html.encode())]
    monkeypatch.setattr("app.ingest.http.httpx.Client", FakeClient)
    return web_mod.fetch_web_source(db_session, src)


@pytest.fixture()
def web_source(db_session, source):
    from app.models import Direction

    d = db_session.get(Direction, source.direction_id)
    return Source(direction_id=d.id, url="https://monitor.example/page",
                  type="web")


def test_web_channel_equation_single_page(db_session, monkeypatch, web_source):
    """单页监测：监测页即一个条目位——首抓 1 页 1 落行，等式平衡。"""
    db_session.add(web_source)
    db_session.commit()
    stats = _fetch_web(db_session, monkeypatch, web_source,
                       _web_html("页面标题", "正文内容足够长。" * 60))
    assert stats.feed_entries == 1
    assert stats.inserted == 1
    _assert_balanced(stats)


def test_web_channel_equation_llm_mixture(db_session, monkeypatch, web_source):
    """列表页抽取混合景：3 条目 = 1 新入库 + 1 同批重复 guid 拦截（不落行）
    + 1 过短规则拒绝（落行单列）——等式平衡。"""
    import app.ingest.web as web_mod
    from app.ingest.web import WebPayload

    db_session.add(web_source)
    db_session.commit()
    now = datetime.now(timezone.utc)

    def fake_entries(db, *, page_url, content_text, extraction_prompt):
        return [
            WebPayload(guid="https://ex.com/e1", url="https://ex.com/e1",
                       title="正常条目", published_at=now, content_text=_LONG),
            WebPayload(guid="https://ex.com/e1", url="https://ex.com/e1",
                       title="同批重复", published_at=now, content_text=_LONG),
            WebPayload(guid="https://ex.com/e2", url="https://ex.com/e2",
                       title="过短条目", published_at=now, content_text="太短"),
        ]

    monkeypatch.setattr(web_mod, "llm_extract_entries", fake_entries)
    web_source.source_config = {"llm_extract": True}
    stats = _fetch_web(db_session, monkeypatch, web_source,
                       _web_html("列表页", "页面正文" * 60))
    assert stats.feed_entries == 3
    assert stats.inserted == 1 and stats.dup_blocked == 1 and stats.rule_rejected == 1
    _assert_balanced(stats)


def test_web_channel_equation_extract_failure(db_session, monkeypatch, web_source):
    """抽取失败景：拉回 1 页 0 落行 1 失败（监测页本身算一个条目位），等式平衡。"""
    import app.ingest.web as web_mod

    db_session.add(web_source)
    db_session.commit()
    monkeypatch.setattr(web_mod, "llm_extract_entries",
                        lambda db, **kw: None)
    web_source.source_config = {"llm_extract": True}
    stats = _fetch_web(db_session, monkeypatch, web_source,
                       _web_html("列表页", "页面正文" * 60))
    assert stats.failed == 1 and stats.error is not None
    _assert_balanced(stats)


def test_search_channel_equation(db_session, monkeypatch, source):
    """搜索通道混合景：5 结果 = 2 新入库 + 1 已存在 guid 拦截（不落行）
    + 1 无效 URL 拦截（不落行）+ 1 过短规则拒绝（落行单列）——等式平衡。"""
    import app.search.pipeline as search_pipeline
    import app.search.registry as registry
    from app.search.base import SearchResult

    d_kw = Source(direction_id=source.direction_id, url="search://equ/等式词",
                  type="search", source_config={"keyword": "等式词", "provider": "fakeprov"})
    db_session.add(d_kw)
    db_session.commit()
    # 预置已存在 guid：https://ex.com/eq/0 的归一化形态
    db_session.add(Item(source_id=d_kw.id, guid="https://ex.com/eq/0",
                        title="已存在", content_text=_LONG,
                        fetched_at=datetime.now(timezone.utc)))
    db_session.commit()
    results = [
        SearchResult(title="已入库", url="https://ex.com/eq/0",
                     snippet=_LONG, content=_LONG, published_at=None, raw={}),
        SearchResult(title="无效URL", url="",
                     snippet=_LONG, content=_LONG, published_at=None, raw={}),
        SearchResult(title="过短", url="https://ex.com/eq/2",
                     snippet="短", content="短", published_at=None, raw={}),
        SearchResult(title="新1", url="https://ex.com/eq/3",
                     snippet=_LONG, content=_LONG, published_at=None, raw={}),
        SearchResult(title="新2", url="https://ex.com/eq/4",
                     snippet=_LONG, content=_LONG, published_at=None, raw={}),
    ]
    monkeypatch.setattr(registry, "get_provider", lambda name, db=None: type("P", (), {
        "name": name, "search": lambda self, q, count=10, **kw: results})())
    stats = search_pipeline.fetch_search_source(db_session, d_kw)
    assert stats.feed_entries == 5
    assert stats.inserted == 2 and stats.dup_blocked == 2 and stats.rule_rejected == 1
    # 拒绝行已落库但计入 rule_rejected 桶（inserted 不含拒绝行——与 RSS 同式）
    rejected = db_session.query(Item).filter_by(source_id=d_kw.id,
                                                fetch_status="REJECTED_RULED").all()
    assert len(rejected) == 1
    _assert_balanced(stats)
