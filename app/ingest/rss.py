"""RSS 抓取：httpx 拉取 + feedparser 解析 + guid 归一化 + (source_id, guid) 去重。

- guid 归一化：entry.id → link → url；是 URL 则去 tracking 参数与 fragment。
- 正文：entry.content[0].value → summary；HTML 用 trafilatura 抽取，失败回退剥标签。
- etag/last_modified 回写（304 跳过），morningdeck "死列"教训的反面实现。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import httpx
from sqlalchemy.orm import Session

from .. import config
from ..models import Item, Source
from .rules import apply_rules
from .sanitize import SanitizeTarget, run_sanitize

log = logging.getLogger("newswright.ingest")

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "spm", "ref", "ref_src",
}
_UA = "Mozilla/5.0 (compatible; newswright-demo/0.1; +https://localhost)"


def normalize_url(url: str) -> str:
    if not url:
        return url
    p = urlparse(url.strip())
    if not p.scheme:
        return url.strip()
    kept = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS]
    return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(kept), ""))


def normalize_guid(entry: dict) -> str:
    raw = (entry.get("id") or entry.get("link") or entry.get("link_alt") or "").strip()
    if raw:
        # entry.id 可能是 tag:/urn: 形式——非 URL 原样保留；URL 形式做归一化
        return normalize_url(raw) if raw.startswith(("http://", "https://")) else raw
    return normalize_url(entry.get("link") or "")


_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(html: str) -> str:
    try:
        import trafilatura

        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text and text.strip():
            return text.strip()
    except Exception:  # noqa: BLE001  抽取失败回退剥标签
        pass
    text = _TAG_RE.sub(" ", html)
    return re.sub(r"\s+", " ", text).strip()


def extract_entry_text(entry: dict) -> str:
    html = ""
    content = entry.get("content")
    if content and isinstance(content, list) and content[0].get("value"):
        html = content[0]["value"]
    else:
        html = entry.get("summary") or entry.get("description") or ""
    return _html_to_text(html) if html else ""


def _entry_published(entry: dict) -> datetime | None:
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if not st:
        return None
    try:
        return datetime(*st[:6], tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


@dataclass
class SourceFetchStats:
    source_id: int
    url: str
    feed_entries: int = 0
    inserted: int = 0
    dup_blocked: int = 0
    rule_rejected: int = 0
    failed: int = 0
    not_modified: bool = False
    sanitize_passed: int = 0
    sanitize_rejected: int = 0
    error: str | None = None
    guid_collisions: int = 0  # feed 内部重复 guid
    # 通道附加信息（web 变更类型/监测词命中等），并入任务 payload.stats
    extra: dict = field(default_factory=dict)


@dataclass
class EntryPayload:
    guid: str
    url: str
    title: str
    published_at: datetime | None
    content_text: str


def parse_feed_entries(content: bytes) -> list[EntryPayload]:
    parsed = feedparser.parse(content)
    entries: list[EntryPayload] = []
    for e in parsed.entries:
        guid = normalize_guid(e)
        if not guid:
            continue
        entries.append(
            EntryPayload(
                guid=guid,
                url=normalize_url(e.get("link") or ""),
                title=(e.get("title") or "").strip(),
                published_at=_entry_published(e),
                content_text=extract_entry_text(e),
            )
        )
    return entries


def fetch_source(db: Session, source: Source, *, max_age_days: int | None = None,
                 blacklist: list[str] | None = None) -> SourceFetchStats:
    stats = SourceFetchStats(source_id=source.id, url=source.url)
    headers = {"User-Agent": _UA}
    if source.etag:
        headers["If-None-Match"] = source.etag
    if source.last_modified:
        headers["If-Modified-Since"] = source.last_modified
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(source.url, headers=headers)
            if resp.status_code == 304:  # 必须在 raise_for_status 之前判（httpx 对 3xx 抛异常）
                stats.not_modified = True
                source.last_fetched_at = datetime.now(timezone.utc)
                db.commit()
                return stats
            resp.raise_for_status()
            body = resp.content
    except httpx.HTTPError as e:
        stats.error = f"{type(e).__name__}: {e}"
        return stats

    entries = parse_feed_entries(body)
    stats.feed_entries = len(entries)
    seen_guids: set[str] = set()

    for ep in entries:
        try:
            if ep.guid in seen_guids:
                stats.guid_collisions += 1
                stats.dup_blocked += 1
                continue
            seen_guids.add(ep.guid)
            exists = db.query(Item.id).filter_by(source_id=source.id, guid=ep.guid).one_or_none()
            if exists:
                stats.dup_blocked += 1
                continue
            item = Item(
                source_id=source.id,
                guid=ep.guid,
                url=ep.url,
                title=ep.title,
                published_at=ep.published_at,
                content_text=ep.content_text,
                fetched_at=datetime.now(timezone.utc),
            )
            rule = apply_rules(
                title=item.title,
                content_text=item.content_text,
                published_at=item.published_at,
                max_age_days=max_age_days,
                blacklist=blacklist,
            )
            if rule.passed:
                item.fetch_status = "FETCHED"
            else:
                item.fetch_status = "REJECTED_RULED"
                item.rule_reject_reason = rule.reason
                stats.rule_rejected += 1
            # 落库前强制流经 sanitize 阶段（骨架：pass-through 或演示链）；
            # 与 fetch_status 语义分离，REJECTED 全文照存
            sr = run_sanitize(SanitizeTarget(
                title=item.title, content_text=item.content_text, url=item.url,
            ))
            item.sanitize_status = "PASSED" if sr.passed else "REJECTED"
            item.sanitize_reason = sr.reason
            item.sanitize_detail = sr.detail or None
            if sr.passed:
                stats.sanitize_passed += 1
            else:
                stats.sanitize_rejected += 1
            db.add(item)
            db.flush()
            stats.inserted += 1
        except Exception as e:  # noqa: BLE001  单条失败不中断整源
            db.rollback()
            stats.failed += 1
            log.warning("item 入库失败 source=%s: %s", source.id, e)

    source.last_fetched_at = datetime.now(timezone.utc)
    # 回写协商缓存头（失败不致命）
    if resp.headers.get("etag"):
        source.etag = resp.headers["etag"][:500]
    if resp.headers.get("last-modified"):
        source.last_modified = resp.headers["last-modified"][:500]
    db.commit()
    return stats
