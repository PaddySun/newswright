"""M8c 测试：调度轮次——入队/执行分离、防重叠、连续失败退避与探测。"""
from app import config
from app.models import Direction, PipelineTask, Source
from app.pipeline.runner import (
    enqueue_fetch_round,
    process_fetch_round,
    round_busy,
)


def _mk_source(db, url: str) -> Source:
    d = db.query(Direction).filter_by(name="DS").one_or_none()
    if d is None:
        d = Direction(name="DS", prompt="p", threshold=60)
        db.add(d)
        db.commit()
    src = Source(direction_id=d.id, url=url, type="rss")
    db.add(src)
    db.commit()
    return src


def test_enqueue_creates_round_and_source_tasks(db_session):
    src = _mk_source(db_session, "https://ex/f")
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    assert rt is not None and rt.status == "PENDING" and rt.kind == "fetch_round"
    sub = [
        t for t in db_session.query(PipelineTask).filter_by(kind="fetch", status="PENDING").all()
        if (t.payload or {}).get("round_task_id") == rt.id
    ]
    assert len(sub) == 1 and sub[0].payload["source_id"] == src.id
    assert rt.payload["skipped_backoff"] == []


def test_round_busy_anti_overlap(db_session):
    _mk_source(db_session, "https://ex/f")
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    assert rt is not None
    # 上一轮还 PENDING（未执行）→ 不置新轮
    assert round_busy(db_session, "fetch_round")
    assert enqueue_fetch_round(db_session, triggered_by="test") is None


def test_backoff_skip_and_probe(db_session, monkeypatch):
    src = _mk_source(db_session, "https://ex/f")
    # 连续失败 3 次 → 达到阈值
    for _ in range(config.BACKOFF_FAIL_THRESHOLD):
        src.backoff_failures += 1
    db_session.commit()
    # 把已有轮次清掉，模拟上一轮已完成
    for t in db_session.query(PipelineTask).all():
        t.status = "DONE"
    db_session.commit()

    rt = enqueue_fetch_round(db_session, triggered_by="test")
    # 第一次 skip 计数=1：(1-1) % 4 == 0 → 放行探测
    assert rt is not None and rt.payload["skipped_backoff"] == []
    for t in db_session.query(PipelineTask).all():
        t.status = "DONE"
    db_session.commit()

    rt2 = enqueue_fetch_round(db_session, triggered_by="test")
    assert rt2 is not None
    skipped = rt2.payload["skipped_backoff"]
    assert len(skipped) == 1 and skipped[0]["source_id"] == src.id
    assert skipped[0]["consecutive_failures"] == config.BACKOFF_FAIL_THRESHOLD


def test_process_round_claims_and_finishes(db_session, monkeypatch):
    src = _mk_source(db_session, "https://ex/f")
    rt = enqueue_fetch_round(db_session, triggered_by="test")

    import app.pipeline.runner as runner

    class FakeStats:
        feed_entries = 1
        inserted = 1
        dup_blocked = 0
        rule_rejected = 0
        failed = 0
        guid_collisions = 0
        not_modified = False
        sanitize_passed = 1
        sanitize_rejected = 0
        error = None

    monkeypatch.setattr(runner, "fetch_source", lambda db, s: FakeStats())
    summary = process_fetch_round(db_session, rt)
    assert summary["status"] == "DONE"
    assert len(summary["sources"]) == 1
    assert rt.status == "DONE"
    src = db_session.merge(src)
    assert src.backoff_failures == 0  # 成功清零
    assert src.backoff_skips == 0

    # 已结束的轮次再 process → 幂等跳过（claim 失败）
    again = process_fetch_round(db_session, rt)
    assert again.get("skipped") is True
