"""热榜聚合（能力③，BettaFish MindSpider 前半段模式：聚合 API → 全量落库 → LLM 提炼关键词）。

- 每平台每轮全量覆盖式记录（batch 语义），不做增量合并；轮次间自然形成时间序列。
- 提炼一次调用（call_point=hot_keywords，JSON 输出 keywords[]+summary，解析失败重试一次）。
- 聚合 API 不可达 → 任务 FAILED 如实呈现，不 mock 数据冒充成功。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from .. import config
from ..models import HotBatch, HotTopic, PipelineTask
from ..pipeline.runner import _claim, _finish, _new_task, round_busy

log = logging.getLogger("newswright.hot")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"


def fetch_platform(platform: str, *, timeout: float = 20.0) -> list[dict[str, Any]]:
    """拉取一个平台热榜（newsnow 类聚合 API），返回原始条目列表（全量，不裁剪）。

    响应形如 {"status": "success|cache", "items": [{"title", "url", "extra"}]}。
    """
    r = httpx.get(
        f"{config.HOT_AGG_BASE}?id={platform}&latest",
        headers={"User-Agent": _UA},
        timeout=timeout,
        follow_redirects=True,
    )
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
            items = fetch_platform(p)
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
    if topics:
        try:
            keywords, summary, model = _extract_keywords(db, topics)
        except Exception as e:  # noqa: BLE001  提炼失败不丢榜单数据
            kw_error = f"{type(e).__name__}: {e}"
            log.warning("关键词提炼失败: %s", e)

    batch.keywords = keywords
    batch.summary = summary
    batch.model = model
    db.commit()

    task_status = "FAILED" if (kw_error or not ok_platforms) else "DONE"
    _finish(db, task, status=task_status, stats={
        "platforms": platform_stats, "topics_stored": topic_count,
        "batch_id": batch_id, "keywords": keywords, "kw_error": kw_error,
    }, error=kw_error)
    return {
        "task_id": task.id, "status": task_status, "batch_id": batch_id,
        "topics_stored": topic_count, "keywords": keywords, "summary": summary[:200],
        "platforms": platform_stats,
    }
