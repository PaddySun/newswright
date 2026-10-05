"""搜索关键词边际降频测试（独立于 429 降频计数）：连续 6 轮零新增 → 倍增限速，
跳过 reason=keyword_exhausted；恢复 = hot_batch 关键词更新 / 站长手工刷新 /
方向提示词升版。设计依据见 docs/design-index.md「D20」「R3」。
"""
from datetime import datetime, timedelta, timezone

import pytest

import app.search.pipeline as search_pipeline
import app.search.registry as registry
from app.models import Direction, Item, PipelineTask, Source
from app.pipeline.runner import _update_source_health, enqueue_fetch_round
from app.pipeline.skip_policy import rate_limit_minutes, reset_keyword_backoff
from app.search.base import SearchResult


@pytest.fixture()
def search_source(db_session):
    d = Direction(name="关键词方向", prompt="p1", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="search://fakeprov/测试词", type="search",
                 source_config={"keyword": "测试词", "provider": "fakeprov"})
    db_session.add(src)
    db_session.commit()
    return src


def _patch_provider(monkeypatch, n_results: int):
    results = [
        SearchResult(title=f"结果{i}", url=f"https://ex.com/k/{n_results}-{i}",
                     snippet="摘要" * 150, content="全文" * 200, published_at=None,
                     raw={})
        for i in range(n_results)
    ]
    monkeypatch.setattr(registry, "get_provider", lambda name: type("P", (), {
        "name": name,
        "search": lambda self, q, count=10, **kw: results,
    })())


def _run_search_round(db_session, monkeypatch, n_results: int):
    """跑一轮搜索采集并做健康状态更新，返回抓取统计。"""
    src = search_source_ns = db_session.query(Source).filter_by(type="search").one()
    _patch_provider(monkeypatch, n_results)
    stats = search_pipeline.fetch_search_source(db_session, src)
    _update_source_health(db_session, src, stats)
    return stats


def test_six_zero_rounds_trigger_keyword_limiter(db_session, search_source, monkeypatch):
    """连续 6 轮零新增 → 进入 1 档限速（30 分钟）；期间轮次跳过
    reason=keyword_exhausted。与 429 降频（D13）计数相互独立。"""
    for _ in range(6):
        _run_search_round(db_session, monkeypatch, 0)  # 搜索返回 0 条
    src = db_session.merge(search_source)
    assert src.keyword_zero_rounds >= 6
    assert src.keyword_rate_level == 1
    assert src.keyword_limited_until is not None
    until = src.keyword_limited_until if src.keyword_limited_until.tzinfo else src.keyword_limited_until.replace(tzinfo=timezone.utc)
    assert until <= datetime.now(timezone.utc) + timedelta(minutes=rate_limit_minutes(1))

    # 限速期内：调度跳过，reason=keyword_exhausted
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    fetch_tasks = [t for t in db_session.query(PipelineTask).filter_by(kind="fetch").all()
                   if (t.payload or {}).get("round_task_id") == rt.id]
    assert fetch_tasks == []
    entry = next(e for e in rt.payload["skipped_backoff"] if e["source_id"] == src.id)
    assert entry["reason"] == "keyword_exhausted"


def test_new_results_reset_keyword_counter(db_session, search_source, monkeypatch):
    """某轮出现新增：零收益计数清零、限速解除（事实恢复）。"""
    for _ in range(5):
        _run_search_round(db_session, monkeypatch, 0)
    _run_search_round(db_session, monkeypatch, 3)  # 该轮有新增
    src = db_session.merge(search_source)
    assert src.keyword_zero_rounds == 0
    assert src.keyword_rate_level == 0 and src.keyword_limited_until is None


def test_search_items_carry_keyword_attribution(db_session, search_source, monkeypatch):
    """搜索通道条目记录命中关键词（逐词新增率归因的数据面）。"""
    _run_search_round(db_session, monkeypatch, 2)
    items = db_session.query(Item).filter_by(source_id=search_source.id).all()
    assert len(items) == 2
    assert all(it.source_keyword == "测试词" for it in items)


def test_recovery_via_direction_prompt_bump(db_session, search_source, monkeypatch, auth_client):
    """恢复事件：方向提示词升版（rescore 场景）→ 该方向搜索源关键词限速复位。"""
    for _ in range(6):
        _run_search_round(db_session, monkeypatch, 0)
    src = db_session.merge(search_source)
    assert src.keyword_limited_until is not None

    r = auth_client.put(f"/api/directions/{src.direction_id}", json={"prompt": "新提示词"})
    assert r.status_code == 200
    db_session.expire_all()
    src = db_session.get(Source, src.id)  # 跨会话写库后过期重读
    assert src.keyword_zero_rounds == 0
    assert src.keyword_rate_level == 0 and src.keyword_limited_until is None


def test_recovery_via_manual_reset(db_session, search_source, monkeypatch):
    """恢复事件：站长手工刷新（复位函数； hot_batch 关键词更新走同一入口）。"""
    for _ in range(6):
        _run_search_round(db_session, monkeypatch, 0)
    src = db_session.merge(search_source)
    assert src.keyword_limited_until is not None

    reset_keyword_backoff(db_session, direction_id=src.direction_id)
    src = db_session.merge(src)
    assert src.keyword_zero_rounds == 0
    assert src.keyword_rate_level == 0 and src.keyword_limited_until is None


def test_d13_and_d20_counters_independent(db_session, search_source, monkeypatch):
    """D13 与 D20 同构但独立计数：429 限流不推进关键词零收益计数，反之亦然。"""
    from types import SimpleNamespace

    src = db_session.merge(search_source)
    # 429 轮：rate 计数动，keyword 计数不动
    stats = SimpleNamespace(error=None, feed_entries=0, inserted=0, not_modified=False,
                            rate_limited=True, retry_after=None, extra={})
    _update_source_health(db_session, src, stats)
    src = db_session.merge(src)
    assert src.rate_level == 1 and src.keyword_zero_rounds == 0
