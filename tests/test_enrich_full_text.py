"""RSS 摘要富化开关测试（enrich_full_text）：成本只花在被拒条目上。

条款依据：产品书 US-04 摘要富化开关（源配置 enrich_full_text=true 时，条目因
too_short 被拒且带真实 URL → 复用 web 富化路径抓原文补全；护栏：条目 URL=页面
URL 不富化；开关关闭（默认）或无 URL → 维持拒绝；失败保持 too_short 拒绝且
全文照存）。设计依据见 docs/design-index.md「AC-04.8」「B5」。
"""
import httpx
import pytest

import app.ingest.rss as rss_mod
import app.ingest.web as web_mod
from app.ingest.rss import fetch_source
from app.models import Direction, Item, Source


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
        return type(self).responses.pop(0)


_FULL_TEXT = "富化后的完整原文。" * 60  # 远超规则最小字数


def _short_feed() -> bytes:
    """两条过短条目（均带真实 URL）+ 一条正常条目。"""
    return """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>t</title>
      <item><guid>https://ex.com/short-1</guid><link>https://ex.com/short-1</link>
      <title>短条目一</title><description>太短了。</description></item>
      <item><guid>https://ex.com/short-2</guid><link>https://ex.com/short-2</link>
      <title>短条目二</title><description>也太短。</description></item>
      <item><guid>https://ex.com/long</guid><link>https://ex.com/long</link>
      <title>长条目</title><description>长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长，不需要富化即可通过规则初筛。</description></item>
    </channel></rss>""".encode("utf-8")


def _setup(db_session, monkeypatch, *, source_config, feed=None, enrich_result=None):
    """公共脚手架：建方向与源、打桩抓取与富化，返回 (source, enrich_calls)。"""
    d = Direction(name="富化方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://feeds.example/enrich.xml", type="rss",
                 source_config=source_config)
    db_session.add(src)
    db_session.commit()

    FakeClient.responses = [FakeResp(feed or _short_feed())]
    monkeypatch.setattr(rss_mod.httpx, "Client", FakeClient)

    calls: list[dict] = []

    def fake_enrich(url, current_text, *, page_url):
        calls.append({"url": url, "current_text": current_text, "page_url": page_url})
        if enrich_result is None:
            return _FULL_TEXT
        return enrich_result  # None 之外的值模拟富化失败（无增量）

    monkeypatch.setattr(web_mod, "enrich_entry_text", fake_enrich)
    return src, calls


def test_enrich_disabled_by_default(db_session, monkeypatch):
    """开关默认关：不发起任何富化请求，过短条目维持 too_short 拒绝。"""
    src, calls = _setup(db_session, monkeypatch, source_config=None)
    stats = fetch_source(db_session, db_session.merge(src))
    assert calls == []  # 零富化请求
    assert stats.rule_rejected == 2
    rows = db_session.query(Item).filter_by(source_id=src.id,
                                            fetch_status="REJECTED_RULED").all()
    assert all(row.rule_reject_reason.startswith("too_short") for row in rows)


def test_enrich_success_full_text_ingested(db_session, monkeypatch):
    """开关开 + 过短 + 真实 URL：富化全文入库进管线（fetch_status=FETCHED）。"""
    src, calls = _setup(db_session, monkeypatch,
                        source_config={"enrich_full_text": True})
    stats = fetch_source(db_session, db_session.merge(src))
    # 成本只花在被拒条目上：仅两条过短条目发起富化，长条目不富化
    assert len(calls) == 2
    assert {c["url"] for c in calls} == {"https://ex.com/short-1", "https://ex.com/short-2"}
    assert stats.rule_rejected == 0
    enriched = db_session.query(Item).filter_by(source_id=src.id,
                                                fetch_status="FETCHED").all()
    assert len(enriched) == 3
    assert any(row.content_text == _FULL_TEXT and row.title == "短条目一"
               for row in enriched)


def test_enrich_skips_entry_url_equal_to_feed_url(db_session, monkeypatch):
    """护栏：条目 URL=页面（feed）URL 不富化——抓回同一内容无增量。"""
    feed = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>t</title>
      <item><guid>https://feeds.example/enrich.xml</guid>
      <link>https://feeds.example/enrich.xml</link>
      <title>自指条目</title><description>太短了。</description></item>
    </channel></rss>""".encode("utf-8")
    src, calls = _setup(db_session, monkeypatch,
                        source_config={"enrich_full_text": True}, feed=feed)
    stats = fetch_source(db_session, db_session.merge(src))
    assert calls == []
    assert stats.rule_rejected == 1  # 维持 too_short 拒绝


def test_enrich_skips_entry_without_url(db_session, monkeypatch):
    """无 URL 的条目不富化（无处可抓）。"""
    feed = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>t</title>
      <item><guid>tag:ex.org,2026:no-link</guid>
      <title>无链接条目</title><description>太短了。</description></item>
    </channel></rss>""".encode("utf-8")
    src, calls = _setup(db_session, monkeypatch,
                        source_config={"enrich_full_text": True}, feed=feed)
    stats = fetch_source(db_session, db_session.merge(src))
    assert calls == []
    assert stats.rule_rejected == 1


def test_enrich_failure_keeps_too_short_rejection(db_session, monkeypatch):
    """富化失败（原文无增量）：维持 too_short 拒绝，摘要文本照存。"""
    src, calls = _setup(db_session, monkeypatch,
                        source_config={"enrich_full_text": True},
                        enrich_result="太短了。")  # 富化未取得更长文本
    stats = fetch_source(db_session, db_session.merge(src))
    assert len(calls) == 2
    assert stats.rule_rejected == 2
    rows = db_session.query(Item).filter_by(source_id=src.id,
                                            fetch_status="REJECTED_RULED").all()
    assert all(row.rule_reject_reason.startswith("too_short") for row in rows)
    assert all(row.content_text == "太短了。" for row in rows)  # 短文本照存


def test_enrich_skips_already_ingested_entries(db_session, monkeypatch):
    """已入库条目（guid 已存在）不富化：成本不花在重复抓取上。"""
    src, calls = _setup(db_session, monkeypatch,
                        source_config={"enrich_full_text": True})
    # 预置 short-1 已在库
    db_session.add(Item(source_id=src.id, guid="https://ex.com/short-1",
                        url="https://ex.com/short-1", title="已入库",
                        content_text="太短了。", fetch_status="FETCHED"))
    db_session.commit()
    fetch_source(db_session, db_session.merge(src))
    assert {c["url"] for c in calls} == {"https://ex.com/short-2"}
