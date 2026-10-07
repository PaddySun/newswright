"""fetch 轮末通知接线测试：聚合哨兵与磁盘检查在轮末被执行 + write 消费者 kind 域。

覆盖口径（R7 采集面聚合哨兵 + R4 磁盘阈值 + AC-20.2，设计依据见
docs/design-index.md「R7」「R4」）：
- fetch 轮收尾顺带执行聚合哨兵检查与磁盘阈值检查（轮末通知链的接线面）；
- write 消费者只消化 kind=write 的 PENDING 任务（其他 kind 的 PENDING 任务
  不得被写作消费者认领执行）。
"""
from app.models import Direction, PipelineTask
from app.pipeline.runner import enqueue_fetch_round, process_fetch_round, process_write_tasks


def test_fetch_round_runs_sentinel_and_disk_checks(db_session, monkeypatch):
    calls = []
    monkeypatch.setattr("app.notify.triggers.check_collective_sentinel",
                        lambda db: calls.append(("sentinel", db)) or {"degraded_sources_count": 0})
    monkeypatch.setattr("app.notify.triggers.check_disk_usage",
                        lambda db: calls.append(("disk", db)) or {"sent": False})
    db_session.add(Direction(name="接线方向", prompt="p", prompt_version=1, threshold=60))
    db_session.commit()
    round_task = enqueue_fetch_round(db_session, triggered_by="test")
    summary = process_fetch_round(db_session, round_task)
    assert summary["status"] == "DONE"
    assert [(name, db is db_session) for name, db in calls] == [("sentinel", True), ("disk", True)]


def test_process_write_tasks_leaves_other_kinds_pending(db_session, monkeypatch):
    """PENDING 的 rescore 任务不被 write 消费者认领（kind 域隔离）。"""
    monkeypatch.setattr("app.authors.writer.run_write",
                        lambda db, au, **kw: (_ for _ in ()).throw(
                            AssertionError("write 消费者不得执行非 write 任务")))
    rescore = PipelineTask(kind="rescore", status="PENDING",
                           payload={"direction_id": 1, "scope": "all"})
    db_session.add(rescore)
    db_session.commit()
    out = process_write_tasks(db_session)
    assert out == []
    assert db_session.get(PipelineTask, rescore.id).status == "PENDING"
