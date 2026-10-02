"""G1/W4 P1-2 测试：方向内跨源 URL 指纹去重（AC-05.2/D15）。

覆盖：同方向源 A→源 B 同 URL（大小写/fragment/utm 变体）→ 第二条 DUP +
duplicate_of 指向 A + 全文照存 + 零 LLM 调用；跨方向独立（D15，AC-07.2 前提）；
归一化单测；分桶口径（inserted 含 DUP 行）。
"""
import httpx
import pytest

import app.ingest.rss as rss_mod
import app.scoring.service as scoring
from app.ingest.fingerprint import canonical_url, url_fingerprint
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
