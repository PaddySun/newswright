"""AI 作者写作：阅读集装配 → 提示词装配（记忆占位符）→ 单次结构化调用 → 引用硬校验 → 落库。

护栏（MiroFish 反幻觉模式）：decision=write 时每个 citation 必须绑定阅读集条目 ID 且
quote 能在该条目正文中子串命中（空白归一化）；违规整体拒收并附违规说明重试一次，
二次失败 write_run 落 FAILED 不入库。
"""
from __future__ import annotations

import re
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
    return _WS_RE.sub("", (s or "")).lower()


def assemble_reading_set(db: Session, author: Author, k: int | None = None) -> list[tuple[Item, ScoreResult]]:
    """可读方向中 relevance≥阈值 且 passed 的条目，按 relevance 降序取前 K。"""
    k = k or config.WRITE_READING_SET_K
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
    for item, sr in q.all():
        if sr.direction_id not in thresholds:
            continue
        th = thresholds[sr.direction_id] or 60
        if sr.relevance_score >= th:
            out.append((item, sr))
        if len(out) >= k:
            break
    return out


def _render_reading_set(pairs: list[tuple[Item, ScoreResult]]) -> str:
    blocks = []
    for item, sr in pairs:
        body = (item.content_text or "").strip()[:READING_BODY_MAX_CHARS]
        pub = item.published_at.strftime("%Y-%m-%d") if item.published_at else "未知"
        blocks.append(
            f"【条目 {item.id}】{item.title}\n来源: {item.url or '未知'} | 发布: {pub} | 相关分: {sr.relevance_score}\n正文: {body or '（无正文）'}"
        )
    return "\n\n".join(blocks)


def _build_prompt(db: Session, author: Author, pairs: list[tuple[Item, ScoreResult]]) -> str:
    template = (PROMPTS_DIR / "writer_v1.md").read_text(encoding="utf-8")
    text = (
        template.replace("{{author_name}}", author.name)
        .replace("{{persona_prompt}}", author.persona_prompt or "")
        .replace("{{global_system_prompt}}", author.global_system_prompt or "")
    )
    text = fill_placeholders(db, author, text)
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


def run_write(db: Session, author: Author, *, triggered_by: str = "manual", model: str | None = None) -> WriteRun:
    pairs = assemble_reading_set(db, author)
    run = WriteRun(
        author_id=author.id,
        triggered_by=triggered_by,
        reading_set_item_ids=[item.id for item, _ in pairs],
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
            break
        except (JSONParseError, CitationError) as e:
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
    )
    db.add(article)
    db.commit()
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
