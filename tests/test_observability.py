"""管线体检端点测试（/api/stats/pipeline，会话守卫）：字段逐项 + 聚合哨兵。

设计依据见 docs/design-index.md「AC-18.3」「AC-19.3」。
"""
from datetime import datetime, timedelta, timezone

from app.models import Direction, Item, PipelineTask, ScoreResult, Source


def _seed_pipeline_data(db):
    now = datetime.now(timezone.utc)
    d = Direction(name="体检方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src_ok = Source(direction_id=d.id, url="https://ok.com/rss")
    src_bad = Source(direction_id=d.id, url="https://bad.com/rss",
                     failure_level="suspect")
    db.add_all([src_ok, src_bad])
    db.commit()
    db.add(PipelineTask(kind="fetch", status="DONE",
                        payload={"source_id": src_ok.id, "url": src_ok.url},
                        created_at=now - timedelta(minutes=10),
                        updated_at=now - timedelta(minutes=10)))
    db.add(PipelineTask(kind="fetch", status="RUNNING",
                        payload={"source_id": src_bad.id, "url": src_bad.url},
                        created_at=now - timedelta(minutes=40)))
    item = Item(source_id=src_ok.id, guid="g1", url="https://ok.com/a",
                title="t", content_text="正文", fetch_status="FETCHED",
                direction_id=d.id, sanitize_status="PASSED")
    db.add(item)
    db.flush()
    db.add(ScoreResult(item_id=item.id, direction_id=d.id, quality_score=90,
                       relevance_score=95, band="high", reason="r",
                       prompt_version=d.prompt_version, model="m",
                       passed=True, status="OK"))
    db.commit()
    return d, src_ok, src_bad, item


def test_stats_pipeline_requires_session(api_client, db_session):
    r = api_client.get("/api/stats/pipeline")
    assert r.status_code == 401


def test_stats_pipeline_fields_pinned(auth_client, db_session):
    """字段逐项钉死（AC-18.3 + 采集面聚合哨兵 + 存储面）。"""
    _seed_pipeline_data(db_session)
    r = auth_client.get("/api/stats/pipeline")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "oldest_running_task_min", "stale_count_24h", "pending_count",
        "per_source_last_success", "llm_error_rate_24h", "items_24h",
        "scored_24h", "passed_24h", "degraded_sources_count",
        "total_enabled_sources", "db_size_mb", "disk_free_mb",
    }
    assert body["items_24h"] == 1
    assert body["scored_24h"] == 1
    assert body["passed_24h"] == 1
    assert body["oldest_running_task_min"] is not None
    assert body["oldest_running_task_min"] >= 35  # RUNNING 40 分钟前创建
    assert body["pending_count"] == 0


def test_stats_pipeline_source_sentinel(auth_client, db_session):
    """聚合哨兵：失效/降频启用源计数（采集面整体降级的判定数据面）。"""
    _, src_ok, src_bad, _ = _seed_pipeline_data(db_session)
    r = auth_client.get("/api/stats/pipeline")
    body = r.json()
    assert body["total_enabled_sources"] == 2
    assert body["degraded_sources_count"] == 1
    # 逐源最近成功抓取：OK 源有值、坏源为 null（其 fetch 任务未 DONE）
    assert body["per_source_last_success"][str(src_ok.id)] is not None
    assert body["per_source_last_success"][str(src_bad.id)] is None


def test_stats_pipeline_rate_limited_source_counts_degraded(auth_client, db_session):
    _seed_pipeline_data(db_session)
    from datetime import datetime as dt

    from app.models import Source as S

    bad = db_session.query(S).filter_by(failure_level="suspect").first()
    bad.failure_level = "none"
    bad.rate_limited_until = dt.now(timezone.utc) + timedelta(minutes=30)
    db_session.commit()
    body = auth_client.get("/api/stats/pipeline").json()
    assert body["degraded_sources_count"] == 1  # 降频状态同样计入哨兵
