"""管线体检载荷字段值测试（/api/stats/pipeline）：pending/stale/items/scored/
passed 计量、逐源最近成功、聚合哨兵 hard_failed 计入。

设计依据见 docs/design-index.md「AC-18.3」「AC-19.3」「AC-19.4」。
"""
from datetime import datetime, timedelta, timezone

from app.models import Direction, Item, PipelineTask, ScoreResult, Source

NOW = datetime.now(timezone.utc)


def _seed_direction_with_source(db, *, failure_level="none"):
    d = Direction(name="体检载荷方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://payload.com/rss",
                 failure_level=failure_level)
    db.add(src)
    db.commit()
    return d, src


def _task(db, *, kind, status, age_minutes, payload=None, last_error=None):
    db.add(PipelineTask(kind=kind, status=status, payload=payload or {},
                        last_error=last_error,
                        created_at=NOW - timedelta(minutes=age_minutes),
                        updated_at=NOW - timedelta(minutes=age_minutes)))


def _item(db, direction, source, *, guid, age_minutes):
    item = Item(source_id=source.id, guid=guid, url=f"https://x.com/{guid}",
                title="t", content_text="正文", fetch_status="FETCHED",
                direction_id=direction.id, sanitize_status="PASSED",
                fetched_at=NOW - timedelta(minutes=age_minutes))
    db.add(item)
    db.flush()
    return item


def _score(db, direction, item, *, status="OK", passed=True, age_minutes):
    db.add(ScoreResult(item_id=item.id, direction_id=direction.id,
                       quality_score=90, relevance_score=95, band="high",
                       reason="r", prompt_version=direction.prompt_version,
                       model="m", passed=passed, status=status,
                       created_at=NOW - timedelta(minutes=age_minutes)))


def test_stats_pending_count_exact(auth_client, db_session):
    """pending_count 只计 PENDING 且计数精确（计量本体）。"""
    d, src = _seed_direction_with_source(db_session)
    _task(db_session, kind="fetch", status="DONE", age_minutes=5,
          payload={"source_id": src.id})
    for i in range(3):
        _task(db_session, kind="score", status="PENDING", age_minutes=5)
    db_session.commit()
    assert auth_client.get("/api/stats/pipeline").json()["pending_count"] == 3


def test_stats_stale_count_window_and_filters(auth_client, db_session):
    """stale_count_24h：只计近 24h 内 FAILED 且 last_error 以 stale_reclaim:
    开头的任务（P0-1 回收语义计量本体）。窗外种子取 24.5h——紧贴窗界外侧，
    防窗宽化（24h→25h）漏杀。"""
    d, src = _seed_direction_with_source(db_session)
    for i in range(2):  # 窗内 stale 两笔
        _task(db_session, kind="fetch", status="FAILED", age_minutes=60,
              last_error=f"stale_reclaim:{i}")
    _task(db_session, kind="fetch", status="FAILED", age_minutes=60,
          last_error="ProviderError: down")  # 非 stale 失败不得混入
    _task(db_session, kind="fetch", status="DONE", age_minutes=60,
          last_error="stale_reclaim:9")  # 非 FAILED 不得混入
    _task(db_session, kind="fetch", status="FAILED", age_minutes=24 * 60 + 30,
          last_error="stale_reclaim:99")  # 窗外（24h 外 30 分钟）不得混入
    db_session.commit()
    assert auth_client.get("/api/stats/pipeline").json()["stale_count_24h"] == 2


def test_stats_stale_count_zero_when_none(auth_client, db_session):
    _seed_direction_with_source(db_session)
    assert auth_client.get("/api/stats/pipeline").json()["stale_count_24h"] == 0


def test_stats_items_24h_counts_window_items(auth_client, db_session):
    """items_24h 只计近 24h 抓取条目（窗外不计；窗外种子取 24.5h 防窗宽化漏杀）。"""
    d, src = _seed_direction_with_source(db_session)
    _item(db_session, d, src, guid="i1", age_minutes=60)
    _item(db_session, d, src, guid="i2", age_minutes=120)
    _item(db_session, d, src, guid="i3", age_minutes=24 * 60 + 30)
    db_session.commit()
    assert auth_client.get("/api/stats/pipeline").json()["items_24h"] == 2


def test_stats_scored_and_passed_24h(auth_client, db_session):
    """scored_24h 只计窗内 OK 打分；passed_24h 只计其中过线行（计量本体）。"""
    d, src = _seed_direction_with_source(db_session)
    i1 = _item(db_session, d, src, guid="s1", age_minutes=60)
    i2 = _item(db_session, d, src, guid="s2", age_minutes=60)
    i3 = _item(db_session, d, src, guid="s3", age_minutes=120)
    i4 = _item(db_session, d, src, guid="s4", age_minutes=60)
    _score(db_session, d, i1, passed=True, age_minutes=60)      # scored+passed
    _score(db_session, d, i2, passed=False, age_minutes=60)     # scored only
    _score(db_session, d, i3, passed=True, age_minutes=120)     # scored+passed
    _score(db_session, d, i4, status="FAILED", passed=True, age_minutes=60)  # 两者皆非
    _score(db_session, d, i1, passed=True, age_minutes=24 * 60 + 30)  # 窗外不得混入
    db_session.commit()
    body = auth_client.get("/api/stats/pipeline").json()
    assert body["scored_24h"] == 3
    assert body["passed_24h"] == 2


def test_stats_scored_passed_zero_when_none(auth_client, db_session):
    """无打分行时空域哨兵为 0（items/stale 同批断言）。"""
    _seed_direction_with_source(db_session)
    body = auth_client.get("/api/stats/pipeline").json()
    assert body["scored_24h"] == 0
    assert body["passed_24h"] == 0
    assert body["items_24h"] == 0
    assert body["pending_count"] == 0


def test_stats_per_source_last_success_is_latest(auth_client, db_session):
    """逐源最近成功抓取取该源最新 DONE 轮；未知 source_id 不得破坏聚合。"""
    d, src = _seed_direction_with_source(db_session)
    _task(db_session, kind="fetch", status="DONE", age_minutes=10,
          payload={"source_id": src.id})  # 旧轮（先插入）
    _task(db_session, kind="fetch", status="DONE", age_minutes=5,
          payload={"source_id": src.id})  # 新轮：应为 per_source 取值
    _task(db_session, kind="fetch", status="DONE", age_minutes=7,
          payload={"source_id": 99999})   # 已不存在的源：跳过不崩溃
    db_session.commit()
    body = auth_client.get("/api/stats/pipeline").json()
    value = body["per_source_last_success"][str(src.id)]
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age = (NOW - parsed).total_seconds() / 60
    assert 2 <= age <= 8  # 新轮（约 5 分钟前）而非旧轮（约 10 分钟前）


def test_stats_sentinel_counts_hard_failed_sources(auth_client, db_session):
    """聚合哨兵：hard_failed 启用源计入 degraded_sources_count（R7 钉面）。"""
    _seed_direction_with_source(db_session, failure_level="hard_failed")
    body = auth_client.get("/api/stats/pipeline").json()
    assert body["degraded_sources_count"] == 1
    assert body["total_enabled_sources"] == 1
