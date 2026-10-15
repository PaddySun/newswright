"""热榜聚合（能力③，BettaFish MindSpider 前半段模式：聚合 API → 全量落库 → LLM 提炼关键词）。

- 每平台每轮全量覆盖式记录（batch 语义），不做增量合并；轮次间自然形成时间序列。
- 提炼一次调用（call_point=hot_keywords，JSON 输出 keywords[]+summary，解析失败重试一次）。
- 聚合 API 不可达（采集失败）→ 任务 FAILED 如实呈现，不 mock 数据冒充成功。
- 关键词提炼失败 ≠ 采集失败：榜单数据已落库，任务照常 DONE，payload.stats 带
  degraded=["hot_keywords"]，关键词降级为标题分词兜底（kw_fallback=title_tokens）。
- 出网治理（热榜治理批）：取用一律经传输脊 GET 面 get_json（裸 httpx 异常零
  逃逸）；域级重试 ≤2 次、聚合器候选位按序取用；每次取用一行终态落 HotCallLog。
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
from ..models import HotBatch, HotCallLog, HotTopic, PipelineTask
from ..pipeline.runner import _claim, _finish, _new_task, round_busy
from ..transport.errors import (
    REASON_ERROR_NOT_RETRYABLE,
    REASON_MAX_RETRIES_EXCEEDED,
    ContractError,
    RetryExhausted,
    SemanticError,
    TransportError,
)
from ..transport.http import _origin_of, _scrub, get_json, retry_delay_ms

log = logging.getLogger("newswright.hot")

def fetch_platform(platform: str, *, timeout: float = 20.0,
                   db=None) -> list[dict[str, Any]]:
    """拉取一个平台热榜（newsnow 类聚合 API），返回原始条目列表（全量，不裁剪）。

    响应形如 {"status": "success|cache", "items": [{"title", "url", "extra"}]}。
    出网经传输脊 GET 面（客户端池复用 + 非 2xx 全入错 + httpx 原生异常包装
    分类上抛）；域级重试 ≤2 次——仅可重试 TransportError 重试（退避经
    retry_delay_ms 协商：429 的服务端 Retry-After 优先采纳、否则随机化指数
    退避；429 动态降频不在本批，status 如实落账），ContractError（items 非
    列表/响应非 JSON 等契约违例）与 SemanticError 不重试。聚合器候选位
    HOT_AGG_CANDIDATES 按序取用：首候选失败 → 次候选，全败抛 RetryExhausted
    终态（轮次层单平台容错照旧兜住）。每次取用一行终态落 HotCallLog（成败
    都记；db 为 None 时跳过落账——生产调用恒传会话）。
    设计依据见 docs/design-index.md「HR-1」「HR-2」「HR-3」「HR-4」。
    """
    bases = list(config.HOT_AGG_CANDIDATES) or [config.HOT_AGG_BASE]
    t0 = time.monotonic()
    errors: list[Exception] = []
    last_err: Exception | None = None
    for base in bases:
        attempt = 0
        while attempt <= 2:  # 首次 + 重试 ≤2（照搜索域纪律）
            try:
                resp = get_json(f"{base}?id={platform}&latest",
                                timeout=timeout, db=db, follow_redirects=True)
                try:
                    body = resp.json()
                except ValueError as e:
                    raise ContractError(
                        f"聚合 API 响应非 JSON platform={platform}: {e}") from e
                items = body.get("items") if isinstance(body, dict) else None
                if not isinstance(items, list):
                    raise ContractError(
                        f"聚合 API 响应异常 platform={platform}: {str(body)[:200]}")
                kept = [it for it in items
                        if isinstance(it, dict) and (it.get("title") or "").strip()]
                _write_call_log(db, base=base, platform=platform, ok=True,
                                status=str(resp.status_code), t0=t0, error=None)
                return kept
            except TransportError as e:
                last_err = e
                errors.append(e)
                if not e.retryable:
                    break  # 不可重试：本候选放弃，换下一候选
                attempt += 1
                if attempt <= 2:
                    delay = retry_delay_ms(e, attempt - 1) / 1000.0
                    log.warning("热榜 %s 传输失败（%.1fs 后重试）: %s",
                                platform, delay, e)
                    time.sleep(delay)
            except (ContractError, SemanticError) as e:
                last_err = e
                errors.append(e)
                break  # 契约/语义错误不重试：换下一候选
        # 该候选放弃（重试耗尽或不可重试）→ 下一候选
    last_retryable = isinstance(last_err, TransportError) and last_err.retryable
    terminal = RetryExhausted(
        f"聚合 API 全候选失败 platform={platform}: {last_err}",
        reason=(REASON_MAX_RETRIES_EXCEEDED if last_retryable
                else REASON_ERROR_NOT_RETRYABLE),
        errors=errors,
    )
    _write_call_log(db, base=bases[-1], platform=platform, ok=False,
                    status=_ledger_status(terminal), t0=t0,
                    error=f"{type(terminal).__name__}: {terminal}")
    raise terminal


def _ledger_status(err: BaseException) -> str:
    """终态错误 → 落账状态：HTTP 码优先（RetryExhausted 取末次尝试链的状态码，
    无码则错误类别名）。"""
    status = getattr(err, "status", None)
    if status is None and isinstance(err, RetryExhausted) and err.errors:
        status = getattr(err.errors[-1], "status", None)
    return str(status) if status is not None else type(err).__name__


def _write_call_log(db, *, base: str, platform: str, ok: bool,
                    status: str, t0: float, error: str | None) -> None:
    """HotCallLog 一行终态账（成败都记，中间尝试不逐行）：provider=聚合器
    origin、latency=整次取用耗时、error 入账前脱敏。"""
    if db is None:
        return
    db.add(HotCallLog(
        provider=_origin_of(base), platform=platform, ok=ok,
        status=str(status)[:20],
        latency_ms=int((time.monotonic() - t0) * 1000),
        error=_scrub(error)[:500] if error else None,
    ))
    db.commit()


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
    from ..providers.resolve import resolve_chat

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
    provider = resolve_chat(db)
    if provider is None:
        # 全部候选冷却中：按既有降级链上抛（调用方降级标题分词兜底）
        raise JSONParseError("hot_keywords 无可用 LLM 提供方（候选全部冷却）")
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
    from ..rerank import registry as rank_registry
    from ..rerank.base import RankCandidate, RankError
    from ..models import Direction

    # 三 env 经 config 归口读取（调用时求值，读取时机与原 os.environ.get 一致）
    if not config.hot_rank_filter_enabled():
        return topics, {"hot_rank_filter": False}
    provider_name = config.hot_rank_provider_name()
    min_score = config.hot_rank_min_score()
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
