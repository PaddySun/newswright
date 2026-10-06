"""热榜聚合（能力③，BettaFish MindSpider 前半段模式：聚合 API → 全量落库 → LLM 提炼关键词）。

- 每平台每轮全量覆盖式记录（batch 语义），不做增量合并；轮次间自然形成时间序列。
- 提炼一次调用（call_point=hot_keywords，JSON 输出 keywords[]+summary，解析失败重试一次）。
- 聚合 API 不可达（采集失败）→ 任务 FAILED 如实呈现，不 mock 数据冒充成功。
- 关键词提炼失败 ≠ 采集失败：榜单数据已落库，任务照常 DONE，payload.stats 带
  degraded=["hot_keywords"]，关键词降级为标题分词兜底（kw_fallback=title_tokens）。
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from .. import config
from ..models import HotBatch, HotTopic, PipelineTask
from ..pipeline.runner import _claim, _finish, _new_task, round_busy

log = logging.getLogger("newswright.hot")

def fetch_platform(platform: str, *, timeout: float = 20.0,
                   db=None) -> list[dict[str, Any]]:
    """拉取一个平台热榜（newsnow 类聚合 API），返回原始条目列表（全量，不裁剪）。

    响应形如 {"status": "success|cache", "items": [{"title", "url", "extra"}]}。
    客户端经统一出网工厂构造（UA 策略 + proxy 参数位）。
    """
    from ..ingest.http import http_client

    with http_client(db, timeout=timeout, follow_redirects=True) as client:
        r = client.get(f"{config.HOT_AGG_BASE}?id={platform}&latest")
    r.raise_for_status()
    body = r.json()
    items = body.get("items")
    if not isinstance(items, list):
        raise ValueError(f"聚合 API 响应异常 platform={platform}: {str(body)[:200]}")
    return [it for it in items if isinstance(it, dict) and (it.get("title") or "").strip()]


def _keyword_input(topics: list[HotTopic]) -> str:
    """给 LLM 的紧凑榜单文本：每平台前 N 条「[平台#rank] 标题 (热度)」。"""
    per_platform: dict[str, list[HotTopic]] = {}
    for t in topics:
        per_platform.setdefault(t.platform, []).append(t)
    lines: list[str] = []
    for p, ts in per_platform.items():
        for t in ts[: config.HOT_KEYWORD_INPUT_PER_PLATFORM]:
            heat = ""
            info = (t.extra or {}).get("info") or (t.extra or {}).get("hover") or ""
            if info:
                heat = f" ({str(info)[:40]})"
            lines.append(f"[{p}#{t.rank}] {t.title}{heat}")
    return "\n".join(lines)


def _extract_keywords(db: Session, topics: list[HotTopic]) -> tuple[list[str], str, str]:
    """一次 LLM 调用提炼当日关键词与 summary。返回 (keywords, summary, model)。"""
    from ..providers.base import JSONParseError
    from ..providers.deepseek import DeepSeekProvider

    system = (
        "你是全网热点分析师。输入是多个平台的热榜条目列表，请提炼今日全网热点。\n"
        "只输出 JSON 对象：{\"keywords\": [10-15 个关键词字符串，覆盖跨平台共性话题与"
        "各平台特色话题，按热度重要性排序], \"summary\": \"150 字以内的今日热点风向一句话综述\"}。"
        "不要输出 JSON 以外的任何内容。"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": _keyword_input(topics)},
    ]
    provider = DeepSeekProvider(db)
    last_err: Exception | None = None
    for _attempt in range(2):  # 解析失败重试一次（同既有纪律）
        try:
            data, model = provider.chat_json(messages, call_point="hot_keywords", temperature=0.0)
            keywords = [str(k).strip() for k in (data.get("keywords") or []) if str(k).strip()]
            summary = str(data.get("summary") or "").strip()
            if not keywords:
                raise JSONParseError("keywords 为空")
            return keywords[:20], summary, model
        except JSONParseError as e:
            last_err = e
            messages = messages + [
                {"role": "assistant", "content": "（上次输出不合规）"},
                {"role": "user", "content": f"上次输出不合规：{e}。请严格只输出规定 JSON 结构，重新提炼。"},
            ]
    raise JSONParseError(f"hot_keywords 两次失败: {last_err}")


_TITLE_WORD_RE = re.compile(r"[0-9A-Za-z_]+|[\u4e00-\u9fff]{2,}")
# 停用词表（分词兜底的清洗规则，不是兜底关键词本身）：虚词/通用平台噪声，命中即丢弃
_TITLE_STOPWORDS = frozenset({
    "的", "了", "和", "是", "在", "上", "中", "与", "及", "或", "等", "对", "为", "被", "把",
    "将", "从", "到", "更", "最", "也", "都", "而", "不", "有", "就", "要", "会", "能", "可",
    "这", "那", "你", "我", "他", "她", "它", "们", "吗", "呢", "吧", "啊", "之", "其", "以",
    "如何", "什么", "怎么", "为何", "为什么", "关于", "通过", "进行", "出现", "成为", "视频",
    "图片", "合集", "直播", "热搜", "榜单", "排行", "the", "and", "for", "with", "from",
    "that", "this", "are", "was", "were", "have", "has", "will", "your", "you",
})


def _fallback_keywords_from_titles(topics: list[HotTopic], limit: int = 15) -> list[str]:
    """关键词提炼失败时的标题分词兜底：ASCII 词原样小写、中文连续段切 2-gram，
    去停用词与纯数字段，按出现频次降序取 top-15。只用真实标题统计，不含任何固定兜底词。"""
    from collections import Counter

    counts: Counter = Counter()
    for t in topics:
        title = (t.title or "").strip()
        if not title:
            continue
        for seg in _TITLE_WORD_RE.findall(title):
            if seg.isdigit():
                continue
            if seg.isascii():
                w = seg.lower()
                if len(w) > 1 and w not in _TITLE_STOPWORDS:
                    counts[w] += 1
            else:
                for i in range(len(seg) - 1):
                    g = seg[i:i + 2]
                    if g not in _TITLE_STOPWORDS:
                        counts[g] += 1
    return [w for w, _c in counts.most_common(limit)]


def _rank_filter_topics(db: Session, topics: list[HotTopic]) -> tuple[list[HotTopic], dict]:
    """热点候选筛选（能力⑤应用点 2，默认关）：按「与站长方向的相关性」排序过滤后
    再喂关键词提炼。榜单数据全量已落库，过滤只影响提炼输入。"""
    import os

    from ..rerank import registry as rank_registry
    from ..rerank.base import RankCandidate, RankError
    from ..models import Direction

    if os.environ.get("HOT_RANK_FILTER", "").lower() not in ("1", "true", "yes", "on"):
        return topics, {"hot_rank_filter": False}
    provider_name = os.environ.get("HOT_RANK_PROVIDER") or "bocha_jev"
    min_score = int(os.environ.get("HOT_RANK_MIN_SCORE") or 40)
    direction = db.query(Direction).filter_by(enabled=True).first()
    if direction is None:
        return topics, {"hot_rank_filter": True, "error": "无启用方向"}
    try:
        provider = rank_registry.get_provider(provider_name, db)
        results = provider.rank(
            direction.prompt,
            [RankCandidate(id=t.id, text=t.title) for t in topics],
            criteria_key=f"hot:{direction.name}",
        )
    except RankError as e:
        return topics, {"hot_rank_filter": True, "provider": provider_name,
                        "error": str(e)[:200], "fallback": True}
    score_by_id = {r.id: r.score for r in results}
    kept = [t for t in topics if score_by_id.get(t.id, 0) >= min_score]
    return (kept or topics), {"hot_rank_filter": True, "provider": provider_name,
                              "input": len(topics), "kept": len(kept)}


def run_hot_round(db: Session, *, triggered_by: str = "scheduler") -> dict:
    """一轮热榜：多平台拉取 → 全量落 hot_topic → LLM 提炼 → hot_batch。"""
    if round_busy(db, "hot_round"):
        return {"skipped": True, "reason": "上一轮 hot_round 未结束（防重叠）"}
    task = _new_task(db, kind="hot_round", payload={"triggered_by": triggered_by})
    if not _claim(db, task):
        return {"skipped": True, "reason": "任务被其他 worker 认领"}
    db.expire(task)

    platforms = config.HOT_PLATFORMS
    platform_stats: list[dict] = []
    raw_by_platform: dict[str, list[dict]] = {}
    for p in platforms:
        t0 = time.monotonic()
        try:
            items = fetch_platform(p, db=db)
            dt = int((time.monotonic() - t0) * 1000)
            platform_stats.append({"platform": p, "ok": True, "items": len(items), "ms": dt})
            raw_by_platform[p] = items
            log.info("热榜 %s: %d 条 %dms", p, len(items), dt)
        except Exception as e:  # noqa: BLE001  单平台失败不中断整轮
            dt = int((time.monotonic() - t0) * 1000)
            platform_stats.append({"platform": p, "ok": False, "error": f"{type(e).__name__}: {e}", "ms": dt})
            log.warning("热榜 %s 失败: %s", p, e)
        time.sleep(0.5)  # 源间礼貌间隔（BettaFish 同款）

    ok_platforms = [s for s in platform_stats if s["ok"]]
    if not ok_platforms:
        _finish(db, task, status="FAILED", stats={"platforms": platform_stats},
                error="全部平台拉取失败（聚合 API 不可达？）")
        return {"task_id": task.id, "status": "FAILED", "platforms": platform_stats}

    batch = HotBatch(
        date=datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d"),
        keywords=[], summary="", source_platforms=[s["platform"] for s in ok_platforms],
        model="",
    )
    db.add(batch)
    db.flush()
    batch_id = batch.id

    topic_count = 0
    for s in ok_platforms:
        p = s["platform"]
        for rank, it in enumerate(raw_by_platform[p], start=1):
            db.add(HotTopic(
                platform=p, rank=rank,
                title=str(it.get("title") or "")[:2000],
                url=str(it.get("url") or "")[:2000] or None,
                extra=it.get("extra") if isinstance(it.get("extra"), dict) else None,
                keyword_contrib=rank <= config.HOT_KEYWORD_INPUT_PER_PLATFORM,
                batch_id=batch_id,
            ))
            topic_count += 1
    db.commit()
    topics = db.query(HotTopic).filter_by(batch_id=batch_id, keyword_contrib=True).all()

    keywords: list[str] = []
    summary = ""
    model = ""
    kw_error = None
    rank_meta: dict = {}
    degraded: list[str] = []
    if topics:
        try:
            llm_input, rank_meta = _rank_filter_topics(db, topics)
            keywords, summary, model = _extract_keywords(db, llm_input)
        except Exception as e:  # noqa: BLE001  提炼失败不丢榜单数据，降级标题分词兜底
            kw_error = f"{type(e).__name__}: {e}"
            log.warning("关键词提炼失败，降级标题分词: %s", e)
            keywords = _fallback_keywords_from_titles(topics)
            degraded.append("hot_keywords")

    batch.keywords = keywords
    batch.summary = summary
    batch.model = model
    db.commit()

    # 热点关键词更新 = 搜索源关键词边际降频的恢复事件之一：复位零收益计数
    if keywords:
        from ..pipeline.skip_policy import reset_keyword_backoff

        reset_keyword_backoff(db)

    # 分态：只有采集（全平台拉取）失败才 FAILED；提炼失败采集成功 → DONE + degraded
    task_status = "FAILED" if not ok_platforms else "DONE"
    stats = {
        "platforms": platform_stats, "topics_stored": topic_count,
        "batch_id": batch_id, "keywords": keywords, "kw_error": kw_error,
        **rank_meta,
    }
    if degraded:
        stats["degraded"] = degraded
        stats["kw_fallback"] = "title_tokens"
    _finish(db, task, status=task_status, stats=stats,
            error=kw_error if task_status == "FAILED" else None)
    return {
        "task_id": task.id, "status": task_status, "batch_id": batch_id,
        "topics_stored": topic_count, "keywords": keywords, "summary": summary[:200],
        "platforms": platform_stats, "degraded": degraded,
    }
