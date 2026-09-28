"""全链路编排：任务状态一律经 pipeline_task 落库（DB 即队列雏形），禁止只在内存。

fetch round：每个启用源一个 kind=fetch 任务；score/write 随 M4/M5 扩展。
调度（能力①，M8）：调度器只负责把轮次任务置 PENDING，执行走 process_fetch_round 的
worker 路径——调度与执行分离；防重叠查 RUNNING 轮次任务，退避看 Source.backoff_*。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from .. import config
from ..models import PipelineTask, Source
from ..ingest.rss import fetch_source
from ..models import Item

log = logging.getLogger("newswright.pipeline")

ROUND_KINDS = ("fetch_round", "hot_round")


def _new_task(db: Session, *, kind: str, payload: dict) -> PipelineTask:
    t = PipelineTask(kind=kind, status="PENDING", payload=payload)
    db.add(t)
    db.commit()
    return t


def _claim(db: Session, task: PipelineTask) -> bool:
    """PENDING→RUNNING 原子抢占；已被其他 worker 抢走则返回 False。"""
    res = db.execute(
        update(PipelineTask)
        .where(PipelineTask.id == task.id, PipelineTask.status == "PENDING")
        .values(status="RUNNING", attempts=PipelineTask.attempts + 1,
                updated_at=datetime.now(timezone.utc))
    )
    db.commit()
    return res.rowcount > 0


def _finish(db: Session, task: PipelineTask, *, status: str, stats: dict | None = None,
            error: str | None = None) -> None:
    task.status = status
    if stats:
        task.payload = {**task.payload, "stats": stats}
    if error:
        task.last_error = error[:2000]
    task.updated_at = datetime.now(timezone.utc)
    db.commit()


def fetch_round(db: Session, *, triggered_by: str = "manual") -> dict:
    """抓一轮全部启用源。返回逐源统计；任何源失败不中断其他源。"""
    sources = db.query(Source).filter_by(enabled=True).all()
    summary: dict[str, object] = {"triggered_by": triggered_by, "sources": []}
    for src in sources:
        task = _new_task(db, kind="fetch", payload={"source_id": src.id, "url": src.url})
        task.status = "RUNNING"
        task.attempts += 1
        db.commit()
        try:
            stats = fetch_source(db, src)
            status = "FAILED" if stats.error else "DONE"
            _finish(db, task, status=status,
                    stats=_fetch_stats_dict(stats), error=stats.error)
            _update_backoff(db, src, failed=bool(stats.error))
        except Exception as e:  # noqa: BLE001
            task.status = "FAILED"
            task.last_error = f"{type(e).__name__}: {e}"
            db.rollback()
            _update_backoff(db, src, failed=True)
        summary["sources"].append({
            "source_id": src.id,
            "url": src.url,
            "task_id": task.id,
            "status": task.status,
            **(task.payload.get("stats") or {}),
            "error": task.last_error,
        })
    return summary


def _fetch_stats_dict(stats) -> dict:
    return {
        "feed_entries": stats.feed_entries,
        "inserted": stats.inserted,
        "dup_blocked": stats.dup_blocked,
        "rule_rejected": stats.rule_rejected,
        "failed": stats.failed,
        "guid_collisions": stats.guid_collisions,
        "not_modified": stats.not_modified,
        "sanitize_passed": stats.sanitize_passed,
        "sanitize_rejected": stats.sanitize_rejected,
    }


def _update_backoff(db: Session, src: Source, *, failed: bool) -> None:
    """连续失败计数：成功清零；失败 +1。供调度退避判定。"""
    if failed:
        src.backoff_failures = (src.backoff_failures or 0) + 1
    else:
        src.backoff_failures = 0
        src.backoff_skips = 0
    db.commit()


# ---------- 调度路径（能力①）：入队 PENDING → worker 执行，调度与执行分离 ----------


def round_busy(db: Session, kind: str) -> bool:
    """防重叠：同 kind 上一轮 RUNNING/PENDING 未清空时不置新轮。"""
    return (
        db.query(PipelineTask.id)
        .filter(PipelineTask.kind == kind, PipelineTask.status.in_(("RUNNING", "PENDING")))
        .first()
        is not None
    )


def enqueue_fetch_round(db: Session, *, triggered_by: str = "scheduler") -> PipelineTask | None:
    """把一轮抓取置为 PENDING 轮次任务 + 逐源 PENDING 任务（退避源跳过并计数）。"""
    if round_busy(db, "fetch_round"):
        return None
    skipped: list[dict] = []
    round_task = _new_task(db, kind="fetch_round", payload={"triggered_by": triggered_by})
    for src in db.query(Source).filter_by(enabled=True).all():
        fails = src.backoff_failures or 0
        if fails >= config.BACKOFF_FAIL_THRESHOLD:
            skips = (src.backoff_skips or 0) + 1
            src.backoff_skips = skips
            db.commit()
            # 退避探测：达到阈值后每 BACKOFF_PROBE_EVERY 轮放行一次探测
            if (skips - 1) % config.BACKOFF_PROBE_EVERY != 0:
                skipped.append({"source_id": src.id, "url": src.url,
                                "consecutive_failures": fails, "skips": skips})
                continue
            log.info("源 %s 连续失败 %d 次，本轮放行探测", src.id, fails)
        _new_task(db, kind="fetch", payload={"source_id": src.id, "url": src.url,
                                             "round_task_id": round_task.id})
    round_task.payload = {**round_task.payload, "skipped_backoff": skipped}
    db.commit()
    return round_task


def process_fetch_round(db: Session, round_task: PipelineTask) -> dict:
    """执行轮次任务下的全部 PENDING fetch 任务（worker 路径，逐源认领）。"""
    if not _claim(db, round_task):
        return {"round_task_id": round_task.id, "status": round_task.status, "skipped": True}
    # SQLite JSON 路径查询兼容性差，轮内任务用 payload.round_task_id 在 Python 侧过滤
    source_tasks = [
        t for t in db.query(PipelineTask)
        .filter(PipelineTask.kind == "fetch", PipelineTask.status == "PENDING")
        .all()
        if (t.payload or {}).get("round_task_id") == round_task.id
    ]
    summary = {"round_task_id": round_task.id, "sources": []}
    any_failed = False
    for t in source_tasks:
        if not _claim(db, t):
            continue
        src = db.get(Source, t.payload["source_id"])
        if src is None:
            _finish(db, t, status="FAILED", error="source 不存在")
            any_failed = True
            continue
        try:
            stats = fetch_source(db, src)
            status = "FAILED" if stats.error else "DONE"
            _finish(db, t, status=status, stats=_fetch_stats_dict(stats), error=stats.error)
            _update_backoff(db, src, failed=bool(stats.error))
            any_failed = any_failed or bool(stats.error)
        except Exception as e:  # noqa: BLE001
            _finish(db, t, status="FAILED", error=f"{type(e).__name__}: {e}")
            _update_backoff(db, src, failed=True)
            any_failed = True
        summary["sources"].append({
            "source_id": src.id, "task_id": t.id, "status": t.status,
            **(t.payload.get("stats") or {}), "error": t.last_error,
        })
    _finish(db, round_task, status="FAILED" if any_failed else "DONE")
    summary["status"] = round_task.status
    return summary


def score_round(db: Session, *, triggered_by: str = "manual", direction_id: int | None = None) -> dict:
    """对全部启用方向打一轮分。

    幂等：只对 fetch_status=FETCHED 且尚无 OK 打分（status=OK）的条目调用 LLM——
    FAILED 的下轮自动续跑，OK 的绝不重复打分（每条内容只烧一次打分 LLM）。
    """
    from ..models import Direction, ScoreResult
    from ..scoring.service import score_item

    q = db.query(Direction).filter_by(enabled=True)
    if direction_id is not None:
        q = q.filter(Direction.id == direction_id)
    directions = q.all()
    summary: dict[str, object] = {"triggered_by": triggered_by, "directions": []}

    for d in directions:
        task = _new_task(db, kind="score", payload={"direction_id": d.id, "prompt_version": d.prompt_version})
        task.status = "RUNNING"
        task.attempts += 1
        db.commit()
        scored = failed = passed = parse_failed = 0
        try:
            items = (
                db.query(Item)
                .filter(
                    Item.source_id.in_(db.query(Source.id).filter_by(direction_id=d.id, enabled=True)),
                    Item.fetch_status == "FETCHED",
                    # 零信任过滤 REJECTED 的条目不进打分（全文仍留库可查）
                    Item.sanitize_status == "PASSED",
                )
                .outerjoin(ScoreResult, (ScoreResult.item_id == Item.id) & (ScoreResult.direction_id == d.id)
                           & (ScoreResult.status == "OK"))
                .filter(ScoreResult.id.is_(None))
                .all()
            )
            for item in items:
                try:
                    sr = score_item(db, item, d)
                except Exception as e:  # noqa: BLE001  单条异常不中断整轮
                    failed += 1
                    log.warning("score_item 异常 item=%s: %s", item.id, e)
                    continue
                if sr.status == "OK":
                    scored += 1
                    passed += int(sr.passed)
                elif sr.error and "JSONParseError" in sr.error:
                    parse_failed += 1
                else:
                    failed += 1
            task.payload = {**task.payload, "stats": {
                "candidates": len(items), "scored": scored, "passed": passed,
                "call_failed": failed, "parse_failed": parse_failed,
            }}
            task.status = "FAILED" if (failed + parse_failed) > 0 and scored == 0 else "DONE"
            if failed + parse_failed > 0:
                task.last_error = f"{failed + parse_failed} 条打分未成功（含解析失败 {parse_failed}），下轮续跑"
        except Exception as e:  # noqa: BLE001
            task.status = "FAILED"
            task.last_error = f"{type(e).__name__}: {e}"
        finally:
            db.commit()
        summary["directions"].append({
            "direction_id": d.id, "name": d.name, "task_id": task.id, "status": task.status,
            **(task.payload.get("stats") or {}), "error": task.last_error,
        })
    return summary


def write_task(db: Session, author_id: int, *, triggered_by: str = "manual") -> dict:
    """触发一次作者写作，状态经 pipeline_task 落库。"""
    from ..models import Author
    from ..authors.writer import run_write

    author = db.get(Author, author_id)
    if author is None:
        raise ValueError(f"author {author_id} 不存在")
    task = _new_task(db, kind="write", payload={"author_id": author_id})
    task.status = "RUNNING"
    task.attempts += 1
    db.commit()
    try:
        run = run_write(db, author, triggered_by=triggered_by)
        task.payload = {**task.payload, "write_run_id": run.id, "decision": run.decision,
                        "article_id": run.article_id}
        task.status = "DONE" if run.status == "OK" else "FAILED"
        if run.status != "OK":
            task.last_error = run.error
    except Exception as e:  # noqa: BLE001
        task.status = "FAILED"
        task.last_error = f"{type(e).__name__}: {e}"
    finally:
        db.commit()
    return {"task_id": task.id, "status": task.status, "payload": task.payload,
            "last_error": task.last_error}
