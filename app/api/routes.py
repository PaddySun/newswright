"""最小 API（本机 Demo，无鉴权）。所有端点返回 JSON。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import (
    Article,
    Author,
    Item,
    MemoryEntry,
    PipelineTask,
    ScoreResult,
    SearchCallLog,
    Source,
    UsageLog,
    WriteRun,
)
from ..pipeline.runner import (
    enqueue_fetch_round,
    fetch_round,
    process_fetch_round,
    score_round,
    write_task,
)
from ..authors.memory import record_feedback
from .. import scheduler as scheduler_mod

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


# ---------- 调度（能力①） ----------

@router.post("/scheduler/run-once/{kind}")
def scheduler_run_once(kind: str, db: Session = Depends(get_session)):
    """手动触发某轮次（与调度器同一条 enqueue→process 路径，便于测试；双轨并存）。"""
    if kind == "fetch":
        round_task = enqueue_fetch_round(db, triggered_by="api_run_once")
        if round_task is None:
            return {"skipped": True, "reason": "上一轮 fetch_round 未结束（防重叠）"}
        summary = process_fetch_round(db, round_task)
        score = score_round(db, triggered_by="api_run_once")
        return {"fetch_round": summary, "score": score}
    if kind == "hot":
        try:
            from ..hot.service import run_hot_round
        except ImportError:
            raise HTTPException(501, "hot 通道未实装（M10）")
        return {"hot_round": run_hot_round(db, triggered_by="api_run_once")}
    raise HTTPException(422, "kind 必须是 fetch|hot")


@router.get("/scheduler/status")
def scheduler_status(db: Session = Depends(get_session)):
    st = scheduler_mod.status()
    recent_rounds = (
        db.query(PipelineTask)
        .filter(PipelineTask.kind.in_(("fetch_round", "hot_round")))
        .order_by(PipelineTask.id.desc())
        .limit(10)
        .all()
    )
    st["recent_rounds"] = [
        {"id": t.id, "kind": t.kind, "status": t.status, "attempts": t.attempts,
         "payload": t.payload, "last_error": t.last_error, "updated_at": t.updated_at}
        for t in recent_rounds
    ]
    return st


# ---------- 热榜（能力③） ----------

@router.get("/hot/batches")
def hot_batches(limit: int = 5, db: Session = Depends(get_session)):
    """热榜批次与关键词（时间序列；图表与作者风向段的数据源）。"""
    from ..models import HotBatch, HotTopic

    q = db.query(HotBatch).order_by(HotBatch.id.desc()).limit(min(limit, 50))
    out = []
    for b in q.all():
        topics = db.query(HotTopic).filter_by(batch_id=b.id).all()
        per_platform: dict[str, int] = {}
        for t in topics:
            per_platform[t.platform] = per_platform.get(t.platform, 0) + 1
        out.append({
            "id": b.id, "date": b.date, "keywords": b.keywords, "summary": b.summary,
            "source_platforms": b.source_platforms, "model": b.model,
            "topics_total": len(topics), "topics_per_platform": per_platform,
            "created_at": b.created_at,
        })
    return out


# ---------- 搜索统计（能力④B） ----------

@router.get("/stats/search")
def stats_search(days: int = 7, db: Session = Depends(get_session)):
    """按 provider × 日聚合：次数/成功/失败/被限额拦截/均延迟。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(
            SearchCallLog.provider,
            func.substr(func.cast(SearchCallLog.created_at, sqlalchemy.String), 1, 10).label("day"),
            func.count(SearchCallLog.id),
            func.sum(func.cast(SearchCallLog.ok, sqlalchemy.Integer)),
            func.sum(func.cast(SearchCallLog.status == "blocked", sqlalchemy.Integer)),
            func.avg(SearchCallLog.latency_ms),
        )
        .filter(SearchCallLog.created_at >= since)
        .group_by(SearchCallLog.provider, "day")
        .all()
    )
    out = []
    for provider, day, n, ok_n, blocked_n, lat in rows:
        out.append({
            "provider": provider, "day": str(day), "calls": int(n),
            "ok_calls": int(ok_n or 0),
            "failed_calls": int(n) - int(ok_n or 0),
            "quota_blocked": int(blocked_n or 0),
            "avg_latency_ms": round(float(lat or 0)),
        })
    return out


# ---------- 排序统计（能力⑤） ----------

@router.get("/stats/rank")
def stats_rank(days: int = 7, db: Session = Depends(get_session)):
    """排序调用统计：按 provider 聚合次数/延迟/被限额拦截；band 分布见
    write_run.payload.details（排序明细随写作任务落库）。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    from ..models import RankCallLog

    rows = (
        db.query(
            RankCallLog.provider,
            func.count(RankCallLog.id),
            func.sum(func.cast(RankCallLog.ok, sqlalchemy.Integer)),
            func.sum(func.cast(RankCallLog.status == "blocked", sqlalchemy.Integer)),
            func.sum(RankCallLog.candidate_count),
            func.avg(RankCallLog.latency_ms),
        )
        .filter(RankCallLog.created_at >= since)
        .group_by(RankCallLog.provider)
        .all()
    )
    out = []
    for provider, n, ok_n, blocked_n, cands, lat in rows:
        out.append({
            "provider": provider, "calls": int(n), "ok_calls": int(ok_n or 0),
            "failed_calls": int(n) - int(ok_n or 0), "quota_blocked": int(blocked_n or 0),
            "candidates_total": int(cands or 0), "avg_latency_ms": round(float(lat or 0)),
        })
    return out


# ---------- 统计（零信任过滤预留位验收项） ----------

@router.get("/stats/filters")
def stats_filters(days: int = 7, db: Session = Depends(get_session)):
    """按阶段（rule/sanitize）× 原因聚合的被过滤条数与占比；时间范围可配。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = db.query(
        Item.fetch_status, Item.rule_reject_reason,
        Item.sanitize_status, Item.sanitize_reason,
        func.count(Item.id),
    ).filter(Item.fetched_at >= since).group_by(
        Item.fetch_status, Item.rule_reject_reason,
        Item.sanitize_status, Item.sanitize_reason,
    ).all()

    def _reason_prefix(reason: str | None) -> str:
        # too_short:12<200 → too_short（聚合到原因类别）
        if not reason:
            return "(none)"
        return reason.split(":", 1)[0]

    total = sum(r[4] for r in q) or 0
    rule_rows: dict[str, int] = {}
    sanitize_rows: dict[str, int] = {}
    for fetch_status, rule_reason, sz_status, sz_reason, n in q:
        if fetch_status == "REJECTED_RULED":
            key = _reason_prefix(rule_reason)
            rule_rows[key] = rule_rows.get(key, 0) + n
        if sz_status == "REJECTED":
            key = f"{_reason_prefix(sz_reason)}|{((sz_reason or '').split(':', 1) + [''])[1]}"
            sanitize_rows[key] = sanitize_rows.get(key, 0) + n

    def _shape(rows: dict[str, int]) -> list[dict]:
        return [
            {"reason": k, "count": v, "share": round(v / total, 4) if total else 0.0}
            for k, v in sorted(rows.items(), key=lambda kv: -kv[1])
        ]

    rejected_total = sum(v for v in rule_rows.values()) + sum(v for v in sanitize_rows.values())
    return {
        "window_days": days,
        "items_total": total,
        "rejected_total": rejected_total,
        "rule": _shape(rule_rows),
        "sanitize": _shape(sanitize_rows),
    }
