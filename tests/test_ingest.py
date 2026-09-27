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
