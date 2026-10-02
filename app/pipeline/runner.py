"""全链路编排：任务状态一律经 pipeline_task 落库（DB 即队列雏形），禁止只在内存。

fetch round：每个启用源一个 kind=fetch 任务；score/write 随 M4/M5 扩展。
调度（能力①，M8）：调度器只负责把轮次任务置 PENDING，执行走 process_fetch_round 的
worker 路径——调度与执行分离；防重叠查 RUNNING 轮次任务，退避看 Source.backoff_*。
P0-1（G1）：僵死 RUNNING 任务按 kind 分档回收；全部终态迁移 CAS 化（迟到完成写拒绝）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from .. import config
from ..models import PipelineTask, Source
from ..ingest.rss import fetch_source
from ..ingest.web import fetch_web_source
from ..models import Item

log = logging.getLogger("newswright.pipeline")

ROUND_KINDS = ("fetch_round", "hot_round")

# P0-1 僵死回收阈值（分钟，按 kind 分档，一处定义）：技术书 §4.2 状态机注记
# "超 30/60/120min（rescore 并入 score=60min）"。hot_round 统筹解释：hot 属采集型，
# 按 30 分钟档（与 fetch 同类）。阈值取宽不取严：回收只兜进程中断，正常慢轮次不误伤。
RECLAIM_STALE_MINUTES: dict[str, int] = {
    "fetch": 30,
    "fetch_round": 30,
    "hot_round": 30,
    "score": 60,
    "rescore": 60,
    "write": 120,
}


def _grouped_thresholds() -> dict[int, list[str]]:
    """按阈值分档（同档一次批式 UPDATE）。"""
    grouped: dict[int, list[str]] = {}
    for kind, minutes in RECLAIM_STALE_MINUTES.items():
        grouped.setdefault(minutes, []).append(kind)
    return grouped


def reclaim_stale_tasks(db: Session, *, now: datetime | None = None) -> int:
    """P0-1 僵死任务回收（AC-20.2）：单进程设计下，跨重启仍 RUNNING 的任务必然僵死
    （morningdeck 118 条 stuck 同款疾病的唯一调度死锁路径）。

    执行形态 = 按档分组的批式 CAS：UPDATE ... WHERE status='RUNNING' AND
    updated_at < cutoff，命中行置 FAILED + last_error=stale_reclaim + attempts+1。
    迟到完成写被 CAS 拒绝（见 _finish）。挂载点：scheduler.start() 首个 tick 前 +
    run_job_safely 每次执行前。返回回收数并 INFO 日志。
    """
    now = now or datetime.now(timezone.utc)
    reclaimed = 0
    for minutes, kinds in _grouped_thresholds().items():
        cutoff = now - timedelta(minutes=minutes)
        res = db.execute(
            update(PipelineTask)
            .where(PipelineTask.kind.in_(kinds), PipelineTask.status == "RUNNING",
                   PipelineTask.updated_at < cutoff)
            .values(status="FAILED", attempts=PipelineTask.attempts + 1,
                    last_error=f"stale_reclaim: RUNNING 超 {minutes} 分钟（疑似进程中断）",
                    updated_at=now)
            .execution_options(synchronize_session=False)
        )
        reclaimed += res.rowcount
    db.commit()
    if reclaimed:
        log.info("P0-1 僵死回收：%d 个 RUNNING 任务置 FAILED（stale_reclaim）", reclaimed)
    return reclaimed


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
            error: str | None = None, payload_extra: dict | None = None) -> None:
    """CAS 收尾（AC-20.2/P0-1）：UPDATE ... SET status/payload/last_error
    WHERE id=? AND status='RUNNING'。

    rowcount=0 → 迟到完成（任务已被回收或被其他路径终结）：WARN 日志后静默丢弃、
    不抛异常（技术书 §4.2 note："回收后迟到的完成写不进去"——防线程挂死场景状态穿透）。
    内存对象同步赋值，调用方读 task.status/payload 不失真。
    stats 并入 payload.stats（DT-5 口径）；payload_extra 为顶层键合并（write_task 用）。
    """
    values: dict = {"status": status, "updated_at": datetime.now(timezone.utc)}
    if payload_extra:
        values["payload"] = {**task.payload, **payload_extra}
    if stats:
        values["payload"] = {**values.get("payload", task.payload), "stats": stats}
    if error:
        values["last_error"] = error[:2000]
    res = db.execute(
        update(PipelineTask)
        .where(PipelineTask.id == task.id, PipelineTask.status == "RUNNING")
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    task.status = status
    if "payload" in values:
        task.payload = values["payload"]
    if error:
        task.last_error = values["last_error"]
    if res.rowcount == 0:
        log.warning("迟到完成被拒 task=%s target=%s（已非 RUNNING，疑似被 stale_reclaim 回收）",
                    task.id, status)


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
            stats = _fetch_one(db, src)
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


def _fetch_one(db: Session, src: Source):
    """按源类型分发抓取器（provider 接口化：新源类型加分支即可）。"""
    if src.type == "web":
        return fetch_web_source(db, src)
    if src.type == "search":
        from ..search.pipeline import fetch_search_source

        return fetch_search_source(db, src)
    return fetch_source(db, src)


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
        **(getattr(stats, "extra", {}) or {}),
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
    now = datetime.now(timezone.utc)
    for src in db.query(Source).filter_by(enabled=True).all():
        # 每源轮询间隔（source_config.interval_minutes）：未到期跳过（调度入队侧判定）
        interval = (src.source_config or {}).get("interval_minutes")
        if interval and src.last_fetched_at:
            last = src.last_fetched_at if src.last_fetched_at.tzinfo else src.last_fetched_at.replace(tzinfo=timezone.utc)
            if (now - last).total_seconds() < int(interval) * 60:
                skipped.append({"source_id": src.id, "url": src.url,
                                "reason": f"interval_not_due:{interval}m"})
                continue
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
            stats = _fetch_one(db, src)
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
            _stats = {
                "candidates": len(items), "scored": scored, "passed": passed,
                "call_failed": failed, "parse_failed": parse_failed,
            }
            _status = "FAILED" if (failed + parse_failed) > 0 and scored == 0 else "DONE"
            _error = (f"{failed + parse_failed} 条打分未成功（含解析失败 {parse_failed}），下轮续跑"
                      if failed + parse_failed > 0 else None)
            _finish(db, task, status=_status, stats=_stats, error=_error)
        except Exception as e:  # noqa: BLE001
            _finish(db, task, status="FAILED", error=f"{type(e).__name__}: {e}")
        summary["directions"].append({
            "direction_id": d.id, "name": d.name, "task_id": task.id, "status": task.status,
            **(task.payload.get("stats") or {}), "error": task.last_error,
        })
    return summary


def write_task(db: Session, author_id: int, *, triggered_by: str = "manual",
               **run_kwargs) -> dict:
    """触发一次作者写作，状态经 pipeline_task 落库（run_kwargs 透传 batch_id 等）。"""
    from ..models import Author
    from ..authors.writer import run_write

    author = db.get(Author, author_id)
    if author is None:
        raise ValueError(f"author {author_id} 不存在")
    task = _new_task(db, kind="write", payload={"author_id": author_id, **run_kwargs})
    task.status = "RUNNING"
    task.attempts += 1
    db.commit()
    try:
        run = run_write(db, author, triggered_by=triggered_by, **run_kwargs)
        _finish(db, task, status="DONE" if run.status == "OK" else "FAILED",
                payload_extra={"write_run_id": run.id, "decision": run.decision,
                               "article_id": run.article_id},
                error=run.error if run.status != "OK" else None)
    except Exception as e:  # noqa: BLE001
        _finish(db, task, status="FAILED", error=f"{type(e).__name__}: {e}")
    return {"task_id": task.id, "status": task.status, "payload": task.payload,
            "last_error": task.last_error}
