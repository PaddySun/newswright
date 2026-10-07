"""healthz 载荷字段值与三态边界测试：score/oldest_running/pending 字段值、
恰 60 分钟冷启动边界、恰 90 分钟抓取停滞边界、pending 阈值配置消费与恰值边界。

设计依据见 docs/design-index.md「AC-18.4」。
"""
from datetime import datetime, timedelta, timezone

from app.models import PipelineTask
from app.siteconfig import set_config


def _task(db, *, kind, status, age_minutes, payload=None):
    now = datetime.now(timezone.utc)
    db.add(PipelineTask(kind=kind, status=status, payload=payload or {},
                        created_at=now - timedelta(minutes=age_minutes),
                        updated_at=now - timedelta(minutes=age_minutes)))


def _beyond_grace(monkeypatch):
    monkeypatch.setattr(
        "app.observability.PROCESS_START",
        datetime.now(timezone.utc) - timedelta(hours=3))


def test_healthz_score_minutes_ago_carries_latest_done(api_client, db_session):
    """last_successful_score_min_ago 反映最近一次 DONE score 任务（字段值语义）。"""
    _task(db_session, kind="fetch", status="DONE", age_minutes=5)
    _task(db_session, kind="score", status="DONE", age_minutes=10)
    db_session.commit()
    body = api_client.get("/healthz").json()
    score_min = body["last_successful_score_min_ago"]
    assert score_min is not None and 5 <= score_min <= 15


def test_healthz_oldest_running_task_min_carries_running(api_client, db_session):
    """oldest_running_task_min 反映最早 RUNNING 任务创建距今分钟数。"""
    _task(db_session, kind="fetch", status="DONE", age_minutes=5)
    _task(db_session, kind="fetch", status="PENDING", age_minutes=5)
    _task(db_session, kind="score", status="RUNNING", age_minutes=40)
    db_session.commit()
    body = api_client.get("/healthz").json()
    oldest = body["oldest_running_task_min"]
    assert oldest is not None and 35 <= oldest <= 45


def test_healthz_pending_tasks_counts_pending_only(api_client, db_session):
    """pending_tasks 只计 PENDING 任务（字段计量本体）。"""
    _task(db_session, kind="fetch", status="DONE", age_minutes=5)
    for _ in range(3):
        _task(db_session, kind="score", status="PENDING", age_minutes=5)
    db_session.commit()
    body = api_client.get("/healthz").json()
    assert body["pending_tasks"] == 3


def test_healthz_pending_tasks_zero_when_none(api_client, db_session):
    """无 PENDING 任务时字段为 0（空域哨兵）。"""
    body = api_client.get("/healthz").json()
    assert body["pending_tasks"] == 0


def test_healthz_cold_start_exactly_60_minutes_still_503(api_client, db_session,
                                                         monkeypatch):
    """恰满 60 分钟宽限即到期：抓取从未成功 → 503（宽限边界条款钉死）。"""
    monkeypatch.setattr(
        "app.observability.PROCESS_START",
        datetime.now(timezone.utc) - timedelta(minutes=60))
    assert api_client.get("/healthz").status_code == 503


def test_healthz_fetch_exactly_at_stale_threshold_is_200(api_client, db_session,
                                                         monkeypatch):
    """恰 90 分钟（默认阈值）不算停滞：成功抓取在阈值上 → 200（边界条款钉死）。"""
    _beyond_grace(monkeypatch)
    _task(db_session, kind="fetch", status="DONE", age_minutes=90)
    db_session.commit()
    assert api_client.get("/healthz").status_code == 200


def test_healthz_pending_threshold_config_consumed(api_client, db_session,
                                                   monkeypatch):
    """healthz_pending_stale_count 配置值进入判定（配置消费契约）。"""
    _beyond_grace(monkeypatch)
    _task(db_session, kind="fetch", status="DONE", age_minutes=5)
    set_config(db_session, "healthz_pending_stale_count", 2)
    for _ in range(3):
        _task(db_session, kind="score", status="PENDING", age_minutes=1)
    db_session.commit()
    assert api_client.get("/healthz").status_code == 503


def test_healthz_pending_exactly_at_threshold_is_200(api_client, db_session,
                                                     monkeypatch):
    """恰等于阈值不算堆积（严格大于边界条款钉死）。"""
    _beyond_grace(monkeypatch)
    _task(db_session, kind="fetch", status="DONE", age_minutes=5)
    set_config(db_session, "healthz_pending_stale_count", 2)
    for _ in range(2):
        _task(db_session, kind="score", status="PENDING", age_minutes=1)
    db_session.commit()
    assert api_client.get("/healthz").status_code == 200
