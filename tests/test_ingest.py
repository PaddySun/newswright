"""M3 测试：guid/URL 归一化、(source_id, guid) 去重、规则初筛。"""
from app.ingest.rss import extract_entry_text, normalize_guid, normalize_url, parse_feed_entries
from app.ingest.rules import apply_rules


def test_normalize_url_strips_tracking():
    url = "https://example.com/a?utm_source=rss&id=7&utm_medium=x#frag"
    assert normalize_url(url) == "https://example.com/a?id=7"
    assert normalize_url("tag:arxiv.org,2026:cs.CV/2601.00001") == "tag:arxiv.org,2026:cs.CV/2601.00001"


def test_normalize_guid_prefers_id():
    e = {"id": "https://x.com/p/1?utm_source=f", "link": "https://x.com/p/2"}
    assert normalize_guid(e) == "https://x.com/p/1"
    e2 = {"link": "https://y.com/b?fbclid=z"}
    assert normalize_guid(e2) == "https://y.com/b"
    assert normalize_guid({"link": "https://z.com/c"}) == "https://z.com/c"


def test_rules_length_blacklist_expiry():
    long_body = "字" * 250
    assert apply_rules(title="t", content_text=long_body, published_at=None).passed

    r = apply_rules(title="t", content_text="太短", published_at=None)
    assert not r.passed and r.reason.startswith("too_short")

    r = apply_rules(title="博彩", content_text=long_body, published_at=None, blacklist=["博彩"])
    assert not r.passed and r.reason == "blacklist:博彩"

    from datetime import datetime, timedelta, timezone

    old = datetime.now(timezone.utc) - timedelta(days=40)
    r = apply_rules(title="t", content_text=long_body, published_at=old)
    assert not r.passed and r.reason.startswith("expired")

    # 缺发布时间不算过期
    assert apply_rules(title="t", content_text=long_body, published_at=None).passed


def test_parse_feed_entries_dedup_and_extract():
    xml = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>t</title>
      <item>
        <guid>https://ex.com/1?utm_source=x</guid>
        <link>https://ex.com/1</link>
        <title>First</title>
        <pubDate>Mon, 28 Sep 2026 08:00:00 GMT</pubDate>
        <description>&lt;p&gt;This is a paragraph with &lt;b&gt;bold&lt;/b&gt; text and enough characters to pass rules in this fixture body.&lt;/p&gt;</description>
      </item>
      <item>
        <guid>https://ex.com/1</guid>
        <link>https://ex.com/1</link>
        <title>Dup</title>
        <description>dup</description>
      </item>
    </channel></rss>"""
    entries = parse_feed_entries(xml)
    assert len(entries) == 2
    assert entries[0].guid == "https://ex.com/1"
    assert "bold" in entries[0].content_text
    assert entries[0].published_at is not None


def test_normalize_guid_url_scheme_case_insensitive():
    """URL 型 guid 的 scheme 大小写不敏感：大写/混合写法 scheme（HTTP://）同样走
    URL 归一化（去 tracking 参数与 fragment），不得因前缀判定只认小写而原样漏过；
    非 URL 形式（tag:/urn:）仍原样保留。"""
    e = {"id": "HTTP://Example.COM/post?utm_source=rss#top", "link": "https://x.com/other"}
    assert normalize_guid(e) == "http://Example.COM/post"
    e2 = {"id": "HtTpS://ex.com/p?fbclid=z"}
    assert normalize_guid(e2) == "https://ex.com/p"
    assert normalize_guid({"id": "tag:arxiv.org,2026:cs/1"}) == "tag:arxiv.org,2026:cs/1"


def test_fetch_source_client_redirect_contract(db_session, monkeypatch):
    """RSS 抓取的 httpx 客户端构造契约：跟随重定向且显式限定跳转上限 3 次。
    两者必须同时出现在构造参数中——只跟随不限次会失控，只设上限不跟随则不跳转。"""
    import types

    import app.ingest.rss as rss_mod
    from app.models import Direction, Source

    class RedirectProbeClient:
        """记录构造 kwargs 的假 httpx.Client；get 返回 304 以短路后续解析。"""
        init_kwargs: dict = {}

        def __init__(self, **kw):
            type(self).init_kwargs = dict(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return types.SimpleNamespace(status_code=304, headers={})

    monkeypatch.setattr(rss_mod.httpx, "Client", RedirectProbeClient)
    d = Direction(name="重定向契约方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://feeds.example/r.xml", type="rss")
    db_session.add(src)
    db_session.commit()

    stats = rss_mod.fetch_source(db_session, src)

    assert RedirectProbeClient.init_kwargs.get("follow_redirects") is True
    assert RedirectProbeClient.init_kwargs.get("max_redirects") == 3
    assert stats.not_modified is True  # 304 短路路径未被构造参数变化破坏
