"""健康自省三态测试：200 / 200+degraded / 503、冷启动宽限、304 计成功、no-store。

三态判定原则的钉死：只有基本功能故障（DB 不可写/抓取停滞超阈/任务堆积）才配
503；增值层（打分/写作）故障是合法稳态，不触发 503。
设计依据见 docs/design-index.md「AC-18.4」。
"""
from datetime import datetime, timedelta, timezone

from app.models import PipelineTask
from app.observability import PROCESS_START


def _seed_done_fetch(db, *, minutes_ago=5, source_id=1, not_modified=False):
    now = datetime.now(timezone.utc)
    db.add(PipelineTask(kind="fetch", status="DONE",
                        payload={"source_id": source_id, "url": "https://x.com/rss",
                                 "stats": {"not_modified": not_modified}},
                        created_at=now - timedelta(minutes=minutes_ago),
                        updated_at=now - timedelta(minutes=minutes_ago)))
    db.commit()


def _seed_failed_value_added(db, kind):
    db.add(PipelineTask(kind=kind, status="FAILED", payload={},
                        last_error="ProviderError: LLM down"))
    db.commit()


def test_healthz_no_store(api_client):
    r = api_client.get("/healthz")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"


def test_healthz_healthy_fields_pinned(api_client):
    """字段清单钉死（技术书 §3 YAML 口径）。"""
    r = api_client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "deploy_id", "db_writable", "last_successful_fetch_min_ago",
        "last_successful_score_min_ago", "pending_tasks",
        "oldest_running_task_min", "llm_error_rate_24h", "db_size_mb",
        "disk_free_mb", "degraded",
    }
    assert body["db_writable"] is True
    assert body["degraded"] == []
    assert "T" in body["deploy_id"]  # 进程启动时间戳


def test_healthz_value_added_failure_degraded_not_503(api_client, db_session):
    """LLM 全挂（打分+写作任务近期全 FAILED）→ 200 + degraded 清单，不 503。"""
    _seed_failed_value_added(db_session, "score")
    _seed_failed_value_added(db_session, "write")
    r = api_client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["degraded"] == ["scoring", "writing"]


def test_healthz_db_unwritable_503(api_client, db_session, monkeypatch):
    monkeypatch.setattr("app.observability._db_writable", lambda db: False)
    r = api_client.get("/healthz")
    assert r.status_code == 503
    assert r.json()["db_writable"] is False


def test_healthz_fetch_stale_beyond_grace_503(api_client, db_session, monkeypatch):
    """部署超宽限期后抓取从未成功 → 503（外部探测据此报警）。"""
    old_start = datetime.now(timezone.utc) - timedelta(hours=3)
    monkeypatch.setattr("app.observability.PROCESS_START", old_start)
    r = api_client.get("/healthz")
    assert r.status_code == 503


def test_healthz_cold_start_grace_no_alarm(api_client, db_session):
    """冷启动宽限：部署后 60 分钟内抓取停滞不触发 503（新装不报警）。"""
    r = api_client.get("/healthz")  # 全新库、无任何 fetch 成功、进程刚启动
    assert r.status_code == 200


def test_healthz_not_modified_round_counts_as_success(api_client, db_session):
    """304/not_modified 轮计入成功抓取（源与管线都活着）。"""
    old_start = datetime.now(timezone.utc) - timedelta(hours=3)
    _seed_done_fetch(db_session, minutes_ago=8, not_modified=True)
    import app.observability as obs

    obs.PROCESS_START = old_start  # 越过宽限期，仅 304 成功轮在场
    try:
        r = api_client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["last_successful_fetch_min_ago"] is not None
        assert 5 <= body["last_successful_fetch_min_ago"] <= 15
    finally:
        obs.PROCESS_START = PROCESS_START


def test_healthz_fetch_stale_threshold_configurable(api_client, db_session, monkeypatch):
    """抓取停滞超 site_config 阈值（宽限期外）→ 503；阈值内 200。"""
    from app.siteconfig import set_config

    _seed_done_fetch(db_session, minutes_ago=120)
    old_start = datetime.now(timezone.utc) - timedelta(hours=3)
    monkeypatch.setattr("app.observability.PROCESS_START", old_start)
    set_config(db_session, "healthz_fetch_stale_minutes", 90)
    assert api_client.get("/healthz").status_code == 503
    set_config(db_session, "healthz_fetch_stale_minutes", 180)
    assert api_client.get("/healthz").status_code == 200
