"""新源首导打分窗口测试：判定顺序（垃圾规则→窗口→ARCHIVED）、过期规则豁免、
ARCHIVED 全文照存/流经 sanitize/重打分补打、窗口成本上界。

条款：新注册源首导时，垃圾类规则仍先于窗口判定（垃圾不占 archived 名额）；
窗口外条目落 ARCHIVED（全文照存、不进过期拒绝、可经方向重打分任务补打）；
ARCHIVED 条目同样流经 sanitize（统计口径不漏类）；30 天过期规则对新源首导不
生效；窗口天数默认 7（site_config 可调，source_config 逐源覆盖）。
设计依据见 docs/design-index.md「AC-04.7」「AC-07.6」。
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import app.ingest.rss as rss_mod
import app.scoring.service as scoring_service
import app.siteconfig as siteconfig
from app.db import SessionLocal
from app.models import Item, ScoreResult, Source
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
        return type(self).responses.pop(0)


_LONG = "正文足够长以通过规则初筛。" * 30


def _feed(*items: str) -> bytes:
    return (f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>t</title>{''.join(items)}
    </channel></rss>""").encode()


def _item(guid: str, title: str, *, days_old: float | None = None, body: str = _LONG) -> str:
    if days_old is None:
        return (f"<item><guid>https://ex.com/{guid}</guid>"
                f"<link>https://ex.com/{guid}</link><title>{title}</title>"
                f"<description>{body}</description></item>")
    pub = (datetime.now(timezone.utc) - timedelta(days=days_old)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    return (f"<item><guid>https://ex.com/{guid}</guid>"
            f"<link>https://ex.com/{guid}</link><title>{title}</title>"
            f"<pubDate>{pub}</pubDate><description>{body}</description></item>")


@pytest.fixture()
def fresh_source(db_session):
    """从未抓取过的新源（首导轮判定前提：last_fetched_at 为空）。"""
    from app.models import Direction

    d = db_session.query(Direction).filter_by(name="首导方向").one_or_none()
    if d is None:
        d = Direction(name="首导方向", prompt="p", threshold=60)
        db_session.add(d)
        db_session.commit()
    src = Source(direction_id=d.id, url="https://feeds.example/first.xml", type="rss")
    db_session.add(src)
    db_session.commit()
    return src


def _fetch(db_session, monkeypatch, src, feed: bytes):
    FakeClient.responses = [FakeResp(feed)]
    monkeypatch.setattr(rss_mod.httpx, "Client", FakeClient)
    return rss_mod.fetch_source(db_session, src)


def test_first_ingest_window_archives_old_entries(db_session, fresh_source, monkeypatch):
    """首导判定顺序：垃圾规则先于窗口（过短旧条目 rejected 不占 archived）；窗口外
    （超 7 天）落 ARCHIVED 且全文照存；窗口内与缺发布时间条目正常 FETCHED。"""
    feed = _feed(
        _item("old-1", "旧闻一", days_old=400),
        _item("recent-1", "新文一", days_old=1),
        _item("no-date-1", "无日期", body=_LONG),
        _item("junk-old", "垃圾旧闻", days_old=400, body="太短"),
    )
    stats = _fetch(db_session, monkeypatch, fresh_source, feed)

    assert stats.archived == 1 and stats.rule_rejected == 1
    rows = {it.guid: it for it in db_session.query(Item).filter_by(source_id=fresh_source.id).all()}
    assert rows["https://ex.com/old-1"].fetch_status == "ARCHIVED"
    assert rows["https://ex.com/old-1"].content_text == _LONG  # 全文照存
    assert rows["https://ex.com/old-1"].rule_reject_reason is None  # 不进过期拒绝
    assert rows["https://ex.com/recent-1"].fetch_status == "FETCHED"
    assert rows["https://ex.com/no-date-1"].fetch_status == "FETCHED"  # 缺发布时间不判窗口外
    junk = rows["https://ex.com/junk-old"]
    assert junk.fetch_status == "REJECTED_RULED" and junk.rule_reject_reason.startswith("too_short:")


def test_expiry_rule_not_applied_on_first_ingest(db_session, fresh_source, monkeypatch):
    """30 天过期规则对新源首导不生效：400 天旧闻不因过期被拒（只受窗口判定）。"""
    feed = _feed(_item("very-old", "超旧闻", days_old=400))
    stats = _fetch(db_session, monkeypatch, fresh_source, feed)
    assert stats.rule_rejected == 0 and stats.archived == 1
    it = db_session.query(Item).filter_by(source_id=fresh_source.id).one()
    assert it.fetch_status == "ARCHIVED"


def test_second_fetch_expiry_rule_applies(db_session, fresh_source, monkeypatch):
    """首导之后的正常轮：过期规则恢复生效（旧条目直接 rejected，不入 archived）。"""
    _fetch(db_session, monkeypatch, fresh_source,
           _feed(_item("first-1", "首批", days_old=1)))
    feed = _feed(_item("second-old", "次轮旧闻", days_old=400))
    stats = _fetch(db_session, monkeypatch, fresh_source, feed)
    assert stats.archived == 0 and stats.rule_rejected == 1
    it = db_session.query(Item).filter_by(source_id=fresh_source.id,
                                          guid="https://ex.com/second-old").one()
    assert it.fetch_status == "REJECTED_RULED" and it.rule_reject_reason.startswith("expired:")


def test_archived_items_flow_through_sanitize(db_session, fresh_source, monkeypatch):
    """ARCHIVED 条目同样流经 sanitize 阶段（统计口径不漏类）。"""
    monkeypatch.setattr(rss_mod.config, "SANITIZE_ENABLED", True)
    monkeypatch.setattr(rss_mod.config, "SANITIZE_DENY_KEYWORDS", ["禁词"])
    feed = _feed(_item("arch-deny", "旧闻含禁词内容", days_old=400,
                       body=_LONG + "命中禁词的正文段落。"))
    _fetch(db_session, monkeypatch, fresh_source, feed)
    it = db_session.query(Item).filter_by(source_id=fresh_source.id,
                                          guid="https://ex.com/arch-deny").one()
    assert it.fetch_status == "ARCHIVED"
    assert it.sanitize_status == "REJECTED"  # 过滤状态与抓取状态语义分离，两者都落


def test_first_ingest_scoring_calls_bounded_by_window(db_session, fresh_source, monkeypatch):
    """窗口成本上界：首导后打分调用数 ≤ 窗口内条数（历史库存零打分成本）。"""
    items = [_item("old", "旧闻", days_old=400)] + [
        _item(f"recent-{i}", f"新文{i}", days_old=1) for i in range(3)]
    _fetch(db_session, monkeypatch, fresh_source, _feed(*items))

    calls: list[int] = []

    def fake_score(db, item, direction):
        calls.append(item.id)

        class R:
            status = "OK"
            passed = True
            error = None

        return R()

    monkeypatch.setattr(scoring_service, "score_item", fake_score)
    score_round(db_session, triggered_by="test")
    assert len(calls) == 3  # 只有 3 条窗口内条目进打分，archived 历史库存零调用


def test_archived_item_rescoring_backfill(db_session, fresh_source, monkeypatch):
    """ARCHIVED 条目可经方向重打分任务补打（rescore 后有当前版本 OK 行）。"""
    _fetch(db_session, monkeypatch, fresh_source, _feed(_item("arch-rs", "归档旧闻", days_old=400)))

    from fastapi.testclient import TestClient

    from app.auth import bootstrap_admin

    bootstrap_admin(db_session)
    from app.main import app

    client = TestClient(app)
    import secrets

    import app.config as cfg

    client.post("/api/auth/login", json={"username": "admin",
                                         "password": cfg.NEWSWRIGHT_ADMIN_PASSWORD})
    client.post("/api/auth/password",
                json={"old_password": cfg.NEWSWRIGHT_ADMIN_PASSWORD,
                      "new_password": "g4-" + secrets.token_urlsafe(12)})
    did = fresh_source.direction_id
    r = client.post(f"/api/directions/{did}/rescore", json={"scope": "all"})
    assert r.status_code == 202

    calls: list[int] = []

    def fake_score(db, item, direction):
        calls.append(item.id)
        sr = ScoreResult(item_id=item.id, direction_id=direction.id, quality_score=80,
                         relevance_score=90, band="high", reason="补打",
                         prompt_version=direction.prompt_version, model="m",
                         passed=True, status="OK")
        db.add(sr)
        db.commit()
        return sr

    monkeypatch.setattr(scoring_service, "score_item", fake_score)
    score_round(SessionLocal(), triggered_by="test")
    assert len(calls) == 1  # 归档条目被补打
    it = db_session.query(Item).filter_by(source_id=fresh_source.id).one()
    rows = db_session.query(ScoreResult).filter_by(item_id=it.id).all()
    assert len(rows) == 1 and rows[0].status == "OK"


def test_first_ingest_days_overrides(db_session, fresh_source, monkeypatch):
    """窗口天数：source_config.first_ingest_days 逐源覆盖 > site_config 默认。"""
    # site_config 默认 7：30 天前条目在窗外
    stats = _fetch(db_session, monkeypatch, fresh_source,
                   _feed(_item("w30", "三十天前", days_old=30)))
    assert stats.archived == 1

    # site_config 全局调大：30 天前条目进窗
    from app.models import SiteConfig

    db_session.add(SiteConfig(key="first_ingest_days", value=90))
    db_session.commit()
    src2 = Source(direction_id=fresh_source.direction_id,
                  url="https://feeds.example/first-2.xml", type="rss")
    db_session.add(src2)
    db_session.commit()
    stats2 = _fetch(db_session, monkeypatch, src2, _feed(_item("w90", "三十天前二", days_old=30)))
    assert stats2.archived == 0

    # source_config 逐源覆盖：收紧到 1 天 → 30 天前条目在窗外
    src3 = Source(direction_id=fresh_source.direction_id,
                  url="https://feeds.example/first-3.xml", type="rss",
                  source_config={"first_ingest_days": 1})
    db_session.add(src3)
    db_session.commit()
    stats3 = _fetch(db_session, monkeypatch, src3, _feed(_item("w1", "三十天前三", days_old=30)))
    assert stats3.archived == 1
