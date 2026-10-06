"""M11 测试：搜索底座——provider 归一化、额度闸拦截与恢复、计数口径、通道转 item。"""
from datetime import datetime

import pytest

import app.search.pipeline as search_pipeline
import app.search.quota as quota_mod
import app.search.registry as registry
from app.search.base import SearchResult
from app.search.quota import check_and_count, quota_state
from app.models import Item, PipelineTask, SearchCallLog, Source


# ---------- 额度闸 ----------

def test_quota_check_and_count(db_session):
    allowed, s1 = check_and_count(db_session, "fakeprov")
    assert allowed and s1["minute"]["used"] == 1 and s1["day"]["used"] == 1
    allowed2, s2 = check_and_count(db_session, "fakeprov")
    assert allowed2 and s2["minute"]["used"] == 2


def test_quota_minute_limit_blocks_and_recovers(db_session, monkeypatch):
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_MINUTE", 2)
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_DAY", 100)
    assert check_and_count(db_session, "fakeprov")[0]
    assert check_and_count(db_session, "fakeprov")[0]
    allowed, state = check_and_count(db_session, "fakeprov")
    assert not allowed and state["minute"]["used"] == state["minute"]["limit"]

    # 分钟窗口翻页 → 自然恢复（不重置日计数）
    later = quota_mod.datetime.now().replace(minute=(quota_mod.datetime.now().minute + 1) % 60)
    allowed2, s2 = check_and_count(db_session, "fakeprov", now=later)
    assert allowed2 and s2["minute"]["used"] == 1


def test_quota_day_limit_blocks(db_session, monkeypatch):
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_MINUTE", 100)
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_DAY", 1)
    assert check_and_count(db_session, "fakeprov")[0]
    assert not check_and_count(db_session, "fakeprov")[0]


# ---------- 通道（fetch_search_source） ----------

def _mk_search_source(db, provider="fakeprov", keyword="测试词") -> Source:
    from app.models import Direction

    d = db.query(Direction).filter_by(name="DQ").one_or_none()
    if d is None:
        d = Direction(name="DQ", prompt="p", threshold=60)
        db.add(d)
        db.commit()
    src = Source(direction_id=d.id, url=f"search://{provider}/{keyword}", type="search",
                 source_config={"keyword": keyword, "provider": provider, "group": "g1"})
    db.add(src)
    db.commit()
    return src


def _fake_results(n=3):
    return [
        SearchResult(
            title=f"结果{i}",
            url=f"https://ex.com/article/{i}",
            snippet="摘要" * 150,  # 足够长过规则
            content="全文" * 200,
            published_at=datetime(2026, 9, 27),
            raw={"index": i},
        )
        for i in range(n)
    ]


def test_search_channel_end_to_end(db_session, monkeypatch):
    src = _mk_search_source(db_session)
    monkeypatch.setattr(registry, "get_provider", lambda name, db=None: type("P", (), {
        "name": name,
        "search": lambda self, q, count=10, **kw: _fake_results(),
    })())
    stats = search_pipeline.fetch_search_source(db_session, src)
    assert stats.inserted == 3 and stats.dup_blocked == 0 and stats.error is None
    items = db_session.query(Item).filter_by(source_id=src.id).all()
    assert len(items) == 3
    it = items[0]
    assert it.guid == "https://ex.com/article/0"  # 归一化 URL 作 guid
    assert it.fetch_status == "FETCHED" and it.sanitize_status == "PASSED"
    assert it.raw == {"index": 0} and it.content_text.startswith("全文")
    # 调用日志一行（成功）
    logs = db_session.query(SearchCallLog).all()
    assert len(logs) == 1 and logs[0].ok and logs[0].result_count == 3

    # 重跑：URL 去重拦截（幂等）
    stats2 = search_pipeline.fetch_search_source(db_session, src)
    assert stats2.inserted == 0 and stats2.dup_blocked == 3


def test_search_channel_quota_blocked_skipped(db_session, monkeypatch):
    src = _mk_search_source(db_session)
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_MINUTE", 0)
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_DAY", 100)

    called = {"n": 0}

    class P:
        name = "fakeprov"

        def search(self, *a, **kw):
            called["n"] += 1
            return _fake_results()

    monkeypatch.setattr(registry, "get_provider", lambda name, db=None: P())
    stats = search_pipeline.fetch_search_source(db_session, src)
    # 调用未发出（SKIPPED_QUOTA 语义）
    assert called["n"] == 0
    assert stats.extra.get("quota_blocked") is True and stats.inserted == 0 and not stats.error
    logs = db_session.query(SearchCallLog).all()
    assert len(logs) == 1 and logs[0].status == "blocked" and logs[0].error == "SKIPPED_QUOTA"
    # 不计失败退避
    from app.models import Source as S

    assert db_session.get(S, src.id).backoff_failures == 0


def test_search_channel_provider_error_recorded(db_session, monkeypatch):
    src = _mk_search_source(db_session)

    class P:
        name = "fakeprov"

        def search(self, *a, **kw):
            from app.search.base import SearchError

            raise SearchError("boom")

    monkeypatch.setattr(registry, "get_provider", lambda name, db=None: P())
    stats = search_pipeline.fetch_search_source(db_session, src)
    assert stats.error and "boom" in stats.error
    logs = db_session.query(SearchCallLog).all()
    assert len(logs) == 1 and not logs[0].ok and logs[0].status == "error"


def test_registry_unknown_provider():
    from app.search.base import SearchError

    with pytest.raises(SearchError):
        registry.get_provider("no_such_provider")
