"""最小 API（本机 Demo，无鉴权）。所有端点返回 JSON。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_session
from ..ingest.fingerprint import canonical_url
from ..models import (
    Article,
    Author,
    Direction,
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
    expire_due_temp_directions,
    fetch_round,
    process_fetch_round,
    score_round,
    write_task,
)
from ..authors.memory import record_feedback
from .. import scheduler as scheduler_mod
from .deps import require_session

# G1 会话守卫接管全部既有端点（AC-01.1/01.3）：路径不加 /api 前缀（统一属后续
# 契约里程碑，技术书 §3 开头注记为凭）；/api/auth/* 豁免（独立 router）。
router = APIRouter(dependencies=[Depends(require_session)])


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
@router.get("/api/items")
def list_items(direction_id: int | None = None, status: str | None = None,
               limit: int = 100, db: Session = Depends(get_session)):
    if direction_id is not None:
        direction = db.get(Direction, direction_id)
        if direction is None:
            raise HTTPException(404, {"code": "DIRECTION_NOT_FOUND",
                                      "message": "方向不存在"})
        if direction.status == Direction.STATUS_DELETED:
            raise HTTPException(404, {"code": "DIRECTION_DELETED",
                                      "message": "方向已删除（数据保留，可经后台日志查询）"})
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
    if kind == "score":
        # 打分独立入口：单独观察 score_round（含 rescore 任务消化），不经 fetch 链
        return {"score": score_round(db, triggered_by="api_run_once")}
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


# ---------- OV2：防蒙蔽穿插 B 流（拍板④） ----------

def interleave_low_score(ranked: list[dict], low_pool: list[dict], *,
                         probability: float, enabled: bool = True,
                         seed: int | None = None) -> tuple[list[dict], dict]:
    """按高分排序展示时以可调概率随机穿插"被记分器打低分但高于最低阈值"的条目。

    诚实展示真实评分不变（穿插条目带 band="low_interleaved" 标记供前端弱化呈现）；
    总开关关闭时原样返回。概率语义：高分列表每个空位独立以 probability 概率插入
    一条低分条目（低分池用尽即止）；seed 供测试确定性复现。
    """
    import random

    meta = {"enabled": enabled, "probability": probability, "inserted": 0}
    if not enabled or not low_pool or probability <= 0:
        return ranked, meta
    rng = random.Random(seed)
    out: list[dict] = []
    pool = list(low_pool)
    for item in ranked:
        if pool and rng.random() < probability:
            low = pool.pop(0)
            out.append({**low, "band": "low_interleaved"})
            meta["inserted"] += 1
        out.append(item)
    if pool and ranked:  # 尾部补齐剩余穿插额度（概率耗尽未触发的部分不再强插）
        pass
    return out, meta


@router.get("/stream/b")
def stream_b(direction_id: int | None = None, limit: int = 50,
             interleave: bool = True, db: Session = Depends(get_session)):
    """登录态 B 流列表（拍板④）：按高分排序 + 可调概率穿插低分（≥最低阈值）条目，
    真实评分原样返回，穿插条目 band 标记 low_interleaved。"""
    import os

    from .. import config

    enabled = interleave and config.SANITIZE_ENABLED is not None and os.environ.get(
        "INTERLEAVE_ENABLED", "1").strip().lower() not in ("0", "false", "off")
    probability = float(os.environ.get("INTERLEAVE_PROBABILITY") or 0.2)
    min_threshold = int(os.environ.get("INTERLEAVE_MIN_THRESHOLD") or 40)

    q = (db.query(Item, ScoreResult)
         .join(ScoreResult, ScoreResult.item_id == Item.id)
         .filter(ScoreResult.status == "OK", ScoreResult.passed.is_(True),
                 Item.fetch_status == "FETCHED")
         .order_by(ScoreResult.relevance_score.desc()))
    if direction_id is not None:
        q = q.filter(ScoreResult.direction_id == direction_id)
    ranked = [
        {"id": item.id, "title": item.title, "url": item.url,
         "relevance": sr.relevance_score, "quality": sr.quality_score,
         "band": sr.band, "reason": sr.reason, "source_id": item.source_id}
        for item, sr in q.limit(min(limit, 300)).all()
    ]
    # 低分但高于最低阈值（被记分器打低、本不进流的条目——数据全量已存）
    lq = (db.query(Item, ScoreResult)
          .join(ScoreResult, ScoreResult.item_id == Item.id)
          .filter(ScoreResult.status == "OK", ScoreResult.passed.is_(False),
                  ScoreResult.relevance_score >= min_threshold,
                  Item.fetch_status == "FETCHED")
          .order_by(ScoreResult.relevance_score.desc()))
    if direction_id is not None:
        lq = lq.filter(ScoreResult.direction_id == direction_id)
    low_pool = [
        {"id": item.id, "title": item.title, "url": item.url,
         "relevance": sr.relevance_score, "quality": sr.quality_score,
         "band": sr.band, "reason": sr.reason, "source_id": item.source_id}
        for item, sr in lq.limit(50).all()
    ]
    merged, meta = interleave_low_score(ranked, low_pool, probability=probability,
                                        enabled=enabled)
    return {"items": merged[:limit], "interleave": meta}


# ---------- OV3：热点面板数据端点（拍板②数据侧） ----------

@router.get("/hot/board")
def hot_board(direction_id: int, top_n: int = 5, db: Session = Depends(get_session)):
    """机场屏数据契约：方向级关键词 × 各关键词下打分排序前 N 条搜索结果标题
    （含 URL 与分数）。关键词 = 方向的搜索关键词（Source type=search）+ 最近
    hot_batch 提炼关键词（仅展示，无搜索结果组）。"""
    from ..models import HotBatch

    kws: list[dict] = []
    for src in db.query(Source).filter_by(direction_id=direction_id, type="search",
                                          enabled=True).all():
        keyword = (src.source_config or {}).get("keyword") or src.url
        rows = (db.query(Item, ScoreResult)
                .join(ScoreResult, ScoreResult.item_id == Item.id)
                .filter(Item.source_id == src.id, ScoreResult.status == "OK",
                        Item.fetch_status == "FETCHED")
                .order_by(ScoreResult.relevance_score.desc())
                .limit(min(top_n, 20)).all())
        kws.append({
            "keyword": keyword, "keyword_group": (src.source_config or {}).get("group"),
            "provider": (src.source_config or {}).get("provider"),
            "results": [
                {"item_id": item.id, "title": item.title, "url": item.url,
                 "relevance": sr.relevance_score, "band": sr.band}
                for item, sr in rows
            ],
        })
    hb = db.query(HotBatch).order_by(HotBatch.id.desc()).first()
    return {
        "direction_id": direction_id,
        "keywords": kws,
        "hot_trending_keywords": (hb.keywords if hb else []),
        "hot_batch_id": hb.id if hb else None,
    }


# ---------- OV4：统计总览（正式版仪表盘数据底座） ----------

@router.get("/stats/overview")
def stats_overview(days: int = 7, db: Session = Depends(get_session)):
    """Token 按作者/调用点、四类失败口径计数、不写统计、管线各阶段成功率。"""
    from ..models import PipelineTask, WriteRun

    since = datetime.now(timezone.utc) - timedelta(days=days)

    token_by_author: dict[str, dict] = {}
    for provider, rid, cp, n, pt, ct in (
        db.query(UsageLog.provider, UsageLog.ref_id, UsageLog.call_point,
                 func.count(UsageLog.id), func.sum(UsageLog.prompt_tokens),
                 func.sum(UsageLog.completion_tokens))
        .filter(UsageLog.ref_type == "author", UsageLog.created_at >= since)
        .group_by(UsageLog.provider, UsageLog.ref_id, UsageLog.call_point).all()
    ):
        if rid is None:
            continue
        d = token_by_author.setdefault(str(rid), {})
        d[cp] = {"calls": n, "prompt_tokens": int(pt or 0), "completion_tokens": int(ct or 0)}

    fetch_failed = (db.query(func.count(PipelineTask.id))
                    .filter(PipelineTask.kind == "fetch", PipelineTask.status == "FAILED",
                            PipelineTask.updated_at >= since).scalar()) or 0
    score_failed = (db.query(func.count(ScoreResult.id))
                    .filter(ScoreResult.status == "FAILED",
                            ScoreResult.created_at >= since).scalar()) or 0
    write_failed = (db.query(func.count(WriteRun.id))
                    .filter(WriteRun.status == "FAILED", WriteRun.created_at >= since).scalar()) or 0
    skip_writes = (db.query(func.count(WriteRun.id))
                   .filter(WriteRun.decision == "SKIP", WriteRun.created_at >= since).scalar()) or 0

    write_total = (db.query(func.count(WriteRun.id))
                   .filter(WriteRun.created_at >= since).scalar()) or 0
    write_ok = (db.query(func.count(WriteRun.id))
                .filter(WriteRun.status == "OK", WriteRun.created_at >= since).scalar()) or 0
    fetch_tasks = (db.query(func.count(PipelineTask.id))
                   .filter(PipelineTask.kind == "fetch", PipelineTask.updated_at >= since).scalar()) or 0
    fetch_done = (db.query(func.count(PipelineTask.id))
                  .filter(PipelineTask.kind == "fetch", PipelineTask.status == "DONE",
                          PipelineTask.updated_at >= since).scalar()) or 0

    return {
        "window_days": days,
        "token_by_author": token_by_author,
        "failures": {
            "fetch_failed": fetch_failed,
            "score_failed": score_failed,
            "write_failed": write_failed,
            "write_skipped": skip_writes,
        },
        "stage_success_rate": {
            "fetch": round(fetch_done / fetch_tasks, 4) if fetch_tasks else None,
            "write": round(write_ok / write_total, 4) if write_total else None,
        },
    }


# ---------- 方向管理（G2/W1） ----------

_DIRECTION_TYPES_ACTIVE = (Direction.STATUS_ACTIVE,)
_SOURCE_TYPES = ("rss", "web", "search")
_DEFAULT_TEMP_TTL_DAYS = 7  # 热点一键转临时方向的默认 TTL 档


class DirectionCreate(BaseModel):
    name: str
    prompt: str
    threshold: int = Field(ge=0, le=100)
    temp: bool = False
    ttl_days: int | None = Field(default=None, ge=1)


class DirectionUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    threshold: int | None = Field(default=None, ge=0, le=100)


class RescoreIn(BaseModel):
    scope: str = "all"


def _direction_out(d: Direction) -> dict:
    """方向序列化：enabled 为派生只读字段（仅 active 为真），status 是唯一真值。"""
    return {
        "id": d.id, "name": d.name, "prompt": d.prompt,
        "prompt_version": d.prompt_version, "threshold": d.threshold,
        "enabled": d.status == Direction.STATUS_ACTIVE,
        "temp": d.temp, "expires_at": d.expires_at, "status": d.status,
    }


def _temp_expires_at(ttl_days: int) -> datetime:
    """TTL 到期时刻 = 到期日零点（UTC）。

    时区口径注记：产品书决策表要求到期零点取 site_config timezone（时区键未实装，
    默认 Asia/Shanghai 待该键落地后接线），当前按 UTC 零点等价实现，见 G2 汇报遗留项。
    """
    day = (datetime.now(timezone.utc) + timedelta(days=ttl_days)).date()
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _get_live_direction(db: Session, direction_id: int) -> Direction:
    """取可操作方向：不存在 → DIRECTION_NOT_FOUND；已软删除 → DIRECTION_DELETED。"""
    d = db.get(Direction, direction_id)
    if d is None:
        raise HTTPException(404, {"code": "DIRECTION_NOT_FOUND", "message": "方向不存在"})
    if d.status == Direction.STATUS_DELETED:
        raise HTTPException(404, {"code": "DIRECTION_DELETED", "message": "方向已删除"})
    return d


@router.post("/api/directions", status_code=201)
def create_direction(payload: DirectionCreate, db: Session = Depends(get_session)):
    """创建方向：prompt_version 从 1 起；temp 方向按 ttl_days 算到期时刻。"""
    expires_at = None
    if payload.temp:
        expires_at = _temp_expires_at(payload.ttl_days or _DEFAULT_TEMP_TTL_DAYS)
    d = Direction(name=payload.name.strip(), prompt=payload.prompt,
                  prompt_version=1, threshold=payload.threshold,
                  temp=payload.temp, expires_at=expires_at)
    db.add(d)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "name 已存在"})
    db.refresh(d)
    return _direction_out(d)


@router.get("/api/directions")
def list_directions(db: Session = Depends(get_session)):
    """方向列表（不含 deleted）；读取前先做 temp TTL 到期扫描（懒翻 expired）。"""
    expire_due_temp_directions(db)
    rows = (db.query(Direction)
            .filter(Direction.status != Direction.STATUS_DELETED)
            .order_by(Direction.id).all())
    return [_direction_out(d) for d in rows]


@router.put("/api/directions/{direction_id}")
def update_direction(direction_id: int, payload: DirectionUpdate,
                     db: Session = Depends(get_session)):
    """编辑方向：仅修改 prompt 时升 prompt_version（历史打分行的版本号不变）；
    提示词升版是搜索源关键词边际降频的恢复事件之一（该方向搜索源复位）。"""
    d = _get_live_direction(db, direction_id)
    prompt_bumped = False
    if payload.prompt is not None and payload.prompt != d.prompt:
        d.prompt = payload.prompt
        d.prompt_version = int(d.prompt_version) + 1
        prompt_bumped = True
    if payload.name is not None and payload.name.strip() and payload.name.strip() != d.name:
        d.name = payload.name.strip()
    if payload.threshold is not None:
        d.threshold = payload.threshold
    db.commit()
    db.refresh(d)
    if prompt_bumped:
        from ..pipeline.skip_policy import reset_keyword_backoff

        reset_keyword_backoff(db, direction_id=d.id)
    return _direction_out(d)


@router.delete("/api/directions/{direction_id}", status_code=204)
def delete_direction(direction_id: int, db: Session = Depends(get_session)):
    """软删除：status=deleted + deleted_at 落库；条目与打分全保留、不再进调度。"""
    d = _get_live_direction(db, direction_id)
    d.apply_status(Direction.STATUS_DELETED)
    db.commit()
    return Response(status_code=204)


@router.post("/api/directions/{direction_id}/rescore", status_code=202)
def rescore_direction(direction_id: int, payload: RescoreIn,
                      db: Session = Depends(get_session)):
    """方向重打分入口：建 kind=rescore 任务异步分批消化（响应 202 + 任务 id）。"""
    if payload.scope not in ("all", "failed"):
        raise HTTPException(400, {"code": "VALIDATION_ERROR",
                                  "message": "scope 必须是 all|failed"})
    d = _get_live_direction(db, direction_id)
    task = PipelineTask(kind="rescore", status="PENDING",
                        payload={"direction_id": d.id, "scope": payload.scope,
                                 "prompt_version": d.prompt_version})
    db.add(task)
    db.commit()
    return {"task_id": task.id, "scope": payload.scope}


# ---------- 来源管理（G2/W1） ----------


class SourceCreate(BaseModel):
    type: str
    url: str
    source_config: dict | None = None


class SourceUpdate(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=1)


def _source_out(s: Source) -> dict:
    cfg = s.source_config or {}
    return {
        "id": s.id, "direction_id": s.direction_id, "type": s.type, "url": s.url,
        "enabled": s.enabled, "interval_minutes": cfg.get("interval_minutes"),
        "failure_level": s.failure_level, "failure_since": s.failure_since,
        "backoff_failures": s.backoff_failures, "backoff_skips": s.backoff_skips,
        "last_error": s.last_error,
    }


@router.post("/api/directions/{direction_id}/sources", status_code=201)
def create_source(direction_id: int, payload: SourceCreate,
                  db: Session = Depends(get_session)):
    """新增来源：type 限 rss|web|search；同方向重复注册同 URL → 409 SOURCE_URL_EXISTS
    （URL 比对在归一化后进行，tracking 参数/大小写变体视为同源）。"""
    _get_live_direction(db, direction_id)
    if payload.type not in _SOURCE_TYPES:
        raise HTTPException(400, {"code": "VALIDATION_ERROR",
                                  "message": "type 必须是 rss|web|search"})
    if not payload.url.strip():
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "url 不能为空"})
    normalized = canonical_url(payload.url)
    for src in db.query(Source).filter_by(direction_id=direction_id).all():
        if canonical_url(src.url) == normalized:
            raise HTTPException(409, {"code": "SOURCE_URL_EXISTS",
                                      "message": "该方向已注册同 URL 来源"})
    s = Source(direction_id=direction_id, type=payload.type, url=payload.url.strip(),
               source_config=payload.source_config)
    db.add(s)
    db.commit()
    db.refresh(s)
    return _source_out(s)


@router.get("/api/directions/{direction_id}/sources")
def list_sources(direction_id: int, db: Session = Depends(get_session)):
    """来源列表（含失效级别与退避状态字段，供采集面体检消费）。"""
    _get_live_direction(db, direction_id)
    rows = (db.query(Source).filter_by(direction_id=direction_id)
            .order_by(Source.id).all())
    return [_source_out(s) for s in rows]


@router.put("/api/sources/{source_id}")
def update_source(source_id: int, payload: SourceUpdate,
                  db: Session = Depends(get_session)):
    """更新来源（启停/源级间隔）：停用后调度跳过该源，已抓数据与失效状态不动。"""
    s = db.get(Source, source_id)
    if s is None:
        raise HTTPException(404, {"code": "SOURCE_NOT_FOUND", "message": "来源不存在"})
    if payload.enabled is not None:
        s.enabled = payload.enabled
    if payload.interval_minutes is not None:
        s.source_config = {**(s.source_config or {}),
                           "interval_minutes": payload.interval_minutes}
    db.commit()
    db.refresh(s)
    return _source_out(s)
