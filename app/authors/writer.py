"""AI 作者写作：阅读集装配 → 提示词装配（记忆占位符）→ 单次结构化调用 → 引用硬校验 → 落库。

护栏（MiroFish 反幻觉模式）：decision=write 时每个 citation 必须绑定阅读集条目 ID 且
quote 能在该条目正文中子串命中（空白归一化）；违规整体拒收并附违规说明重试一次。
重试耗尽后的去向按输出是否成功解析分态：解析从未成功（如 JSON 形态坏）→ write_run
落 FAILED 不入库；输出已解析但引用校验始终不过 → 违规文章依旧入库，article 置
citation_violated=True（数据保留，展示侧据此提示"引用存疑"），run.payload 记录违规详情。
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from .. import config
from ..models import Article, Author, Direction, Item, ScoreResult, WriteRun
from ..providers.base import JSONParseError
from ..providers.deepseek import DeepSeekProvider
from .memory import fill_placeholders

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
READING_BODY_MAX_CHARS = 1200

_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    """空白归一化 + NFKC 宽度归一化：引文匹配对「空白/全半角」格式差异鲁棒，
    内容仍须逐字连续命中（夜跑实测：RSS 源文半角标点 vs 模型全角书写）。"""
    return _WS_RE.sub("", unicodedata.normalize("NFKC", (s or ""))).lower()


def assemble_reading_set(db: Session, author: Author, k: int | None = None) -> list[tuple[Item, ScoreResult]]:
    """可读方向中 relevance≥阈值 且 passed 的条目，按 relevance 降序取前 K
    （含每源域名硬约束——见 _assemble_with_domain_cap）。"""
    return _assemble_with_domain_cap(db, author, k)[0]


def _assemble_with_domain_cap(db: Session, author: Author, k: int | None = None
                              ) -> tuple[list[tuple[Item, ScoreResult]], int]:
    """阅读集装配（含域名硬约束）：每源域名（条目 URL 的 netloc）至多
    site_config.reading_set_domain_cap 条（默认 3，≤0 = 不设限）；同一域名
    超额的条目跳过并继续收集其他域名条目直至 K——保证 K 个席位不被单一域名
    垄断（阅读集多样性硬约束，MMR 软选样为二期可选项不在本批）。
    返回 (阅读集, 因域名超额被截断的条数)。"""
    from ..siteconfig import get_config

    k = k or config.WRITE_READING_SET_K
    cap = int(get_config(db, "reading_set_domain_cap") or 0)
    q = (
        db.query(Item, ScoreResult)
        .join(ScoreResult, ScoreResult.item_id == Item.id)
        .filter(
            ScoreResult.status == "OK",
            ScoreResult.passed.is_(True),
            Item.fetch_status == "FETCHED",
        )
        .order_by(ScoreResult.relevance_score.desc())
        .limit(200)
    )
    thresholds = {rd["direction_id"]: rd.get("threshold") for rd in (author.readable_directions or [])}
    out: list[tuple[Item, ScoreResult]] = []
    domain_counts: dict[str, int] = {}
    domain_capped = 0
    from urllib.parse import urlparse

    for item, sr in q.all():
        if sr.direction_id not in thresholds:
            continue
        th = thresholds[sr.direction_id] or 60
        if sr.relevance_score < th:
            continue
        if cap and cap > 0:
            domain = urlparse(item.url or "").netloc or ""
            if domain_counts.get(domain, 0) >= cap:
                domain_capped += 1
                continue
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
        out.append((item, sr))
        if len(out) >= k:
            break
    return out, domain_capped


RANK_POOL_K = 50  # 预排序候选池：先放宽到 50，排序后取 top-K


def assemble_ranked_reading_set(
    db: Session, author: Author, k: int | None = None
) -> tuple[list[tuple[Item, ScoreResult]], dict]:
    """阅读集装配（能力⑤应用点 1）：passed 候选 → rank(criteria=方向提示词) →
    低分排除 → top-K。rank_provider=none 或排序失败时回退 relevance 排序（如实记录）。

    返回 (pairs, rank_meta)；rank_meta 落 write_run.payload（候选 id/score/provider/耗时）。
    """
    import time as _time

    from ..rerank import registry as rank_registry
    from ..rerank.base import RankCandidate, RankError

    k = k or config.WRITE_READING_SET_K
    provider_name = (author.rank_provider or "none").strip()
    if provider_name == "none":
        pairs, domain_capped = _assemble_with_domain_cap(db, author, k)
        return pairs, {"rank_provider": "none", "domain_capped": domain_capped}

    pool, pool_capped = _assemble_with_domain_cap(db, author, k=RANK_POOL_K)
    meta: dict = {"rank_provider": provider_name, "pool": len(pool),
                  "domain_capped": pool_capped}
    if not pool:
        return pool, meta

    # 按方向分组排序（criteria=方向提示词；Demo 单方向）
    by_direction: dict[int, list[tuple[Item, ScoreResult]]] = {}
    for item, sr in pool:
        by_direction.setdefault(sr.direction_id, []).append((item, sr))

    ranked_pairs: list[tuple[tuple[Item, ScoreResult], dict]] = []
    t0 = _time.monotonic()
    try:
        provider = rank_registry.get_provider(provider_name, db)
        for direction_id, group in by_direction.items():
            direction = db.get(Direction, direction_id)
            if direction is None:
                continue
            results = provider.rank(
                direction.prompt,
                [RankCandidate(id=item.id, text=f"{item.title}\n{item.content_text or ''}")
                 for item, _ in group],
                criteria_key=direction.name,
            )
            score_by_id = {r.id: r for r in results}
            for item, sr in group:
                r = score_by_id.get(item.id)
                if r is None:
                    continue
                ranked_pairs.append(((item, sr), {"rank_score": r.score, "rank_band": r.band}))
    except RankError as e:
        meta["rank_error"] = str(e)[:300]
    meta["latency_ms"] = int((_time.monotonic() - t0) * 1000)

    if not ranked_pairs:
        # 排序失败/被限额/明细缺失：回退 relevance 口径，不丢阅读集
        meta["fallback"] = "rank_failed_or_empty"
        pairs, domain_capped = _assemble_with_domain_cap(db, author, k)
        meta["domain_capped"] = domain_capped
        return pairs, meta

    threshold = author.rank_exclude_below
    kept = [(pair, det) for pair, det in ranked_pairs if det["rank_score"] >= threshold]
    if not kept:
        # 全被排除（如排序后端与长 criteria 语义不匹配的退化场景）：回退而非清空阅读集
        meta["fallback"] = "all_excluded"
        pairs, domain_capped = _assemble_with_domain_cap(db, author, k)
        meta["domain_capped"] = domain_capped
        return pairs, meta
    kept.sort(key=lambda pd: -pd[1]["rank_score"])
    meta["ranked"] = len(ranked_pairs)
    meta["kept"] = len(kept[:k])
    meta["excluded"] = len(ranked_pairs) - len(kept)
    meta["details"] = [
        {"item_id": pair[0].id, "score": det["rank_score"], "band": det["rank_band"],
         "relevance": pair[1].relevance_score}
        for pair, det in ranked_pairs
    ]
    return [pair for pair, _ in kept[:k]], meta


def _render_reading_set(pairs: list[tuple[Item, ScoreResult]]) -> str:
    blocks = []
    for item, sr in pairs:
        body = (item.content_text or "").strip()[:READING_BODY_MAX_CHARS]
        pub = item.published_at.strftime("%Y-%m-%d") if item.published_at else "未知"
        blocks.append(
            f"【条目 {item.id}】{item.title}\n来源: {item.url or '未知'} | 发布: {pub} | 相关分: {sr.relevance_score}\n正文: {body or '（无正文）'}"
        )
    return "\n\n".join(blocks)


def _hot_brief(db: Session, author: Author) -> str:
    """热点风向段（能力③→作者侧）：定位是破茧房的风向信息而非可引用素材——
    citations 校验只认阅读集 item，热点话题无全文天然不可引用（结构护栏）。"""
    if not getattr(author, "include_hot_brief", False):
        return ""
    from ..models import HotBatch

    batch = db.query(HotBatch).order_by(HotBatch.id.desc()).first()
    if batch is None:
        return ""
    kws = "、".join(batch.keywords[:15]) if batch.keywords else "（无）"
    return (
        f"\n\n【本期全网热点风向（背景信息，非阅读集，禁止作为引用来源）】\n"
        f"关键词：{kws}\n一句话综述：{batch.summary or '（无）'}\n"
    )


def _build_prompt(db: Session, author: Author, pairs: list[tuple[Item, ScoreResult]]) -> str:
    template = (PROMPTS_DIR / "writer_v1.md").read_text(encoding="utf-8")
    text = (
        template.replace("{{author_name}}", author.name)
        .replace("{{persona_prompt}}", author.persona_prompt or "")
        .replace("{{global_system_prompt}}", author.global_system_prompt or "")
    )
    text = fill_placeholders(db, author, text)
    text = text.replace("{{hot_brief}}", _hot_brief(db, author))
    return text.replace("{{reading_set}}", _render_reading_set(pairs) or "（本期阅读集为空）")


def _validate_citations(data: dict, pairs: list[tuple[Item, ScoreResult]]) -> None:
    """硬校验；失败抛 CitationError（含违规说明）。"""
    article = data.get("article") or {}
    citations = article.get("citations")
    if not isinstance(citations, list) or not citations:
        raise CitationError("decision=write 但 citations 为空或缺失")
    bodies = {item.id: item.content_text or "" for item, _ in pairs}
    for i, c in enumerate(citations):
        if not isinstance(c, dict):
            raise CitationError(f"citations[{i}] 不是对象")
        item_id, quote = c.get("item_id"), (c.get("quote") or "").strip()
        if item_id not in bodies:
            raise CitationError(f"citations[{i}].item_id={item_id} 不在阅读集内")
        if not quote:
            raise CitationError(f"citations[{i}].quote 为空")
        if _norm(quote) not in _norm(bodies[item_id]):
            raise CitationError(
                f"citations[{i}] 的 quote 在条目 {item_id} 正文中找不到（需逐字摘自原文）: {quote[:80]!r}"
            )


class CitationError(Exception):
    pass


def _parse_output(data: dict) -> dict:
    decision = str(data.get("decision", "")).strip().lower()
    if decision not in ("write", "skip"):
        raise JSONParseError(f"decision 非法: {decision!r}")
    return data


def run_write(db: Session, author: Author, *, triggered_by: str = "manual", model: str | None = None,
              batch_id: str | None = None, reading_window: tuple[int, int] | None = None,
              route_overrides: dict | None = None) -> WriteRun:
    # 可配置写作管线分派（M14）：有 author.json 的作者走 JSON 驱动管线；
    # 无 JSON 作者走现行 single 路线，行为不变（迁移策略：声明式上层，不推倒）。
    if author.author_json:
        from .pipeline import run_pipeline_write

        return run_pipeline_write(db, author, triggered_by=triggered_by, model=model,
                                  batch_id=batch_id, reading_window=reading_window,
                                  route_overrides=route_overrides)

    pairs, rank_meta = assemble_ranked_reading_set(db, author)
    run = WriteRun(
        author_id=author.id,
        triggered_by=triggered_by,
        reading_set_item_ids=[item.id for item, _ in pairs],
        payload=rank_meta,
        prompt_snapshot="",
        model=model or author.model,
        status="FAILED",
    )
    db.add(run)
    db.commit()

    provider = DeepSeekProvider(db)
    messages = [
        {"role": "system", "content": "你是 AI 内容生产系统中的作者代理，只输出规定结构的 JSON 对象。"},
        {"role": "user", "content": _build_prompt(db, author, pairs)},
    ]
    run.prompt_snapshot = messages[0]["content"] + "\n\n---USER---\n\n" + messages[1]["content"]
    db.commit()

    data: dict | None = None
    last_error: str | None = None
    # 引用违规标记：有过 CitationError 且此后未再获得通过校验的输出 → 入库文章带标记。
    # data 不复位：拒收后上一轮已解析的输出保留在 data 中，重试耗尽即按该输出入库。
    citation_violated = False
    for attempt in range(2):
        try:
            content, actual_model = provider.chat_json(
                messages,
                model=model or author.model,
                call_point="writing",
                ref_type="author",
                ref_id=author.id,
                temperature=0.3,
            )
            run.model = actual_model
            data = _parse_output(content)
            if data["decision"] == "write":
                _validate_citations(data, pairs)  # 抛 CitationError → 拒收重试
            last_error = None
            citation_violated = False
            break
        except (JSONParseError, CitationError) as e:
            citation_violated = citation_violated or isinstance(e, CitationError)
            last_error = f"{type(e).__name__}: {e}"
            messages = messages + [
                {"role": "assistant", "content": "（上次输出被拒收）"},
                {
                    "role": "user",
                    "content": (
                        f"你上次的输出因以下原因被拒收：{e}\n"
                        "请严格重新输出：JSON 只含 decision/article/reason/thinking 字段；"
                        "citations[].item_id 必须取自阅读集条目 ID，quote 必须逐字摘自该条目正文（不要改写）。"
                    ),
                },
            ]
        # ProviderError：provider 层已重试耗尽，落 FAILED

    if data is None:
        run.status = "FAILED"
        run.error = last_error
        db.commit()
        return run

    if data["decision"] == "skip":
        run.decision = "SKIP"
        run.skip_reason = str(data.get("reason") or "")
        run.skip_thinking = str(data.get("thinking") or "")
        run.status = "OK"
        db.commit()
        return run

    article_data = data["article"]
    article = Article(
        author_id=author.id,
        title=str(article_data.get("title") or "（无题）"),
        body=str(article_data.get("body") or ""),
        citations=article_data.get("citations") or [],
        status="PUBLISHED_TO_C",
        citation_violated=citation_violated,
    )
    db.add(article)
    db.commit()
    if citation_violated:
        run.payload = {**(run.payload or {}), "citation_violated": True,
                       "citation_error": last_error}
    run.decision = "WRITE"
    run.article_id = article.id
    run.status = "OK"
    run.error = None
    db.commit()

    # 写作完成 → topic_memory 沉淀"本次写了什么"
    from .memory import add_memory

    add_memory(
        db,
        author,
        module="topic",
        content=f"本次写了《{article.title}》，选题来自阅读集条目 {article.citations and article.citations[0]['item_id']} 等内容。",
        source_event="write",
    )
    return run
