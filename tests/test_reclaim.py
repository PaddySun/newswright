"""G1/W2 P0-1 测试（AC-20.2）：僵死任务回收、迟到完成 CAS 拒绝、分档阈值、挂载点。

阈值分档直接种 updated_at 值验证，不真实等待。
"""
import logging
from datetime import datetime, timedelta, timezone

import app.scheduler as sched_mod
from app.models import Direction, PipelineTask, Source
from app.pipeline.runner import (
    _finish,
    enqueue_fetch_round,
    reclaim_stale_tasks,
    round_busy,
)


def _mk_running(db, kind: str, *, age_minutes: int) -> PipelineTask:
    t = PipelineTask(kind=kind, status="RUNNING", payload={},
                     updated_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes))
    db.add(t)
    db.commit()
    return t


def _fresh(db, task):
    db.expire_all()
    return db.get(PipelineTask, task.id)


def test_stale_fetch_reclaimed_and_round_unblocked(db_session):
    """AC-20.2 主场景：超时 RUNNING fetch 任务 → 回收为 FAILED（last_error 含
    stale_reclaim）→ round_busy 不再阻塞新轮次。"""
    d = Direction(name="DS", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://ex/f", type="rss")
    db_session.add(src)
    db_session.commit()
    t = _mk_running(db_session, "fetch", age_minutes=31)
    t2 = _mk_running(db_session, "fetch_round", age_minutes=31)

    n = reclaim_stale_tasks(db_session)
    assert n == 2
    f1, f2 = _fresh(db_session, t), _fresh(db_session, t2)
    assert f1.status == "FAILED" and "stale_reclaim" in f1.last_error and f1.attempts == 1
    assert f2.status == "FAILED"

    assert not round_busy(db_session, "fetch_round")
    assert enqueue_fetch_round(db_session, triggered_by="test") is not None


def test_late_finish_rejected(db_session, caplog):
    """迟到完成被拒：任务被回收后再调 _finish → 状态不变 + WARN 日志 + 不抛异常。"""
    t = _mk_running(db_session, "fetch", age_minutes=60)
    reclaim_stale_tasks(db_session)
    with caplog.at_level(logging.WARNING, logger="newswright.pipeline"):
        _finish(db_session, t, status="DONE", stats={"inserted": 1})  # 不抛异常
    fresh = _fresh(db_session, t)
    assert fresh.status == "FAILED"
    assert "stale_reclaim" in fresh.last_error
    assert "迟到完成被拒" in caplog.text


def test_reclaim_threshold_buckets(db_session):
    """分档阈值：fetch/fetch_round/hot_round=30、score/rescore=60、write=120 各验一档。"""
    f31 = _mk_running(db_session, "fetch", age_minutes=31)
    h31 = _mk_running(db_session, "hot_round", age_minutes=31)
    s31 = _mk_running(db_session, "score", age_minutes=31)
    w31 = _mk_running(db_session, "write", age_minutes=31)
    reclaim_stale_tasks(db_session)
    assert _fresh(db_session, f31).status == "FAILED"
    assert _fresh(db_session, h31).status == "FAILED"
    assert _fresh(db_session, s31).status == "RUNNING"  # 31 < 60
    assert _fresh(db_session, w31).status == "RUNNING"  # 31 < 120

    s61 = _mk_running(db_session, "rescore", age_minutes=61)
    reclaim_stale_tasks(db_session)
    assert _fresh(db_session, s61).status == "FAILED"
    assert _fresh(db_session, w31).status == "RUNNING"  # 31 < 120

    w121 = _mk_running(db_session, "write", age_minutes=121)
    reclaim_stale_tasks(db_session)
    assert _fresh(db_session, w121).status == "FAILED"

    fresh_run = _mk_running(db_session, "fetch", age_minutes=0)
    assert reclaim_stale_tasks(db_session) == 0  # 新鲜 RUNNING 不误收
    assert _fresh(db_session, fresh_run).status == "RUNNING"


def test_scheduler_mount_reclaim(db_session):
    """挂载点：scheduler 启动回收（start() 首个 tick 前）经 SessionLocal 生效。"""
    t = _mk_running(db_session, "fetch_round", age_minutes=31)
    sched_mod._reclaim_once()
    assert _fresh(db_session, t).status == "FAILED"
