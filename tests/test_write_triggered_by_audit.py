"""write_run.triggered_by 审计值域契约测试（AC-18.1 审计值域补句，
2026-10-08 拍板条款）。

覆盖口径（设计依据见 docs/design-index.md「AC-18.1」）：write_run.triggered_by
为审计必填值（api/manual/scheduler 之一），终值不得为空或回退漂移——

- 同步入口 write_task 的 triggered_by 实参原样进入任务 payload 并透传
  run_write，最终落 WriteRun.triggered_by（api 路径与 manual 缺省路径）；
- 任务 payload 缺键/值空时回退 "manual"（审计回退语义——不得落 None）；
- 写作链走 JSON 管线（run_pipeline_write）与旧路线（run_write）两条落库路径
  均承载同一审计终值。

网络纪律：FakeProviderPipeline 脚本化输出（落 SKIP 即可触发落库），零出网；
生产代码零改动。
"""
import pytest

import app.authors.writer as wr
import app.pipeline.runner as runner_mod
from app.models import Author, WriteRun


@pytest.fixture()
def audit_author(db_session):
    a = Author(name="审计作者", model="fake-model")
    db_session.add(a)
    db_session.commit()
    return a


def _fake_run_write(db, author, *, triggered_by="manual", **kw):
    """轻量 run_write 替身：审计透传即落库（断言面=终值，不触发模型调用）。"""
    run = WriteRun(author_id=author.id, triggered_by=triggered_by,
                   reading_set_item_ids=[], payload={}, prompt_snapshot="",
                   model=author.model, status="OK", decision="SKIP",
                   skip_reason="审计替身")
    db.add(run)
    db.commit()
    return run


def test_write_task_api_triggered_by_reaches_write_run(db_session, audit_author,
                                                       monkeypatch):
    """api 触发路径：triggered_by="api" 审计终值落库（不得漂移）。"""
    monkeypatch.setattr(wr, "run_write",
                        lambda db, author, **kw: _fake_run_write(db, author, **kw))
    out = runner_mod.write_task(db_session, audit_author.id, triggered_by="api")
    assert out["status"] == "DONE"
    run = db_session.query(WriteRun).order_by(WriteRun.id.desc()).first()
    assert run.triggered_by == "api"


def test_write_task_manual_default_reaches_write_run(db_session, audit_author,
                                                     monkeypatch):
    """manual 缺省路径：入口缺省实参经 payload 透传后终值恒 "manual"。"""
    monkeypatch.setattr(wr, "run_write",
                        lambda db, author, **kw: _fake_run_write(db, author, **kw))
    out = runner_mod.write_task(db_session, audit_author.id)
    assert out["status"] == "DONE"
    run = db_session.query(WriteRun).order_by(WriteRun.id.desc()).first()
    assert run.triggered_by == "manual"


def test_execute_task_falls_back_to_manual_when_payload_missing(db_session,
                                                                audit_author,
                                                                monkeypatch):
    """任务 payload 缺 triggered_by 键：执行侧回退 manual（审计必填——不得落 None）。"""
    from app.models import PipelineTask

    monkeypatch.setattr(wr, "run_write",
                        lambda db, author, **kw: _fake_run_write(db, author, **kw))
    task = PipelineTask(kind="write", status="PENDING",
                        payload={"author_id": audit_author.id})
    db_session.add(task)
    db_session.commit()
    runner_mod._execute_write_task(db_session, task)
    run = db_session.query(WriteRun).order_by(WriteRun.id.desc()).first()
    assert run.triggered_by == "manual"


def test_execute_task_empty_payload_value_falls_back_to_manual(db_session,
                                                               audit_author,
                                                               monkeypatch):
    """payload triggered_by 值为空（None）：回退 manual（or 兜底审计语义）。"""
    from app.models import PipelineTask

    monkeypatch.setattr(wr, "run_write",
                        lambda db, author, **kw: _fake_run_write(db, author, **kw))
    task = PipelineTask(kind="write", status="PENDING",
                        payload={"author_id": audit_author.id,
                                 "triggered_by": None})
    db_session.add(task)
    db_session.commit()
    runner_mod._execute_write_task(db_session, task)
    run = db_session.query(WriteRun).order_by(WriteRun.id.desc()).first()
    assert run.triggered_by == "manual"


def test_scheduler_path_value_flows_through(db_session, audit_author,
                                            monkeypatch):
    """scheduler 触发路径：值原样透传（审计值域含 scheduler）。"""
    monkeypatch.setattr(wr, "run_write",
                        lambda db, author, **kw: _fake_run_write(db, author, **kw))
    out = runner_mod.write_task(db_session, audit_author.id,
                                triggered_by="scheduler")
    assert out["status"] == "DONE"
    run = db_session.query(WriteRun).order_by(WriteRun.id.desc()).first()
    assert run.triggered_by == "scheduler"


def test_pipeline_route_carries_triggered_by(db_session, audit_author):
    """JSON 管线路径：run_pipeline_write 创建的 WriteRun 审计终值原样落库
    （author.json 缺失走 FAILED 落库路径——审计值在失败落库时同样承载）。"""
    from app.authors.pipeline import run_pipeline_write

    run = run_pipeline_write(db_session, audit_author, triggered_by="api")
    assert run.triggered_by == "api"
    run2 = run_pipeline_write(db_session, audit_author, triggered_by="scheduler")
    assert run2.triggered_by == "scheduler"
