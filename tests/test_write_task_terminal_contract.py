"""write 任务终态契约测试：执行器的失败承载与任务构造。

覆盖口径（AC-11.7 异步写作 + F2 write 202 异步链，设计依据见
docs/design-index.md「AC-11.7」）：
- run_write 正常返回但 status=FAILED 的 run：任务终态 FAILED（不是 DONE 伪装），
  失败原因经 last_error 可见（失败原因可见性 = AC-11.7 明确反馈条款）；
- run_write 收到的 db 会话即任务执行会话（实参透传契约）；
- rank_meta 无 domain_capped 时 stats 哨兵 = 0（计量空域零值，不得虚高）；
- write_task 建的任务 kind=write（任务 kind 枚举域，技术书 §4.2 状态机）。
"""
import app.pipeline.runner as runner_mod
from app.models import Author, PipelineTask
from app.pipeline.runner import process_write_tasks, write_task


class _FakeRun:
    def __init__(self, status="OK", payload=None):
        self.status = status
        self.decision = "WRITE" if status == "OK" else "SKIP"
        self.article_id = None
        self.error = None if status == "OK" else "写作管线失败：门禁拒绝"
        self.id = 202
        self.payload = payload if payload is not None else {"rank": {"domain_capped": 2}}


def _make_pending(db, author_id: int) -> PipelineTask:
    t = PipelineTask(kind="write", status="PENDING",
                     payload={"author_id": author_id, "triggered_by": "api"})
    db.add(t)
    db.commit()
    return t


def test_failed_run_marks_task_failed_with_error(db_session, monkeypatch):
    """run_write 返回 FAILED run（非异常路径）→ 任务 FAILED + last_error 承载原因。"""
    a = Author(name="失败承载作者", model="m")
    db_session.add(a)
    db_session.commit()
    monkeypatch.setattr("app.authors.writer.run_write",
                        lambda db, au, **kw: _FakeRun(status="FAILED"))
    task = _make_pending(db_session, a.id)
    out = process_write_tasks(db_session)
    assert out[0]["status"] == "FAILED"
    refreshed = db_session.get(PipelineTask, task.id)
    assert refreshed.status == "FAILED"
    assert "写作管线失败" in (refreshed.last_error or "")


def test_ok_run_passes_session_and_zero_domain_capped(db_session, monkeypatch):
    """实参透传：run_write 收到的 db 即执行会话；rank 无 domain_capped → stats=0。"""
    a = Author(name="透传作者", model="m")
    db_session.add(a)
    db_session.commit()
    seen = {}

    def fake_run(db, au, **kw):
        seen["db"] = db
        seen["kwargs"] = kw
        return _FakeRun(payload={"rank": {}})

    monkeypatch.setattr("app.authors.writer.run_write", fake_run)
    task = _make_pending(db_session, a.id)
    out = process_write_tasks(db_session)
    assert out[0]["status"] == "DONE"
    assert seen["db"] is db_session
    refreshed = db_session.get(PipelineTask, task.id)
    assert refreshed.payload["stats"]["domain_capped"] == 0


def test_write_task_creates_write_kind_task(db_session, monkeypatch):
    """write_task 同步入口建的任务 kind=write（kind 枚举域）。"""
    a = Author(name="同步入口作者", model="m")
    db_session.add(a)
    db_session.commit()
    monkeypatch.setattr("app.authors.writer.run_write",
                        lambda db, au, **kw: _FakeRun())
    out = write_task(db_session, a.id, triggered_by="test")
    assert out["status"] == "DONE"
    task = db_session.get(PipelineTask, out["task_id"])
    assert task.kind == "write"
