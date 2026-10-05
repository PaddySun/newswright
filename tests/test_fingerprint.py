"""G1/W4 P1-2 测试：方向内跨源 URL 指纹去重（AC-05.2/D15）。

覆盖：同方向源 A→源 B 同 URL（大小写/fragment/utm 变体）→ 第二条 DUP +
duplicate_of 指向 A + 全文照存 + 零 LLM 调用；跨方向独立（D15，AC-07.2 前提）；
归一化单测；分桶口径（inserted 含 DUP 行）。
"""
import httpx
import pytest

import app.ingest.rss as rss_mod
import app.scoring.service as scoring
from app.ingest.fingerprint import canonical_url, find_fingerprint_origin, url_fingerprint
from app.ingest.rss import fetch_source
from app.models import Direction, Item, Source, UsageLog
from app.pipeline.runner import score_round


class FakeResp:
    def __init__(self, content, status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})

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
        return FakeClient.responses.pop(0)


def _feed_xml(link: str) -> bytes:
    body = "正文内容足够长以通过规则初筛。" * 20
    return f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>b</title>
      <item>
        <guid>https://bsrc.com/gB</guid>
        <link>{link}</link>
        <title>Dup Entry</title>
        <description>{body}</description>
      </item>
    </channel></rss>""".encode("utf-8")


@pytest.fixture()
def two_sources(db_session):
    d = Direction(name="DD", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    a = Source(direction_id=d.id, url="https://feeds.example/a.xml", type="rss")
    b = Source(direction_id=d.id, url="https://feeds.example/b.xml", type="rss")
    db_session.add_all([a, b])
    db_session.commit()
    return d, a, b


def _seed_origin(db, src) -> Item:
    fp = url_fingerprint("https://ex.com/post?utm_source=feedA")
    orig = Item(source_id=src.id, guid="https://ex.com/post",
                url="https://ex.com/post?utm_source=feedA", title="Origin",
                content_text="全文A" * 100, fetch_status="FETCHED",
                sanitize_status="PASSED", direction_id=src.direction_id,
                fingerprint=fp)
    db.add(orig)
    db.commit()
    return orig


def test_url_normalization_fingerprint():
    """归一化单测：大小写/fragment/utm 折叠同指纹；不同路径不同指纹。"""
    a = url_fingerprint("https://EX.com/post?utm_source=rss#top")
    assert a == url_fingerprint("https://ex.com/post")
    assert canonical_url("https://Ex.COM/PaTh?fbclid=x") == "https://ex.com/PaTh"
    assert url_fingerprint("https://ex.com/other") != a
    assert url_fingerprint("") is None


def test_url_dup(db_session, two_sources, monkeypatch):
    """AC-05.2 全场景：同方向跨源同 URL → DUP + duplicate_of + 全文照存 + 零 LLM。"""
    d, src_a, src_b = two_sources
    orig = _seed_origin(db_session, src_a)

    FakeClient.responses = [FakeResp(_feed_xml("https://EX.com/post?utm_source=rss#frag"))]
    monkeypatch.setattr(rss_mod.httpx, "Client", FakeClient)
    stats = fetch_source(db_session, src_b)

    # 分桶口径（AC-05.1）：inserted 含 DUP 行
    assert stats.inserted == 1 and stats.dup_blocked == 0
    row = db_session.query(Item).filter_by(source_id=src_b.id).one()
    assert row.fetch_status == "DUP"
    assert row.duplicate_of == orig.id  # 同方向内引用
    assert row.content_text == "正文内容足够长以通过规则初筛。" * 20  # 全文照存
    assert row.fingerprint == orig.fingerprint and row.direction_id == d.id

    # 打分豁免：score_round 只打 FETCHED，DUP 零 LLM 调用（usage_log 无 scoring 行）
    calls: list[int] = []

    def fake_score(db, item, direction):
        calls.append(item.id)

        class R:
            status = "OK"
            passed = True
            error = None

        return R()

    monkeypatch.setattr(scoring, "score_item", fake_score)
    score_round(db_session, triggered_by="test", direction_id=d.id)
    assert calls == [orig.id]  # 只有原条目被打分，DUP 不进打分
    assert db_session.query(UsageLog).filter(UsageLog.call_point == "scoring").count() == 0


def test_cross_direction_independent(db_session, two_sources, monkeypatch):
    """D15：跨方向同 URL 各自独立采集打分（AC-07.2 据此成立）。"""
    d, src_a, _ = two_sources
    orig = _seed_origin(db_session, src_a)
    d2 = Direction(name="DD2", prompt="p", threshold=60)
    db_session.add(d2)
    db_session.commit()
    src_c = Source(direction_id=d2.id, url="https://feeds.example/c.xml", type="rss")
    db_session.add(src_c)
    db_session.commit()

    FakeClient.responses = [FakeResp(_feed_xml("https://ex.com/post"))]
    monkeypatch.setattr(rss_mod.httpx, "Client", FakeClient)
    stats = fetch_source(db_session, src_c)

    assert stats.inserted == 1
    row = db_session.query(Item).filter_by(source_id=src_c.id).one()
    assert row.fetch_status == "FETCHED"  # 方向 2 无指纹命中 → 正常入库
    assert row.duplicate_of is None and row.direction_id == d2.id
    assert row.fingerprint == orig.fingerprint  # 指纹相同但作用域不跨方向


def test_find_fingerprint_origin_returns_earliest(db_session, two_sources):
    """同方向多条同指纹命中时返回最早入库条目（min id）——duplicate_of 指向语义钉死
    （解析见 docs/design-index.md）。"""
    d, src_a, src_b = two_sources
    fp = url_fingerprint("https://ex.com/same-post")
    i1 = Item(source_id=src_a.id, guid="o1", url="https://ex.com/same-post", title="First",
              content_text="全文", fetch_status="FETCHED", direction_id=d.id, fingerprint=fp)
    db_session.add(i1)
    db_session.commit()
    i2 = Item(source_id=src_b.id, guid="o2", url="https://ex.com/same-post", title="Second",
              content_text="全文", fetch_status="FETCHED", direction_id=d.id, fingerprint=fp)
    db_session.add(i2)
    db_session.commit()
    origin = find_fingerprint_origin(db_session, d.id, fp)
    assert origin.id == i1.id


# ---------- 指纹退化链（RSS 加固批）：link → URL 型 guid → 标题兜底[低置信] ----------


def test_entry_fingerprint_chain_prefers_link():
    """链一：有可用 link URL 时取 URL 指纹，非低置信。"""
    from app.ingest.fingerprint import entry_fingerprint

    fp, low = entry_fingerprint("https://EX.com/post?utm_source=rss#top", "", "")
    assert fp == url_fingerprint("https://ex.com/post")
    assert low is False


def test_entry_fingerprint_chain_guid_fallback():
    """链二：link 缺失且 guid 为 URL 型 → 取 guid 指纹（tag:/urn: 型跳过）。"""
    from app.ingest.fingerprint import entry_fingerprint

    fp, low = entry_fingerprint("", "https://guid.ex.com/p/1?utm_source=f", "标题")
    assert fp == url_fingerprint("https://guid.ex.com/p/1")
    assert low is False
    # 非 URL 型 guid（tag:/urn:）不作链二，落到链三
    fp2, low2 = entry_fingerprint("", "tag:arxiv.org,2026:cs/1", "标题甲")
    assert fp2 is not None and fp2.startswith("ttl:")
    assert low2 is True


def test_entry_fingerprint_chain_title_fallback_low_confidence():
    """链三：标题兜底，低置信以 ttl: 前缀在指纹值内留痕。"""
    from app.ingest.fingerprint import entry_fingerprint

    fp, low = entry_fingerprint("", "", "某条新闻的标题")
    assert fp is not None and fp.startswith("ttl:")
    assert low is True
    assert len(fp) <= 64  # 贴合指纹列宽
    assert entry_fingerprint("", "", "")[0] is None  # 三级皆不可得 → 不参与去重


def test_title_fingerprint_unescape_then_nfkc():
    """标题归一化顺序：先解码 HTML 实体再做 NFKC + 空白折叠——实体不解码则
    同一标题分裂为两条指纹（右单引号 &#8217; / ’ / 全角空格 变体必须同指纹）。"""
    from app.ingest.fingerprint import title_fingerprint

    a = title_fingerprint("Apple&#8217;s M 系列芯片　发布")
    b = title_fingerprint("Apple’s M 系列芯片 发布")
    assert a == b and a is not None
    assert title_fingerprint("完全不同的标题") != a


def test_title_fallback_dup_marks_duplicate_within_direction(db_session, two_sources, monkeypatch):
    """链路集成：两个源各自条目均无 link、guid 非 URL 型、标题相同 →
    后入库条目按标题兜底指纹判 DUP（低置信指纹参与方向内去重）。"""
    d, src_a, src_b = two_sources

    def _title_only_feed(title: str) -> bytes:
        return f"""<?xml version="1.0"?>
        <rss version="2.0"><channel><title>b</title>
          <item><guid>tag:ex.org,2026:{"a" if title == "First" else "b"}</guid>
          <title>{title}</title>
          <description>正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。正文内容足够长以通过规则初筛。</description></item>
        </channel></rss>""".encode("utf-8")

    FakeClient.responses = [FakeResp(_title_only_feed("First"))]
    monkeypatch.setattr(rss_mod.httpx, "Client", FakeClient)
    s1 = fetch_source(db_session, src_a)
    assert s1.inserted == 1
    first = db_session.query(Item).filter_by(source_id=src_a.id).one()
    assert first.fingerprint.startswith("ttl:")

    FakeClient.responses = [FakeResp(_title_only_feed("First"))]
    s2 = fetch_source(db_session, src_b)
    assert s2.inserted == 1
    second = db_session.query(Item).filter_by(source_id=src_b.id).one()
    assert second.fetch_status == "DUP" and second.duplicate_of == first.id
