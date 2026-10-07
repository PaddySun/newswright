"""增值层降级判定单元测试（_degraded_levels）：近 24h 窗、score/write 两维度、
存在尝试且全部 FAILED 才判降级。

设计依据见 docs/design-index.md「AC-18.4」。
"""
from datetime import datetime, timedelta, timezone

from app.models import PipelineTask
from app.observability import _degraded_levels

NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


def _task(db, *, kind, status, age_hours):
    db.add(PipelineTask(kind=kind, status=status, payload={},
                        created_at=NOW - timedelta(hours=age_hours),
                        updated_at=NOW - timedelta(hours=age_hours)))
    db.commit()


def test_degraded_window_is_24h_rolling(db_session):
    """窗外（25h 前）的 FAILED 不触发降级（近 24h 窗语义）。"""
    _task(db_session, kind="score", status="FAILED", age_hours=25)
    assert _degraded_levels(db_session, NOW) == []


def test_degraded_single_dimension_write_only(db_session):
    """仅写作维度失败：degraded 清单只含 writing（维度完整性）。"""
    _task(db_session, kind="write", status="FAILED", age_hours=1)
    assert _degraded_levels(db_session, NOW) == ["writing"]


def test_degraded_ignores_non_value_added_kinds(db_session):
    """fetch 等基本层任务不进入增值降级判定（判定域=score/write）。"""
    _task(db_session, kind="fetch", status="DONE", age_hours=2)
    assert _degraded_levels(db_session, NOW) == []


def test_degraded_pending_tasks_are_not_attempts(db_session):
    """PENDING 任务不是「已尝试」：仅有 PENDING/排队态任务不触发降级
    （尝试=DONE/FAILED 终态轮）。"""
    _task(db_session, kind="score", status="PENDING", age_hours=1)
    assert _degraded_levels(db_session, NOW) == []


def test_degraded_done_task_prevents_degradation(db_session):
    """同维度近 24h 存在 DONE（有成功轮）→ 不判降级。"""
    _task(db_session, kind="score", status="DONE", age_hours=2)
    _task(db_session, kind="score", status="FAILED", age_hours=1)
    assert _degraded_levels(db_session, NOW) == []


def test_degraded_cross_kind_done_does_not_rescue(db_session):
    """fetch 维度的成功不得 rescue score 维度的失败（done 域按 kind 隔离）。"""
    _task(db_session, kind="fetch", status="DONE", age_hours=2)
    _task(db_session, kind="score", status="FAILED", age_hours=1)
    assert _degraded_levels(db_session, NOW) == ["scoring"]
