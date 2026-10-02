"""G1/W3 P1-1 测试：异常路径先 db.rollback() 再落 FAILED 终态。

构造：抓取器往会话塞一条违反 NOT NULL 的脏对象后抛异常（模拟会话损坏/rollback-only）——
若无 P1-1 修复，_finish 的 commit 会连带 flush 脏对象失败，任务卡 RUNNING（只能靠
P0-1 兜底）；修复后 except 先回滚，终态干净落库。
"""
from app.models import Direction, Item, PipelineTask, Source
from app.pipeline.runner import enqueue_fetch_round, fetch_round, process_fetch_round


def _mk_direction_and_source(db, url: str) -> Source:
    d = Direction(name="DS", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url=url, type="rss")
    db.add(src)
    db.commit()
    return src


def _corrupting_fetcher(db, src):
    """塞脏对象（guid NOT NULL）再抛异常：会话内存在待 flush 的毒行。"""
    db.add(Item(source_id=src.id, guid=None, title="poison"))
    raise RuntimeError("模拟抓取途中会话损坏")


def test_process_round_except_lands_failed_with_dirty_session(db_session, monkeypatch):
    src = _mk_direction_and_source(db_session, "https://ex/f")
    import app.pipeline.runner as runner

    monkeypatch.setattr(runner, "fetch_source", _corrupting_fetcher)
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    summary = process_fetch_round(db_session, rt)

    assert summary["status"] == "FAILED"
    assert summary["sources"][0]["status"] == "FAILED"
    assert "RuntimeError" in summary["sources"][0]["error"]
    db_session.expire_all()
    t = db_session.get(PipelineTask, summary["sources"][0]["task_id"])
    assert t.status == "FAILED"  # 卡 RUNNING = P1-1 未修
    assert db_session.query(Item).count() == 0  # 脏行被回滚，未落库


def test_fetch_round_except_lands_failed_with_dirty_session(db_session, monkeypatch):
    src = _mk_direction_and_source(db_session, "https://ex/f")
    import app.pipeline.runner as runner

    monkeypatch.setattr(runner, "fetch_source", _corrupting_fetcher)
    summary = fetch_round(db_session, triggered_by="test")

    assert summary["sources"][0]["status"] == "FAILED"
    assert "RuntimeError" in summary["sources"][0]["error"]
    db_session.expire_all()
    t = db_session.get(PipelineTask, summary["sources"][0]["task_id"])
    assert t.status == "FAILED"
    assert db_session.query(Item).count() == 0
