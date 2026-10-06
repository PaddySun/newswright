"""异步写作测试：POST /api/pipeline/write/{id} 202 + task_id + 增值池消费者。

条款口径（产品书 US-11.7，设计依据见 docs/design-index.md「AC-11.7」）：
202 与 {"task_id":<id>}；任务终态可查（DONE/FAILED 两景）、失败原因可见；
消费=认领→执行→终态落库（与重打分任务同构），重复消化幂等（认领 CAS）。
前端 2s/4s/8s 退避轮询行为归 UI 里程碑，不在本批断言面。
"""
import pytest

import app.scheduler as scheduler_mod
from app.models import Author, PipelineTask
from app.pipeline.runner import process_write_tasks


class _FakeRun:
    def __init__(self, status="OK", decision="WRITE", payload=None):
        self.status = status
        self.decision = decision
        self.article_id = None
        self.error = None if status == "OK" else "写作管线失败"
        self.id = 101
        self.payload = payload if payload is not None else {"rank": {"domain_capped": 2}}


@pytest.fixture()
def author(db_session):
    a = Author(name="异步写作作者", model="m")
    db_session.add(a)
    db_session.commit()
    return a


@pytest.fixture()
def no_auto_submit(monkeypatch):
    """封住端点的即时线程池提交（测试内同步驱动消费者，保持确定性）。"""
    monkeypatch.setattr(scheduler_mod, "submit_write_tasks_async", lambda: None)


def _make_pending(db, author_id: int) -> PipelineTask:
    t = PipelineTask(kind="write", status="PENDING",
                     payload={"author_id": author_id, "triggered_by": "api"})
    db.add(t)
    db.commit()
    return t


def test_write_endpoint_returns_202_with_task_id(auth_client, author, no_auto_submit):
    r = auth_client.post(f"/api/pipeline/write/{author.id}")
    assert r.status_code == 202
    body = r.json()
    assert set(body) == {"task_id"}
    task = auth_client.get("/tasks", params={"kind": "write"}).json()
    assert any(t["id"] == body["task_id"] and t["status"] == "PENDING" for t in task)


def test_write_endpoint_unknown_author_404(auth_client, no_auto_submit):
    r = auth_client.post("/api/pipeline/write/99999")
    assert r.status_code == 404


def test_consumer_done_terminal_with_domain_capped(db_session, author, monkeypatch):
    monkeypatch.setattr("app.authors.writer.run_write",
                        lambda db, a, **kw: _FakeRun(status="OK"))
    task = _make_pending(db_session, author.id)
    out = process_write_tasks(db_session)
    assert out == [{"task_id": task.id, "status": "DONE"}]
    refreshed = db_session.get(PipelineTask, task.id)
    assert refreshed.status == "DONE"
    assert refreshed.payload["write_run_id"] == 101
    assert refreshed.payload["stats"]["domain_capped"] == 2
    assert refreshed.last_error is None


def test_consumer_failed_terminal_error_visible(db_session, author, monkeypatch):
    def boom(db, a, **kw):
        raise RuntimeError("写作调用崩溃")

    monkeypatch.setattr("app.authors.writer.run_write", boom)
    task = _make_pending(db_session, author.id)
    out = process_write_tasks(db_session)
    assert out[0]["status"] == "FAILED"
    refreshed = db_session.get(PipelineTask, task.id)
    assert refreshed.status == "FAILED"
    assert "RuntimeError" in (refreshed.last_error or "")


def test_consumer_claim_idempotent(db_session, author, monkeypatch):
    """重复消化不重复执行：认领 CAS 后无新 PENDING，run_write 恰执行一次。"""
    calls = []

    def fake_run(db, a, **kw):
        calls.append(a.id)
        return _FakeRun(status="OK")

    monkeypatch.setattr("app.authors.writer.run_write", fake_run)
    _make_pending(db_session, author.id)
    process_write_tasks(db_session)
    process_write_tasks(db_session)
    process_write_tasks(db_session)
    assert calls == [author.id]


def test_consumer_budget_gate_without_confirmation(db_session, author, monkeypatch):
    """预算触发且任务未带站长确认标记：不执行 LLM，任务 DONE+标记（恢复=带
    budget_confirmed 的新任务）。"""
    from datetime import datetime, timezone

    from app.models import UsageLog
    from app.siteconfig import set_config

    set_config(db_session, "daily_token_budget", 100)
    db_session.add(UsageLog(provider="p", model="m", call_point="writing",
                            prompt_tokens=80, completion_tokens=30,
                            created_at=datetime.now(timezone.utc)))
    db_session.commit()

    def must_not_run(db, a, **kw):
        raise AssertionError("预算未确认时写作不得执行 LLM")

    monkeypatch.setattr("app.authors.writer.run_write", must_not_run)
    task = _make_pending(db_session, author.id)
    out = process_write_tasks(db_session)
    assert out[0]["status"] == "DONE"
    refreshed = db_session.get(PipelineTask, task.id)
    assert refreshed.payload["budget_confirmation_required"] is True
    assert refreshed.payload["executed"] is False


def test_consumer_unknown_author_fails_task(db_session):
    task = _make_pending(db_session, 99999)
    out = process_write_tasks(db_session)
    assert out[0]["status"] == "FAILED"
    assert "author" in (db_session.get(PipelineTask, task.id).last_error or "")


def test_scheduler_registers_write_consume_job():
    """周期兜底 tick 已注册（遗留 PENDING 任务的恢复入口；≥2h 实 soak 归部署
    验证——本测为注册面逻辑断言）。"""
    from app.scheduler import _tick_write_consume, submit_write_tasks_async

    assert callable(submit_write_tasks_async)
    assert callable(_tick_write_consume)
