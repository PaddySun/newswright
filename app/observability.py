"""健康自省与管线体检的计算层：/healthz 三态与 /api/stats/pipeline 共用口径。

三态判定原则（价值导向的可观测投影）：只有"基本功能故障"才配 503（DB 不可写/
抓取停滞超阈/任务堆积超阈）；增值层（打分/写作）故障是合法降级稳态，返回
200 + degraded 清单，报警交给外部探测、通知交给邮件通道——防报警疲劳。
口径细则：304/not_modified 轮计入成功抓取（源与管线都活着）；部署后 60 分钟
冷启动宽限内抓取停滞不触发 503（新装不报警）。
设计依据见 docs/design-index.md「AC-18.3」「AC-18.4」。
"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .models import Item, PipelineTask, ScoreResult, Source, UsageLog
from .siteconfig import get_config

# 进程启动时刻（deploy_id 语义）：探测者据此识别缓存假活与冷启动宽限期
PROCESS_START = datetime.now(timezone.utc)
COLD_START_GRACE_MINUTES = 60


def _minutes_ago(dt: datetime | None, now: datetime) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round(max((now - dt).total_seconds(), 0) / 60, 1)


def _current_engine():
    """动态取当前 engine（测试夹具会重绑 appdb.engine，模块级导入会绑到旧库）。"""
    from . import db as appdb

    return appdb.engine


def _db_writable(db: Session) -> bool:
    """写探针：独占写锁探测（只读库在 BEGIN IMMEDIATE 即失败）。"""
    try:
        with _current_engine().connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            conn.exec_driver_sql("ROLLBACK")
        return True
    except Exception:  # noqa: BLE001  探针吞异常：失败本身就是判定结果
        return False


def _db_size_mb(db: Session) -> float:
    row = db.execute(text("PRAGMA page_count")).scalar()
    page_size = db.execute(text("PRAGMA page_size")).scalar()
    if not row or not page_size:
        return 0.0
    return round(row * page_size / (1024 * 1024), 2)


def _disk_free_mb(db: Session) -> float:
    path = _current_engine().url.database or "."
    return round(shutil.disk_usage(path).free / (1024 * 1024), 2)


def _llm_error_rate_24h(db: Session, now: datetime) -> float:
    since = now - timedelta(hours=24)
    total = db.query(func.count(UsageLog.id)).filter(
        UsageLog.created_at >= since).scalar() or 0
    if not total:
        return 0.0
    errors = db.query(func.count(UsageLog.id)).filter(
        UsageLog.created_at >= since, UsageLog.ok.is_(False)).scalar() or 0
    return round(errors / total, 4)


def _degraded_levels(db: Session, now: datetime) -> list[str]:
    """增值层降级判定：近 24h 存在尝试且全部 FAILED 的增值轮 → 该能力降级中。"""
    since = now - timedelta(hours=24)
    degraded: list[str] = []
    for kind, level in (("score", "scoring"), ("write", "writing")):
        attempted = (db.query(PipelineTask.id)
                     .filter(PipelineTask.kind == kind,
                             PipelineTask.status.in_(("DONE", "FAILED")),
                             PipelineTask.updated_at >= since).count())
        if not attempted:
            continue
        done = (db.query(PipelineTask.id)
                .filter(PipelineTask.kind == kind, PipelineTask.status == "DONE",
                        PipelineTask.updated_at >= since).count())
        if done == 0:
            degraded.append(level)
    return degraded


def _last_successful_task(db: Session, kind: str) -> datetime | None:
    row = (db.query(PipelineTask.updated_at)
           .filter(PipelineTask.kind == kind, PipelineTask.status == "DONE")
           .order_by(PipelineTask.updated_at.desc())
           .first())
    return row[0] if row else None


def health_payload(db: Session) -> tuple[int, dict]:
    """计算 /healthz 三态：(status_code, payload)。fetch 任务 DONE（含 304
    not_modified 轮）即为成功抓取。"""
    from datetime import datetime as _dt

    now = _dt.now(timezone.utc)
    db_ok = _db_writable(db)
    fetch_min = _minutes_ago(_last_successful_task(db, "fetch"), now)
    score_min = _minutes_ago(_last_successful_task(db, "score"), now)
    pending_tasks = (db.query(func.count(PipelineTask.id))
                     .filter(PipelineTask.status == "PENDING").scalar()) or 0
    oldest_running = (db.query(func.min(PipelineTask.created_at))
                      .filter(PipelineTask.status == "RUNNING").scalar())
    payload = {
        "deploy_id": PROCESS_START.isoformat(),
        "db_writable": db_ok,
        "last_successful_fetch_min_ago": fetch_min,
        "last_successful_score_min_ago": score_min,
        "pending_tasks": pending_tasks,
        "oldest_running_task_min": _minutes_ago(oldest_running, now),
        "llm_error_rate_24h": _llm_error_rate_24h(db, now),
        "db_size_mb": _db_size_mb(db),
        "disk_free_mb": _disk_free_mb(db),
        "degraded": _degraded_levels(db, now),
    }
    if not db_ok:
        return 503, payload
    # 冷启动宽限：部署后 60 分钟内抓取停滞不触发 503（新装不报警）
    cold_start = _minutes_ago(PROCESS_START, now) < COLD_START_GRACE_MINUTES
    stale_minutes = int(get_config(db, "healthz_fetch_stale_minutes") or 90)
    fetch_stale = (fetch_min is None or fetch_min > stale_minutes) and not cold_start
    pending_over = pending_tasks > int(get_config(db, "healthz_pending_stale_count") or 500)
    if fetch_stale or pending_over:
        return 503, payload
    return 200, payload


def pipeline_stats_payload(db: Session) -> dict:
    """/api/stats/pipeline 体检数据：任务面 + 采集面聚合哨兵 + 存储面。"""
    from datetime import datetime as _dt

    now = _dt.now(timezone.utc)
    since = now - timedelta(hours=24)
    pending_count = (db.query(func.count(PipelineTask.id))
                     .filter(PipelineTask.status == "PENDING").scalar()) or 0
    oldest_running = (db.query(func.min(PipelineTask.created_at))
                      .filter(PipelineTask.status == "RUNNING").scalar())
    stale_count_24h = (db.query(func.count(PipelineTask.id))
                       .filter(PipelineTask.status == "FAILED",
                               PipelineTask.last_error.like("stale_reclaim:%"),
                               PipelineTask.updated_at >= since).scalar()) or 0
    per_source: dict[int, str | None] = {}
    # SQLite JSON 路径兼容性差：逐源最近成功抓取在 Python 侧聚合（源数量级小）
    rows = (db.query(PipelineTask.payload, PipelineTask.updated_at)
            .filter(PipelineTask.kind == "fetch", PipelineTask.status == "DONE")
            .order_by(PipelineTask.updated_at.desc()).all())
    per_source = {s.id: None for s in db.query(Source.id).all()}
    for payload_row, updated_at in rows:
        sid = (payload_row or {}).get("source_id")
        if sid in per_source and per_source[sid] is None:
            per_source[sid] = updated_at.isoformat() if updated_at else None
    enabled_sources = db.query(Source).filter(Source.enabled.is_(True)).all()
    degraded_sources = [s for s in enabled_sources
                        if s.failure_level in ("suspect", "hard_failed")
                        or s.rate_limited_until is not None]
    items_24h = (db.query(func.count(Item.id))
                 .filter(Item.fetched_at >= since).scalar()) or 0
    scored_24h = (db.query(func.count(ScoreResult.id))
                  .filter(ScoreResult.created_at >= since,
                          ScoreResult.status == "OK").scalar()) or 0
    passed_24h = (db.query(func.count(ScoreResult.id))
                  .filter(ScoreResult.created_at >= since,
                          ScoreResult.status == "OK",
                          ScoreResult.passed.is_(True)).scalar()) or 0
    return {
        "oldest_running_task_min": _minutes_ago(oldest_running, now),
        "stale_count_24h": stale_count_24h,
        "pending_count": pending_count,
        "per_source_last_success": per_source,
        "llm_error_rate_24h": _llm_error_rate_24h(db, now),
        "items_24h": items_24h,
        "scored_24h": scored_24h,
        "passed_24h": passed_24h,
        "degraded_sources_count": len(degraded_sources),
        "total_enabled_sources": len(enabled_sources),
        "db_size_mb": _db_size_mb(db),
        "disk_free_mb": _disk_free_mb(db),
    }
