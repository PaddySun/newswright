"""任务流呈现面契约测试（GET /api/tasks 增列——UI2 W0b，服务 P5 写作
工作台任务流）。

覆盖口径：行增 author_name（payload.author_id 联表，取不到为 null）与
article_id（write 任务终态回填后有值，其余 null）；write DONE 回填经打桩
写作管线实证（run_write 桩返回成文 run → 任务行直链文章）；SKIP 终态
article_id=null；既有字段（id/kind/status/attempts/payload/last_error/
updated_at）不回归。设计依据见 docs/design-index.md「AC-11.7」。
"""
from app.models import Author, PipelineTask
from app.pipeline.runner import process_write_tasks


class _StubRun:
    """打桩 run_write 的返回 run：成文（WRITE+article_id）/跳过（SKIP）两形态。"""

    def __init__(self, *, decision="WRITE", article_id=None):
        self.status = "OK"
        self.decision = decision
        self.article_id = article_id
        self.error = None
        self.id = 501
        self.payload = {"rank": {}}


def _mk_task(db, kind="write", payload=None) -> PipelineTask:
    t = PipelineTask(kind=kind, status="PENDING", payload=payload or {})
    db.add(t)
    db.commit()
    return t


def _get_task_row(client, task_id) -> dict:
    rows = client.get("/api/tasks").json()
    return next(x for x in rows if x["id"] == task_id)


def test_write_done_task_links_author_and_article(auth_client, db_session,
                                                  monkeypatch):
    """write DONE（成文）任务行：author_name 联表 + article_id 直链（终态回填实证）。"""
    a = Author(name="直链作者", model="m")
    db_session.add(a)
    db_session.commit()
    monkeypatch.setattr("app.authors.writer.run_write",
                        lambda db, au, **kw: _StubRun(decision="WRITE",
                                                      article_id=777))
    task = _mk_task(db_session, payload={"author_id": a.id, "triggered_by": "api"})
    assert process_write_tasks(db_session)[0]["status"] == "DONE"

    row = _get_task_row(auth_client, task.id)
    assert row["author_name"] == "直链作者"
    assert row["article_id"] == 777


def test_write_skip_task_keeps_article_id_null(auth_client, db_session,
                                               monkeypatch):
    """SKIP 终态任务行 article_id=null（跳过不成文，无文章可链）。"""
    a = Author(name="跳过作者", model="m")
    db_session.add(a)
    db_session.commit()
    monkeypatch.setattr("app.authors.writer.run_write",
                        lambda db, au, **kw: _StubRun(decision="SKIP"))
    task = _mk_task(db_session, payload={"author_id": a.id, "triggered_by": "api"})
    process_write_tasks(db_session)

    row = _get_task_row(auth_client, task.id)
    assert row["author_name"] == "跳过作者"
    assert row["article_id"] is None


def test_pending_write_task_has_null_article_id(auth_client, db_session):
    """未执行的 write 任务（PENDING）行 article_id=null（终态回填前无值）。"""
    a = Author(name="待跑作者", model="m")
    db_session.add(a)
    db_session.commit()
    task = _mk_task(db_session, payload={"author_id": a.id})

    row = _get_task_row(auth_client, task.id)
    assert row["author_name"] == "待跑作者"
    assert row["article_id"] is None


def test_task_without_author_id_has_null_author_name(auth_client, db_session):
    """无 author_id 的任务（fetch 轮）行 author_name=null / article_id=null。"""
    task = _mk_task(db_session, kind="fetch", payload={"round": 3})

    row = _get_task_row(auth_client, task.id)
    assert row["author_name"] is None
    assert row["article_id"] is None


def test_task_with_deleted_author_has_null_author_name(auth_client, db_session):
    """payload.author_id 指向已删作者行 → author_name=null（取不到不呈现）。"""
    task = _mk_task(db_session, payload={"author_id": 88888})

    row = _get_task_row(auth_client, task.id)
    assert row["author_name"] is None


def test_tasks_row_keeps_existing_fields(auth_client, db_session):
    """既有字段不回归：id/kind/status/attempts/payload/last_error/updated_at
    原样保留（增列零破坏）。"""
    a = Author(name="既有字段作者", model="m")
    db_session.add(a)
    db_session.commit()
    task = _mk_task(db_session, kind="write",
                    payload={"author_id": a.id, "triggered_by": "api"})

    row = _get_task_row(auth_client, task.id)
    assert set(row) == {"id", "kind", "status", "attempts", "payload",
                        "last_error", "updated_at", "author_name", "article_id"}
    assert row["kind"] == "write"
    assert row["status"] == "PENDING"
    assert row["attempts"] == 0
    assert row["payload"] == {"author_id": a.id, "triggered_by": "api"}
    assert row["last_error"] is None
