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
    ItemVec,
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
)
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


@router.post("/pipeline/write/{author_id}", status_code=202)
def pipeline_write(author_id: int, db: Session = Depends(get_session)):
    """异步写作入口：建 kind=write 的 PENDING 任务并立即提交增值线程池消费，
    响应 202 + {"task_id"}（作者不存在 → 404）。

    任务终态可查（/api/tasks 与 /api/write-runs/{id}），失败原因经 last_error
    可见；失败可恢复 = FAILED 落因后重新触发即新任务，进程中断遗留的 RUNNING
    由僵死回收转 FAILED。前端 2s/4s/8s 退避轮询行为归 UI 里程碑，本批落
    "任务终态可查 + 失败原因可见"。"""
    author = db.get(Author, author_id)
    if author is None:
        raise HTTPException(404, f"author {author_id} 不存在")
    task = PipelineTask(kind="write", status="PENDING",
                        payload={"author_id": author_id, "triggered_by": "api"})
    db.add(task)
    db.commit()
    scheduler_mod.submit_write_tasks_async()
    return {"task_id": task.id}


# ---------- 条目与打分 ----------

@router.get("/items")
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
def list_articles(author_id: int | None = None, bookmarked: bool | None = None,
                  db: Session = Depends(get_session)):
    """文章列表：author_id=按作者筛选（仅返回该作者文章）；bookmarked=按书签位
    筛选（true=已书签）。两个参数可独立使用，均为可选。"""
    q = db.query(Article).order_by(Article.id.desc())
    if author_id is not None:
        q = q.filter(Article.author_id == author_id)
    if bookmarked is not None:
        q = q.filter(Article.bookmarked.is_(bookmarked))
    return [
        {"id": a.id, "author_id": a.author_id, "title": a.title,
         "status": a.status, "citations": len(a.citations or []),
         "bookmarked": a.bookmarked}
        for a in q.all()
    ]


@router.post("/articles/{article_id}/bookmark")
def bookmark_article(article_id: int, db: Session = Depends(get_session)):
    """书签端点：置位文章的 bookmarked 列并返回 200。

    幂等语义天然成立：书签状态是文章行上的一个布尔位而非独立书签行/计数器，
    重复或并发调用都收敛到同一终态（bookmarked=true），不会产生第二份书签。
    取消书签的翻转操作（unbookmark）不在此端点（后续呈现批次）。"""
    a = db.get(Article, article_id)
    if a is None:
        raise HTTPException(404, {"code": "ARTICLE_NOT_FOUND", "message": "文章不存在"})
    a.bookmarked = True
    db.commit()
    return {"article_id": a.id, "bookmarked": True}


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


@router.get("/stats/pipeline")
@router.get("/stats/pipeline")
def stats_pipeline(db: Session = Depends(get_session)):
    """管线体检（会话守卫）：任务面 + 采集面聚合哨兵 + 存储面。"""
    from ..observability import pipeline_stats_payload

    return pipeline_stats_payload(db)


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

# 热点转方向的方向提示词预填模板（创建即确认：站长点击即人在环路确认动作）
_HOT_TRACK_PROMPT_TEMPLATE = (
    "追踪热点关键词「{keyword}」：收集与该关键词直接相关的新闻报道、官方发布、"
    "数据与多方评论，按重要性与新鲜度评估；只收录与关键词实质相关的内容，"
    "泛泛提及不收。")


class HotToDirectionIn(BaseModel):
    keyword: str


@router.post("/hot/to-direction", status_code=201)
def hot_to_direction(payload: HotToDirectionIn, db: Session = Depends(get_session)):
    """热点关键词一键转临时追踪方向（人在环路轻量闭环）。

    本端点的调用即站长确认动作（点击=确认）——无任何自动触发路径（热点批次
    更新不自动建方向；自动注入的三重约束形态列 Out of Scope）。创建物两件：
    ① temp 方向（TTL 默认 7 天、prompt 预填含关键词模板）；② 搜索源
    （url 位承载关键词、freshness=oneDay——新页面召回，旧页面不过期规则白花钱）。
    创建后按常规调度节奏采集（下一轮自然纳入，非本端点触发）。
    同名方向已存在 → 409 DIRECTION_NAME_EXISTS。"""
    keyword = payload.keyword.strip()
    if not keyword:
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "keyword 不能为空"})
    from ..timeline import site_zone

    name_exists = db.query(Direction.id).filter(Direction.name == keyword).first()
    if name_exists is not None:
        raise HTTPException(409, {"code": "DIRECTION_NAME_EXISTS",
                                  "message": "同名方向已存在"})
    d = Direction(name=keyword,
                  prompt=_HOT_TRACK_PROMPT_TEMPLATE.format(keyword=keyword),
                  prompt_version=1, threshold=60, temp=True,
                  expires_at=_temp_expires_at(_DEFAULT_TEMP_TTL_DAYS, site_zone(db)))
    db.add(d)
    db.flush()
    s = Source(direction_id=d.id, type="search", url=keyword,
               source_config={"keyword": keyword, "freshness": "oneDay"})
    db.add(s)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, {"code": "DIRECTION_NAME_EXISTS",
                                  "message": "同名方向已存在"})
    db.refresh(d)
    db.refresh(s)
    return {"direction_id": d.id, "source_id": s.id}


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
    """按 provider × 日聚合：次数/成功/失败/被限额拦截/均延迟。
    日键取 site_config timezone 的本地日（created_at 为 UTC 存储，SQL 内按站点
    时区偏移换算后切日——与预算日/追踪日同一时区口径，设计依据见
    docs/design-index.md「D16」）。"""
    from ..timeline import site_zone

    since = datetime.now(timezone.utc) - timedelta(days=days)
    zone_offset = int(site_zone(db).utcoffset(datetime.now(timezone.utc)).total_seconds())
    rows = (
        db.query(
            SearchCallLog.provider,
            func.substr(
                func.datetime(
                    func.cast(SearchCallLog.created_at, sqlalchemy.String),
                    f"+{zone_offset} seconds",
                ),
                1, 10,
            ).label("day"),
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
             interleave: bool = True, sort: str = "score",
             db: Session = Depends(get_session)):
    """登录态 B 流列表（拍板④）：按高分排序 + 可调概率穿插低分（≥最低阈值）条目，
    真实评分原样返回，穿插条目 band 标记 low_interleaved。

    探索层注入（sort=score 路径）：方向查询向量就绪且探索开关（site_config 全局
    或方向级 explore_config 覆盖）开启时，在常规排序结果之后按配额注入探索条目
    ——条目带 flag="explore" 且展示真实低相关分（不伪装）；开关关闭时零探索条目。
    阈值过滤仅约束常规条目（探索条目经注入路径出现）。"""
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
    out_items = merged[:limit]
    explore_meta = {"enabled": False, "inserted": 0}
    unscored = _unscored_entries(db, direction_id)
    if direction_id is not None and sort == "score":
        explore_meta = _inject_explore_items(db, direction_id, out_items, limit)
    return {"items": out_items, "interleave": meta, "explore": explore_meta,
            "unscored": unscored}


def _unscored_entries(db: Session, direction_id: int | None) -> list[dict]:
    """未评分条目标注列表：近期打分轮存在失败（LLM 故障的合法降级稳态）时，
    B 流附带未评分 FETCHED 条目并带"暂未评分"标注字段（真实低分/无分不伪装，
    条目照常可读）——故障隔离的呈现侧语义。近期无打分失败时不附带（正常轮
    未评分条目只是排队中）。"""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_score_failed = (
        db.query(PipelineTask.id)
        .filter(PipelineTask.kind == "score", PipelineTask.status == "FAILED",
                PipelineTask.updated_at >= cutoff)
        .first()
        is not None
    )
    if not recent_score_failed:
        return []
    q = (
        db.query(Item)
        .filter(
            Item.fetch_status == "FETCHED",
            Item.sanitize_status == "PASSED",
            Item.duplicate_of.is_(None),
        )
        .outerjoin(ScoreResult, (ScoreResult.item_id == Item.id)
                   & (ScoreResult.status == "OK"))
        .filter(ScoreResult.id.is_(None))
    )
    if direction_id is not None:
        q = q.filter(Item.source_id.in_(
            db.query(Source.id).filter_by(direction_id=direction_id, enabled=True)))
    return [
        {"id": i.id, "title": i.title, "url": i.url, "flag": "unscored",
         "note": "暂未评分"}
        for i in q.order_by(Item.id.desc()).limit(10).all()
    ]


def _inject_explore_items(db: Session, direction_id: int, out_items: list[dict],
                          limit: int) -> dict:
    """B 流探索条目注入：探索层选样（质量地板×距离分位×MMR）后追加到常规结果之后。

    总开关关（site_config 或方向级覆盖为关）、方向查询向量未就绪、嵌入禁用或
    Token 日预算触发（探索层为降级秩序第一档：选样返回空 + WARN 日志）时
    零注入；注入条目带 flag="explore" 与真实低相关分。每页配额 ≤ quota。
    """
    from .. import config
    from ..pipeline.budget import budget_exceeded
    from ..retrieval.embedder import blob_to_vec, embed_enabled
    from ..retrieval.explore import explore_params, explore_pick
    from ..siteconfig import get_config as site_get_config

    meta = {"enabled": False, "inserted": 0}
    d = db.get(Direction, direction_id)
    if d is None:
        return meta
    params = explore_params(db, d, get_config=site_get_config)
    meta["enabled"] = params["enabled"]
    if budget_exceeded(db):
        import logging as _logging

        _logging.getLogger("newswright.retrieval").warning(
            "Token 日预算已触发，探索层本轮暂停（降级秩序第一档）")
        meta["budget_paused"] = True
        return meta
    model_version = config.MOARK_EMBED_MODEL
    if (not params["enabled"] or not embed_enabled()
            or not model_version or model_version == "none"
            or d.query_vec is None):
        return meta
    rows = (
        db.query(Item, ScoreResult, ItemVec)
        .join(ScoreResult, ScoreResult.item_id == Item.id)
        .join(ItemVec, ItemVec.item_id == Item.id)
        .filter(
            ScoreResult.direction_id == direction_id,
            ScoreResult.status == "OK",
            ItemVec.model_version == model_version,
            Item.fetch_status == "FETCHED",
            Item.duplicate_of.is_(None),
        )
        .all()
    )
    pool = [
        {"id": item.id, "title": item.title, "url": item.url,
         "relevance": sr.relevance_score, "quality": sr.quality_score,
         "band": sr.band, "reason": sr.reason, "source_id": item.source_id,
         "passed": sr.passed, "vec": blob_to_vec(iv.vec)}
        for item, sr, iv in rows
    ]
    picks = explore_pick(pool, blob_to_vec(d.query_vec),
                         floor=params["floor"], percentile=params["percentile"],
                         quota=params["quota"], mmr_lambda=params["mmr_lambda"])
    existing_ids = {i["id"] for i in out_items}
    for p in picks:
        if p["id"] in existing_ids:
            continue
        out_items.append({
            "id": p["id"], "title": p["title"], "url": p["url"],
            "relevance": p["relevance"], "quality": p["quality"],
            "band": p["band"], "reason": p["reason"], "source_id": p["source_id"],
            "flag": "explore",
        })
        meta["inserted"] += 1
    return meta


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


def _temp_expires_at(ttl_days: int, zone) -> datetime:
    """TTL 到期时刻 = 到期日零点（站点时区口径——site_config timezone 的当日
    零点，解析统一经 app/timeline.py）。"""
    from ..timeline import local_day_start_after

    return local_day_start_after(zone, ttl_days)


def _get_live_direction(db: Session, direction_id: int) -> Direction:
    """取可操作方向：不存在 → DIRECTION_NOT_FOUND；已软删除 → DIRECTION_DELETED。"""
    d = db.get(Direction, direction_id)
    if d is None:
        raise HTTPException(404, {"code": "DIRECTION_NOT_FOUND", "message": "方向不存在"})
    if d.status == Direction.STATUS_DELETED:
        raise HTTPException(404, {"code": "DIRECTION_DELETED", "message": "方向已删除"})
    return d


@router.post("/directions", status_code=201)
def create_direction(payload: DirectionCreate, db: Session = Depends(get_session)):
    """创建方向：prompt_version 从 1 起；temp 方向按 ttl_days 算到期时刻
    （站点时区零点口径）。"""
    from ..timeline import site_zone

    expires_at = None
    if payload.temp:
        expires_at = _temp_expires_at(payload.ttl_days or _DEFAULT_TEMP_TTL_DAYS,
                                      site_zone(db))
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


@router.get("/directions")
def list_directions(db: Session = Depends(get_session)):
    """方向列表（不含 deleted）；读取前先做 temp TTL 到期扫描（懒翻 expired）。"""
    expire_due_temp_directions(db)
    rows = (db.query(Direction)
            .filter(Direction.status != Direction.STATUS_DELETED)
            .order_by(Direction.id).all())
    return [_direction_out(d) for d in rows]


@router.put("/directions/{direction_id}")
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


@router.delete("/directions/{direction_id}", status_code=204)
def delete_direction(direction_id: int, db: Session = Depends(get_session)):
    """软删除：status=deleted + deleted_at 落库；条目与打分全保留、不再进调度。"""
    d = _get_live_direction(db, direction_id)
    d.apply_status(Direction.STATUS_DELETED)
    db.commit()
    return Response(status_code=204)


@router.post("/directions/{direction_id}/rescore", status_code=202)
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


# ---------- 通知设置（US-19） ----------

_NOTIFY_SWITCH_KEYS = ("notify_on_source_failure", "notify_on_token_budget",
                       "notify_on_collective", "notify_on_disk")


class NotifySettingsIn(BaseModel):
    """SMTP 参数（凭据 writeOnly：只写不读回）与触发条件开关。"""
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_user: str | None = None
    smtp_pass: str | None = None
    from_addr: str | None = None
    to_addrs: list[str] | None = None
    notify_on_source_failure: bool | None = None
    notify_on_token_budget: bool | None = None
    notify_on_collective: bool | None = None
    notify_on_disk: bool | None = None


def _smtp_configured(db: Session) -> bool:
    from ..notify import get_notifier

    notifier = get_notifier("smtp", db)
    return bool(notifier and notifier.configured())


@router.put("/settings/notify")
def put_notify_settings(payload: NotifySettingsIn,
                        db: Session = Depends(get_session)):
    """保存通知设置：SMTP 参数落 site_config（凭据只写不回显）+ 触发开关；
    每次保存落一行审计日志（actor/config_key——site_config 变更审计纪律）。"""
    import logging as _logging

    from ..siteconfig import set_config

    changes = []
    field_map = {"smtp_host": payload.smtp_host, "smtp_port": payload.smtp_port,
                 "smtp_user": payload.smtp_user, "smtp_pass": payload.smtp_pass,
                 "smtp_from": payload.from_addr, "smtp_to": payload.to_addrs}
    for key, value in field_map.items():
        if value is not None:
            set_config(db, key, value)
            changes.append(key)  # 审计日志只记键名，绝不记值（凭据不落日志）
    for key in _NOTIFY_SWITCH_KEYS:
        value = getattr(payload, key)
        if value is not None:
            set_config(db, key, value)
            changes.append(key)
    if changes:
        _logging.getLogger("newswright.config").info(
            "通知设置已保存: %s", ",".join(changes),
            extra={"config_key": ",".join(changes)})
    return {"saved": True, "changed_keys": changes,
            "smtp_configured": _smtp_configured(db)}


@router.get("/settings/notify")
def get_notify_settings(db: Session = Depends(get_session)):
    """读取通知设置：凭据只出布尔位（smtp_configured），绝不回显任何配置值。"""
    from ..siteconfig import get_config

    return {
        "smtp_configured": _smtp_configured(db),
        **{key: bool(get_config(db, key)) for key in _NOTIFY_SWITCH_KEYS},
    }


@router.post("/settings/notify/test")
def test_notify_settings(db: Session = Depends(get_session)):
    """测试邮件：200 = 已发出；502 SMTP_UNREACHABLE = 不可达或未配置。"""
    from ..notify import get_notifier

    notifier = get_notifier("smtp", db)
    if notifier is None or not notifier.configured():
        raise HTTPException(502, {"code": "SMTP_UNREACHABLE",
                                  "message": "SMTP 未配置"})
    try:
        notifier._deliver("[newswright] 测试邮件",
                          "这是一封测试邮件（通知通道验证）。")
    except Exception as e:  # noqa: BLE001  报错脱敏：不携带配置值
        raise HTTPException(502, {"code": "SMTP_UNREACHABLE",
                                  "message": f"{type(e).__name__}: {e}"})
    return {"sent": True}


# ---------- 站长端点：关键词降频复位 / 月度计费对账 ----------

@router.post("/directions/{direction_id}/refresh-keyword")
def refresh_keyword(direction_id: int, db: Session = Depends(get_session)):
    """搜索关键词边际降频的手工恢复入口：清零该方向全部搜索源的零收益计数
    与降频档（复位了状态的源数即返回值；无搜索源或本就无降频时 reset=0）。"""
    from ..pipeline.skip_policy import reset_keyword_backoff

    _get_live_direction(db, direction_id)
    reset = reset_keyword_backoff(db, direction_id=direction_id)
    return {"reset": reset}


class UsageReconcileIn(BaseModel):
    month: str  # YYYY-MM
    platform_billed_units: int = Field(ge=0)


def _month_range(month: str) -> tuple[datetime, datetime] | None:
    """YYYY-MM → [当月起, 次月起) UTC 区间；格式非法返回 None。"""
    try:
        year, mon = month.split("-")
        start = datetime(int(year), int(mon), 1, tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
    if not (1 <= int(mon) <= 12) or len(mon) != 2 or len(year) != 4:
        return None
    end_year, end_mon = (int(year) + 1, 1) if int(mon) == 12 else (year, f"{int(mon) + 1:02d}")
    return start, datetime(int(end_year), int(end_mon), 1, tzinfo=timezone.utc)


@router.post("/settings/usage/reconcile")
def usage_reconcile(payload: UsageReconcileIn, db: Session = Depends(get_session)):
    """月度计费对账：平台账单计费量 vs 账本（usage_log 当月 billing_units 汇总）。

    偏差 >10% → 通知（category=reconcile，24h 去重）+ 结构化 ERROR 日志行
    （账本是唯一可信源——平台计费口径漂移过一次，对账是发现通道）。
    同月重复提交=覆盖对账记录（幂等语义；承载形态=site_config 键
    usage_reconcile_<month> 的 JSON 快照，upsert 覆盖，无独立对账表）。
    """
    import logging as _logging

    from ..models import UsageLog
    from ..notify.triggers import notify_usage_reconcile_deviation
    from ..siteconfig import set_config

    rng = _month_range(payload.month)
    if rng is None:
        raise HTTPException(400, {"code": "VALIDATION_ERROR",
                                  "message": "month 必须是 YYYY-MM 形态"})
    start, end = rng
    ledger_units = int(db.query(func.sum(func.coalesce(UsageLog.billing_units, 0)))
                       .filter(UsageLog.created_at >= start, UsageLog.created_at < end)
                       .scalar() or 0)
    platform_units = int(payload.platform_billed_units)
    if ledger_units > 0:
        deviation_pct = round(abs(platform_units - ledger_units) / ledger_units * 100, 2)
    else:
        deviation_pct = 0.0 if platform_units == 0 else 100.0
    alerted = False
    if deviation_pct > 10:
        _logging.getLogger("newswright.reconcile").error(
            "计费对账偏差超阈: month=%s ledger=%d platform=%d deviation=%.2f%%",
            payload.month, ledger_units, platform_units, deviation_pct,
            extra={"error_code": "RECONCILE_DEVIATION", "month": payload.month})
        out = notify_usage_reconcile_deviation(
            db, month=payload.month, ledger_units=ledger_units,
            platform_units=platform_units, deviation_pct=deviation_pct)
        alerted = bool(out.get("sent"))
    set_config(db, f"usage_reconcile_{payload.month}", {
        "month": payload.month, "ledger_units": ledger_units,
        "platform_units": platform_units, "deviation_pct": deviation_pct,
        "alerted": alerted, "at": datetime.now(timezone.utc).isoformat()})
    return {"month": payload.month, "ledger_units": ledger_units,
            "platform_units": platform_units, "deviation_pct": deviation_pct,
            "alerted": alerted}


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


@router.post("/directions/{direction_id}/sources", status_code=201)
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
    source_config = dict(payload.source_config or {})
    # 临时（追踪）方向的搜索源：未显式配置时效参数时默认 oneDay——默认不过滤会搜回
    # 旧页面被过期规则拒绝，搜索费白花
    d = db.get(Direction, direction_id)
    if payload.type == "search" and d is not None and d.temp and not source_config.get("freshness"):
        source_config["freshness"] = "oneDay"
    s = Source(direction_id=direction_id, type=payload.type, url=payload.url.strip(),
               source_config=source_config or None)
    db.add(s)
    db.commit()
    db.refresh(s)
    return _source_out(s)


@router.get("/directions/{direction_id}/sources")
def list_sources(direction_id: int, db: Session = Depends(get_session)):
    """来源列表（含失效级别与退避状态字段，供采集面体检消费）。"""
    _get_live_direction(db, direction_id)
    rows = (db.query(Source).filter_by(direction_id=direction_id)
            .order_by(Source.id).all())
    return [_source_out(s) for s in rows]


@router.put("/sources/{source_id}")
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
