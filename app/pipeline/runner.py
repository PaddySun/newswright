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
