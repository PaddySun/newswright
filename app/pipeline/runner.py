"""全链路编排：任务状态一律经 pipeline_task 落库（DB 即队列雏形），禁止只在内存。

fetch round：每个启用源一个 kind=fetch 任务；score/write 随 M4/M5 扩展。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import config
from ..models import PipelineTask, Source
from ..ingest.rss import fetch_source
from ..models import Item

log = logging.getLogger("newswright.pipeline")


def _new_task(db: Session, *, kind: str, payload: dict) -> PipelineTask:
    t = PipelineTask(kind=kind, status="PENDING", payload=payload)
    db.add(t)
    db.commit()
    return t


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
            task.status = "FAILED" if stats.error else "DONE"
            task.payload = {
                **task.payload,
                "stats": {
                    "feed_entries": stats.feed_entries,
                    "inserted": stats.inserted,
                    "dup_blocked": stats.dup_blocked,
                    "rule_rejected": stats.rule_rejected,
                    "failed": stats.failed,
                    "guid_collisions": stats.guid_collisions,
                    "not_modified": stats.not_modified,
                },
            }
            if stats.error:
                task.last_error = stats.error
        except Exception as e:  # noqa: BLE001
            task.status = "FAILED"
            task.last_error = f"{type(e).__name__}: {e}"
            db.rollback()
        finally:
            task.updated_at = datetime.now(timezone.utc)
            db.commit()
        summary["sources"].append({
            "source_id": src.id,
            "url": src.url,
            "task_id": task.id,
            "status": task.status,
            **(task.payload.get("stats") or {}),
            "error": task.last_error,
        })
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
