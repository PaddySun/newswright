"""未评分条目附带域测试：触发条件、条目域与方向域。

覆盖口径（AC-21.1 LLM 故障稳态的呈现侧语义，设计依据见
docs/design-index.md「AC-21.1」）：
- 触发条件 = 近期（24h 内）存在 kind=score 且 status=FAILED 的任务：窗外失败、
  其他 kind 失败、无失败三种形态都不附带；
- 条目域 = FETCHED + 零信任过滤通过（PASSED）+ 未判重（duplicate_of 空）且
  尚无 OK 打分行——已评分条目不得伪装"暂未评分"；
- 方向域 = 该方向启用源的条目；其他方向条目与停用源条目不混入。
"""
from datetime import datetime, timedelta, timezone

from app.api.routes import _unscored_entries
from app.models import Direction, Item, PipelineTask, ScoreResult, Source


def _seed_direction(db, name, *, enabled=True):
    d = Direction(name=name, prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url=f"https://example.com/{name}",
                 enabled=enabled)
    db.add(src)
    db.commit()
    return d, src


def _item(db, src, guid, *, fetch_status="FETCHED", sanitize="PASSED", dup=None):
    it = Item(source_id=src.id, guid=guid, url=f"https://example.com/{guid}",
              title=f"标题{guid}", content_text="正文" * 50,
              fetch_status=fetch_status, direction_id=src.direction_id,
              sanitize_status=sanitize, duplicate_of=dup)
    db.add(it)
    db.commit()
    return it


def _score_failed_task(db, *, kind="score", status="FAILED", hours_ago=1):
    t = PipelineTask(kind=kind, status=status, payload={},
                     updated_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago))
    db.add(t)
    db.commit()
    return t


def test_recent_score_failure_triggers_unscored(db_session):
    """24h 内 score 失败 → 附带未评分条目（触发链正常态）。"""
    d, src = _seed_direction(db_session, "触发方向")
    _item(db_session, src, "a")
    _score_failed_task(db_session)
    assert [u["id"] for u in _unscored_entries(db_session, d.id)] != []


def test_stale_or_other_kind_or_done_failures_do_not_trigger(db_session):
    """窗外失败 / 其他 kind 失败 / DONE 任务都不触发附带。"""
    d, src = _seed_direction(db_session, "不触发方向")
    _item(db_session, src, "a")
    _score_failed_task(db_session, hours_ago=25)  # 窗外
    assert _unscored_entries(db_session, d.id) == []
    _score_failed_task(db_session, kind="fetch")  # 非 score
    assert _unscored_entries(db_session, d.id) == []
    _score_failed_task(db_session, status="DONE")  # 非失败
    assert _unscored_entries(db_session, d.id) == []


def test_only_clean_unduplicated_items_attached(db_session):
    """条目域：仅 FETCHED+PASSED+未判重条目附带。"""
    d, src = _seed_direction(db_session, "条目域方向")
    clean = _item(db_session, src, "clean")
    _item(db_session, src, "ruled", fetch_status="REJECTED_RULED")
    _item(db_session, src, "dirty", sanitize="REJECTED")
    _item(db_session, src, "dup", dup=clean.id)
    _score_failed_task(db_session)
    ids = [u["id"] for u in _unscored_entries(db_session, d.id)]
    assert ids == [clean.id]


def test_already_scored_items_not_attached(db_session):
    """已有 OK 打分行的条目不得伪装暂未评分（真实低分/无分不伪装）。"""
    d, src = _seed_direction(db_session, "已评分方向")
    scored = _item(db_session, src, "scored")
    db_session.add(ScoreResult(item_id=scored.id, direction_id=d.id, model="m",
                               status="OK", passed=True, relevance_score=90))
    db_session.commit()
    _score_failed_task(db_session)
    assert _unscored_entries(db_session, d.id) == []


def test_scoped_to_direction_enabled_sources(db_session):
    """方向域：其他方向条目与停用源条目不混入（源域 enabled 过滤在方向域）。"""
    d_a, _ = _seed_direction(db_session, "查询方向")
    d_b, src_b = _seed_direction(db_session, "另方向")
    _item(db_session, src_b, "other-dir")
    _score_failed_task(db_session)
    # 另方向条目不得出现在查询方向的附带里
    assert _unscored_entries(db_session, d_a.id) == []
    # 停用源方向：方向域查询不含停用源条目
    d_c, src_c = _seed_direction(db_session, "停用源方向", enabled=False)
    disabled = _item(db_session, src_c, "disabled-src")
    assert all(u["id"] != disabled.id for u in _unscored_entries(db_session, d_c.id))
    # 全局态（无 direction_id）不做源过滤（实现域：附带面全局开放）
    ids = {u["id"] for u in _unscored_entries(db_session, None)}
    assert ids != set()
