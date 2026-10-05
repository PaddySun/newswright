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
from .fingerprint import entry_fingerprint, find_fingerprint_origin
from .rules import apply_rules
from .sanitize import SanitizeTarget, run_sanitize

log = logging.getLogger("newswright.ingest")

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "spm", "ref", "ref_src",
}
_UA = "Mozilla/5.0 (compatible; newswright-demo/0.1; +https://localhost)"

# 内容嗅探：HTTP 200 但响应体不是 XML（WAF 挑战页/HTML 伪装空 feed）→ 判
# non_xml_response 走失败列，不喂 feedparser（空 feed 解析会伪装成"源没更新"）。
_XML_HEAD_RE = re.compile(rb"<\?xml|<rss|<feed", re.IGNORECASE)


def _looks_like_xml(content: bytes, content_type: str) -> bool:
    """内容级 + 头部级双重嗅探：正文起始是 XML 标记，或 Content-Type 声明 xml，
    任一命中即视为 XML（两侧都不过才判非 XML——挑战页两者皆不中）。"""
    head = content[:512]
    if head.startswith(b"\xef\xbb\xbf"):  # UTF-8 BOM
        head = head[3:]
    if _XML_HEAD_RE.match(head.lstrip()):
        return True
    return "xml" in (content_type or "").lower()


# RSS 声明的休息日（feedparser 不解析 skipDays，需自行读取）
_SKIPDAYS_RE = re.compile(rb"<skipdays>(.*?)</skipdays>", re.IGNORECASE | re.DOTALL)
_SKIPDAY_ITEM_RE = re.compile(rb"<day>\s*([A-Za-z]+)\s*</day>", re.IGNORECASE)


def channel_skip_days(content: bytes) -> list[str]:
    """读取 feed 声明的 skipDays 星期名（小写；未声明返回空）。"""
    m = _SKIPDAYS_RE.search(content[:65536])
    if not m:
        return []
    return [dm.group(1).decode("ascii", "ignore").strip().lower()
            for dm in _SKIPDAY_ITEM_RE.finditer(m.group(1))]


def parse_retry_after(value: str | None, *, now: datetime) -> float | None:
    """Retry-After 双形态解析：delta-seconds 秒数与 HTTP-date 两种形态；
    解析失败返回 None（调用方退回降频档位对应缺省间隔）。负值钳为 0。"""
    if not value or not value.strip():
        return None
    text = value.strip()
    if text.isdigit():
        return float(text)
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - now).total_seconds())
    except (TypeError, ValueError):
        return None


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
        # entry.id 可能是 tag:/urn: 形式——非 URL 原样保留；URL 形式做归一化。
        # scheme 大小写不敏感（HTTP:// 也是 URL）：前缀判定先 lower，避免大写
        # 写法的 URL 型 guid 绕过 tracking 参数与 fragment 清洗、造成同文双指纹。
        return normalize_url(raw) if raw.lower().startswith(("http://", "https://")) else raw
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
    # 429/Retry-After 限流信号（动态降频识别面）：命中时任务不算失败、不记退避
    rate_limited: bool = False
    retry_after: str | None = None
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
        # 跟随重定向但显式封顶 3 次跳转：httpx 默认上限远高于此，且不设上限的
        # 跟随在恶意/配置错误的 feed 上会失控；不跟随则无法穿透短链与换域迁移。
        with httpx.Client(timeout=60.0, follow_redirects=True, max_redirects=3) as client:
            resp = client.get(source.url, headers=headers)
            if resp.status_code == 304:  # 必须在 raise_for_status 之前判（httpx 对 3xx 抛异常）
                stats.not_modified = True
                source.last_fetched_at = datetime.now(timezone.utc)
                db.commit()
                return stats
            # 429/Retry-After 在 raise_for_status 之前拦截（4xx 会抛异常走错误路径，
            # 但限流不是抓取失败——交给动态降频状态机，不计失败退避）
            if resp.status_code == 429 or "retry-after" in resp.headers:
                stats.rate_limited = True
                stats.retry_after = resp.headers.get("retry-after")
                return stats
            resp.raise_for_status()
            body = resp.content
    except httpx.HTTPStatusError as e:
        stats.error = f"{type(e).__name__}: {e}"
        if getattr(e, "response", None) is not None:
            stats.extra["http_status"] = e.response.status_code
        return stats
    except httpx.HTTPError as e:
        stats.error = f"{type(e).__name__}: {e}"
        return stats

    # 内容嗅探先于解析：挑战页/HTML 不喂 feedparser，也不回写协商缓存头
    #（挑战页的 etag 会污染后续 304 判定）
    if not _looks_like_xml(resp.content, resp.headers.get("content-type", "")):
        stats.error = "non_xml_response: HTTP 200 但响应非 XML（疑似挑战页或 HTML）"
        return stats

    entries = parse_feed_entries(body)
    stats.feed_entries = len(entries)
    _skip_days = set(channel_skip_days(body))
    if _skip_days:
        # 源声明休息日：今日命中时暴露为失效判据豁免信号（空轮不计入）
        _weekday = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        stats.extra["skip_days"] = sorted(_skip_days)
        stats.extra["skip_day"] = _weekday[datetime.now(timezone.utc).weekday()] in _skip_days
    seen_guids: set[str] = set()

    # 摘要富化预采（开关默认关）：对会因过短被规则拒绝且带真实 URL 的新条目，
    # 先抓原文补全再进写库循环——富化网络调用不携带 DB 事务（外部调用出事务纪律）。
    # 失败保持原摘要文本：后续规则判定自然落 too_short 拒绝，短文本照存。
    if bool((source.source_config or {}).get("enrich_full_text")):
        from .web import enrich_entry_text

        for ep in entries:
            if ep.guid in seen_guids or not ep.url.startswith(("http://", "https://")):
                continue
            if len(ep.content_text.strip()) >= config.RULE_MIN_BODY_CHARS:
                continue
            if normalize_url(ep.url) == normalize_url(source.url):
                continue  # 条目 URL=页面 URL 不富化（抓回同一内容无增量）
            exists = db.query(Item.id).filter_by(source_id=source.id, guid=ep.guid).one_or_none()
            if exists:
                continue  # 已入库条目不富化（成本只花在会新落库的被拒条目上）
            db.commit()  # 结束只读检查事务
            ep.content_text = enrich_entry_text(ep.url, ep.content_text, page_url=source.url)

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
            fp, _low_confidence = entry_fingerprint(ep.url, ep.guid, ep.title)
            # P1-2（D15）：方向内跨源同 URL 指纹命中 → DUP 落行（全文照存），
            # 规则初筛跳过（不进打分）；与 (source_id,guid) 分工：后者不落行
            origin = find_fingerprint_origin(db, source.direction_id, fp) if fp else None
            item = Item(
                source_id=source.id,
                guid=ep.guid,
                url=ep.url,
                title=ep.title,
                published_at=ep.published_at,
                content_text=ep.content_text,
                fetched_at=datetime.now(timezone.utc),
                direction_id=source.direction_id,
                fingerprint=fp,
            )
            if origin is not None:
                item.fetch_status = "DUP"
                item.duplicate_of = origin.id
            else:
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
