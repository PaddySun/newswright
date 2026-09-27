"""最小 API（本机 Demo，无鉴权）。所有端点返回 JSON。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Article, Author, Item, MemoryEntry, PipelineTask, ScoreResult, Source, UsageLog, WriteRun
from ..pipeline.runner import fetch_round, score_round, write_task
from ..authors.memory import record_feedback

router = APIRouter()


# ---------- 管线触发 ----------

@router.post("/pipeline/run")
def pipeline_run(db: Session = Depends(get_session), direction_id: int | None = None):
    fetch = fetch_round(db, triggered_by="api")
    score = score_round(db, triggered_by="api", direction_id=direction_id)
    return {"fetch": fetch, "score": score}


@router.post("/pipeline/write/{author_id}")
def pipeline_write(author_id: int, db: Session = Depends(get_session)):
    try:
        return write_task(db, author_id, triggered_by="api")
    except ValueError as e:
        raise HTTPException(404, str(e))


# ---------- 条目与打分 ----------

@router.get("/items")
def list_items(direction_id: int | None = None, status: str | None = None,
               limit: int = 100, db: Session = Depends(get_session)):
    q = (
        db.query(Item, ScoreResult, Source)
        .join(Source, Item.source_id == Source.id)
        .outerjoin(ScoreResult, (ScoreResult.item_id == Item.id))
        .order_by(Item.id.desc())
    )
    if direction_id is not None:
        q = q.filter(Source.direction_id == direction_id)
    if status is not None:
        q = q.filter(Item.fetch_status == status)
    q = q.limit(min(limit, 500))
    out = []
    for item, sr, src in q.all():
        # 同一条目可能被打分多次（重试历史）——取最新一条
        if sr is not None:
            latest = (
                db.query(ScoreResult)
                .filter_by(item_id=item.id, direction_id=sr.direction_id)
                .order_by(ScoreResult.id.desc())
                .first()
            )
            if latest.id != sr.id:
                sr = latest
        out.append({
            "id": item.id, "source_id": item.source_id, "url": item.url,
            "title": item.title, "published_at": item.published_at,
            "fetch_status": item.fetch_status, "rule_reject_reason": item.rule_reject_reason,
            "content_chars": len(item.content_text or ""),
            "score": None if sr is None else {
                "quality": sr.quality_score, "relevance": sr.relevance_score,
                "band": sr.band, "passed": sr.passed, "reason": sr.reason,
                "prompt_version": sr.prompt_version, "model": sr.model, "status": sr.status,
            },
        })
    return out


# ---------- 文章 ----------

@router.get("/articles")
def list_articles(db: Session = Depends(get_session)):
    return [
        {"id": a.id, "author_id": a.author_id, "title": a.title,
         "status": a.status, "citations": len(a.citations or [])}
        for a in db.query(Article).order_by(Article.id.desc()).all()
    ]


@router.get("/articles/{article_id}")
def get_article(article_id: int, db: Session = Depends(get_session)):
    a = db.get(Article, article_id)
    if a is None:
        raise HTTPException(404, "article not found")
    return {"id": a.id, "author_id": a.author_id, "title": a.title, "body": a.body,
            "citations": a.citations, "status": a.status}


# ---------- 作者与记忆 ----------

@router.get("/authors/{author_id}/memory")
def author_memory(author_id: int, module: str | None = None, db: Session = Depends(get_session)):
    if db.get(Author, author_id) is None:
        raise HTTPException(404, "author not found")
    q = db.query(MemoryEntry).filter_by(author_id=author_id)
    if module:
        q = q.filter_by(module=module)
    return [
        {"id": m.id, "module": m.module, "content": m.content,
         "source_event": m.source_event, "created_at": m.created_at}
        for m in q.order_by(MemoryEntry.id.desc()).all()
    ]


@router.get("/write-runs/{run_id}")
def get_write_run(run_id: int, db: Session = Depends(get_session)):
    r = db.get(WriteRun, run_id)
    if r is None:
        raise HTTPException(404, "write_run not found")
    return {
        "id": r.id, "author_id": r.author_id, "triggered_by": r.triggered_by,
        "reading_set_item_ids": r.reading_set_item_ids, "prompt_snapshot": r.prompt_snapshot,
        "decision": r.decision, "article_id": r.article_id,
        "skip_reason": r.skip_reason, "skip_thinking": r.skip_thinking,
        "model": r.model, "status": r.status, "error": r.error,
        "created_at": r.created_at,
    }


# ---------- 反馈 ----------

class FeedbackIn(BaseModel):
    article_id: int
    verdict: str  # like | dislike
    comment: str | None = None


@router.post("/feedback")
def feedback(payload: FeedbackIn, db: Session = Depends(get_session)):
    article = db.get(Article, payload.article_id)
    if article is None:
        raise HTTPException(404, "article not found")
    if payload.verdict not in ("like", "dislike"):
        raise HTTPException(422, "verdict must be like|dislike")
    entry = record_feedback(db, article, verdict=payload.verdict, comment=payload.comment)
    return {"memory_entry_id": entry.id, "module": entry.module, "content": entry.content}


# ---------- 用量 ----------

@router.get("/usage/summary")
def usage_summary(db: Session = Depends(get_session)):
    rows = (
        db.query(
            UsageLog.call_point, UsageLog.model,
            func.count(UsageLog.id),
            func.sum(UsageLog.prompt_tokens), func.sum(UsageLog.completion_tokens),
            func.sum(UsageLog.billing_units),
            func.sum(func.cast(UsageLog.ok, __import__("sqlalchemy").Integer)),
            func.avg(UsageLog.latency_ms),
        )
        .group_by(UsageLog.call_point, UsageLog.model)
        .all()
    )
    out = []
    for call_point, model, n, pt, ct, bu, ok_n, lat in rows:
        out.append({
            "call_point": call_point, "model": model, "calls": n,
            "prompt_tokens": int(pt or 0), "completion_tokens": int(ct or 0),
            "billing_units": int(bu or 0),
            "ok_calls": int(ok_n or 0), "avg_latency_ms": round(float(lat or 0)),
        })
    return out


@router.get("/tasks")
def list_tasks(kind: str | None = None, limit: int = 50, db: Session = Depends(get_session)):
    q = db.query(PipelineTask).order_by(PipelineTask.id.desc())
    if kind:
        q = q.filter_by(kind=kind)
    q = q.limit(min(limit, 200))
    return [
        {"id": t.id, "kind": t.kind, "status": t.status, "attempts": t.attempts,
         "payload": t.payload, "last_error": t.last_error, "updated_at": t.updated_at}
        for t in q.all()
    ]
