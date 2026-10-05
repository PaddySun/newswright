"""采集轮次编排契约测试：可抓源闸门、跳过记录载荷、探测计数推进、
防阻塞入队、payload.stats 通道附加键合并、临时方向 TTL 懒扫描边界。

设计依据见 docs/design-index.md「AC-04.5」「AC-05.1」「AC-20.3」
「AC-05.3」「DT-5」「AC-03.4」「AC-03.3」。
"""
import types
from datetime import datetime, timedelta, timezone

import pytest

import app.pipeline.runner as runner_mod
from app.models import Direction, PipelineTask, Source
from app.pipeline.runner import (
    _fetch_stats_dict,
    enqueue_fetch_round,
    expire_due_temp_directions,
    fetch_round,
)


def _stats(**kw) -> types.SimpleNamespace:
    base = dict(source_id=1, url="https://feeds.example/o.xml", feed_entries=3,
                inserted=3, dup_blocked=0, rule_rejected=0, failed=0, archived=0,
                not_modified=False, sanitize_passed=3, sanitize_rejected=0,
                error=None, guid_collisions=0, rate_limited=False,
                retry_after=None, extra={})
    base.update(kw)
    return types.SimpleNamespace(**base)


@pytest.fixture()
def rss_source(db_session):
    d = Direction(name="编排方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://feeds.example/o.xml", type="rss")
    db_session.add(src)
    db_session.commit()
    return src


def test_extra_keys_merged_into_payload_stats():
    """采集统计的 extra 通道附加键并入任务 payload.stats
    （变更类型/HTTP 状态等经此通道落账）。"""
    d = _stats(extra={"http_status": 429, "change_type": "content_changed"})
    out = _fetch_stats_dict(d)
    assert out["change_type"] == "content_changed"
    assert out["http_status"] == 429


def test_disabled_source_not_fetched(db_session, rss_source, monkeypatch):
    """停用源不进入采集轮：不产生抓取任务、不出现在轮次统计里。"""
    calls: list[int] = []

    def _fake_fetch(db, s):
        calls.append(s.id)
        return _stats(source_id=s.id, url=s.url)

    rss_source.enabled = False
    db_session.commit()
    monkeypatch.setattr(runner_mod, "_fetch_one", _fake_fetch)
    summary = fetch_round(db_session, triggered_by="test")
    assert summary["sources"] == []
    assert calls == []


def test_probe_counter_advances_each_state_round(db_session, rss_source):
    """退避源的每个状态内轮次（含探测轮）都推进探测轮计数：
    每 4 轮放行一次探测，不得只数首轮后停摆饿死。"""
    def _close_round(db):
        # 只考察入队节奏：手工闭合上一轮的轮次任务，解除防重叠
        for t in db.query(PipelineTask).filter(
                PipelineTask.kind == "fetch_round",
                PipelineTask.status.in_(("PENDING", "RUNNING"))).all():
            t.status = "DONE"
        db.commit()

    src = rss_source
    src.backoff_failures = 3
    db_session.commit()
    for _ in range(5):
        enqueue_fetch_round(db_session, triggered_by="test")
        _close_round(db_session)
    src = db_session.merge(src)
    assert src.backoff_skips == 5
    probes = [t for t in db_session.query(PipelineTask).filter_by(kind="fetch").all()]
    assert len(probes) >= 2  # 首轮探测 + 第 5 轮再次探测


def test_skipped_entry_carries_contract_keys(db_session, rss_source):
    """限流跳过记录载荷带契约键：source_id/url/reason（调度跳过
    面的记录形态）。"""
    src = rss_source
    src.rate_limited_until = datetime.now(timezone.utc) + timedelta(minutes=30)
    db_session.commit()
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    assert rt is not None
    entry = rt.payload["skipped_backoff"][0]
    assert entry["reason"] == "rate_limited"
    assert set(entry.keys()) == {"source_id", "url", "reason"}
    assert entry["url"] == src.url


def test_skip_of_one_source_does_not_block_others(db_session, rss_source):
    """一个源命中跳过不得中断入队：同轮其他可抓源照常产生抓取任务。"""
    blocked = rss_source
    blocked.rate_limited_until = datetime.now(timezone.utc) + timedelta(minutes=30)
    d2 = Direction(name="编排方向二", prompt="p", threshold=60)
    db_session.add(d2)
    db_session.flush()
    ok_src = Source(direction_id=d2.id, url="https://feeds.example/o2.xml", type="rss")
    db_session.add(ok_src)
    db_session.commit()
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    assert rt is not None
    skipped_ids = [e["source_id"] for e in rt.payload["skipped_backoff"]]
    assert blocked.id in skipped_ids
    ok_tasks = [t for t in db_session.query(PipelineTask).filter_by(kind="fetch").all()
                if (t.payload or {}).get("source_id") == ok_src.id]
    assert len(ok_tasks) == 1


def test_deleted_temp_direction_not_resurrected_by_ttl_scan(db_session):
    """TTL 懒扫描只翻 active 方向：已软删除的 temp 方向保持 deleted，
    不得被复活为 expired。"""
    d = Direction(name="已删追踪方向", prompt="p", threshold=60, temp=True,
                  expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    db_session.add(d)
    db_session.flush()
    d.apply_status(Direction.STATUS_DELETED)
    db_session.commit()
    changed = expire_due_temp_directions(db_session)
    db_session.refresh(d)
    assert changed == 0
    assert d.status == Direction.STATUS_DELETED


def test_future_ttl_direction_stays_active(db_session):
    """TTL 未到期的 temp 方向保持 active（到期比较不可省略）。"""
    d = Direction(name="追踪中方向", prompt="p", threshold=60, temp=True,
                  expires_at=datetime.now(timezone.utc) + timedelta(days=7))
    db_session.add(d)
    db_session.commit()
    changed = expire_due_temp_directions(db_session)
    db_session.refresh(d)
    assert changed == 0
    assert d.status == Direction.STATUS_ACTIVE
