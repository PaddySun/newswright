"""定点网页监测（能力②，morningdeck WebFetcher 模式，只学模式不抄代码）。

链路：httpx 拉静态 HTML（不引入 Playwright；JS 渲染页记遗留）→ trafilatura 抽取
→ 变更检测：HTTP etag/Last-Modified 优先，缺失时内容 sha256 对比（存 Source.content_hash）
→ 无变更短跳（304 语义）；有变更/首次 → 生成 item 进入全量管线。

guid 口径（记录偏离）：单页监测条目 guid = 归一化URL#v-<内容哈希前12位>——
同 URL 内容变化时新版本新条目，旧条目保留（全量保存原则）；首抓即带版本后缀，
使 (source_id, guid) 对"内容版本"唯一。列表页 LLM 抽取的条目 guid=归一化条目 URL
（缺 URL 时用 页面URL#e-<标题哈希>）。

抽取：trafilatura 纯代码抽取先跑通；列表页可选 LLM 抽取（provider 层，
call_point=web_extract，一次 ≤10 条，JSON 输出，解析失败重试一次同既有纪律）。

监测词：source_config.monitor_words 命中时在任务 payload 记 alert（变更提醒钩子位，
本阶段不发通知）。
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from .. import config
from ..models import Item, Source
from .fingerprint import find_fingerprint_origin, url_fingerprint
from .rss import SourceFetchStats, normalize_url
from .rules import apply_rules
from .sanitize import SanitizeTarget, run_sanitize

log = logging.getLogger("newswright.ingest.web")

_UA = "Mozilla/5.0 (compatible; newswright-demo/0.1; +https://localhost)"
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_WEB_BODY_MAX_CHARS = 100_000  # morningdeck 口径：抽取后正文截 100KB


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class WebPayload:
    guid: str
    url: str
    title: str
    published_at: datetime | None
    content_text: str


def _html_title(html: str) -> str:
    m = _TITLE_RE.search(html)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()


def _published_date(html: str) -> datetime | None:
    """htmldate 抽取页面发布日期（找不到返回 None；缺发布时间不拒，与 RSS 口径一致）。"""
    try:
        import htmldate

        d = htmldate.find_date(html, original_date=True)
        if not d:
            return None
        return datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def extract_page_markdown(html: str) -> str:
    """trafilatura 抽取为 markdown（正文主体）；失败回退纯文本抽取，再失败回退剥标签。"""
    import trafilatura

    try:
        text = trafilatura.extract(
            html, output_format="markdown", include_comments=False, include_tables=False
        )
        if text and text.strip():
            return text.strip()[:_WEB_BODY_MAX_CHARS]
    except Exception:  # noqa: BLE001
        pass
    try:
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text and text.strip():
            return text.strip()[:_WEB_BODY_MAX_CHARS]
    except Exception:  # noqa: BLE001
        pass
    return ""


def llm_extract_entries(db: Session, *, page_url: str, content_text: str,
                        extraction_prompt: str) -> list[WebPayload] | None:
    """列表页 LLM 抽取（可选增强）：一次 ≤10 条，JSON 输出，解析失败重试一次。

    返回 None 表示两次均失败（调用方如实记 FAILED，不 mock）。
    """
    from ..providers.base import JSONParseError
    from ..providers.deepseek import DeepSeekProvider

    system = (
        "你是网页内容抽取器。从给定的页面内容中抽取最新条目（文章/发布记录/变更日志）。\n"
        "只输出 JSON 对象：{\"items\":[{\"title\": str, \"url\": str 或 \"\", "
        "\"summary\": str, \"date\": \"YYYY-MM-DD\" 或 \"\"}]}，最多 10 条，"
        "按页面中越新越靠前排序。不要输出 JSON 以外的任何内容。"
    )
    user = (
        f"【页面 URL】{page_url}\n【抽取要求】{extraction_prompt or '抽取页面中的内容条目'}\n"
        f"【页面内容（markdown）】\n{content_text[:20000]}"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    provider = DeepSeekProvider(db)
    data: dict | None = None
    last_err: str | None = None
    for attempt in range(2):
        try:
            data, _model = provider.chat_json(messages, call_point="web_extract", temperature=0.0)
            items = data.get("items")
            if isinstance(items, list) and items:
                break
            raise JSONParseError("items 缺失或为空")
        except Exception as e:  # noqa: BLE001  ProviderError 也走同一次重试
            last_err = f"{type(e).__name__}: {e}"
            data = None
            messages = messages + [
                {"role": "assistant", "content": "（上次输出被拒收）"},
                {"role": "user", "content": f"上次输出不合规：{e}。请严格只输出规定 JSON 结构，重新抽取。"},
            ]
    if data is None:
        log.warning("web LLM 抽取两次失败 page=%s: %s", page_url, last_err)
        return None

    out: list[WebPayload] = []
    for raw in data["items"][:10]:
        if not isinstance(raw, dict) or not str(raw.get("title") or "").strip():
            continue
        title = str(raw["title"]).strip()
        url = normalize_url(str(raw.get("url") or "").strip())
        base = url or f"{normalize_url(page_url)}#e-{hashlib.sha1(title.encode('utf-8')).hexdigest()[:12]}"
        pub = None
        ds = str(raw.get("date") or "").strip()
        if ds:
            try:
                pub = datetime.fromisoformat(ds).replace(tzinfo=timezone.utc)
            except ValueError:
                pub = None
        out.append(WebPayload(
            guid=base,
            url=url or normalize_url(page_url),
            title=title,
            published_at=pub,
            content_text=str(raw.get("summary") or "").strip(),
        ))
    return out


def enrich_entry_text(url: str, current_text: str, *, page_url: str) -> str:
    """抓原文补全正文（httpx+trafilatura，无 LLM）：全文比现文本更长才采用。

    供监测列表条目与 RSS 摘要富化开关共用（复用同一抽取路径）。
    护栏：条目 URL 与页面 URL 相同时不富化（LLM 常把索引页自身当条目 URL，
    抓回同一内容无增量）；失败保留原文不致命。

    安装备注（0 信任二期依据）：条目 URL 来自不可信页面/LLM 抽取——与 morningdeck
    抓取侧相同的教训，正式系统需 SSRF 复检（私网地址/重定向白名单），Demo 不做。
    """
    if not url.startswith(("http://", "https://")):
        return current_text
    if normalize_url(url) == normalize_url(page_url):
        return current_text
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _UA})
            resp.raise_for_status()
        text = extract_page_markdown(resp.text)
        if len(text.strip()) > len(current_text.strip()):
            return text
    except Exception as e:  # noqa: BLE001  富化失败保留摘要，不致命
        # 级别纪律：富化失败属自愈类（保留摘要继续走管线）→ WARN 而非 INFO
        log.warning("条目富化失败 url=%s: %s", url[:120], e)
    return current_text


def fetch_web_source(db: Session, source: Source) -> SourceFetchStats:
    """抓取一个 type=web 监测源：变更检测 → 抽取 → item 入库。"""
    cfg_ = source.source_config or {}
    monitor_words: list[str] = [w for w in (cfg_.get("monitor_words") or []) if w]
    extraction_prompt = cfg_.get("extraction_prompt")
    llm_extract = bool(cfg_.get("llm_extract"))
    # 索引/落地页的页面级日期不可靠（htmldate 可能取页脚或推测值）：
    # 配置 ignore_page_date=true 时单页条目不带发布时间（缺日期不拒，与 RSS 口径一致）
    ignore_page_date = bool(cfg_.get("ignore_page_date"))

    stats = SourceFetchStats(source_id=source.id, url=source.url)
    headers = {"User-Agent": _UA}
    if source.etag:
        headers["If-None-Match"] = source.etag
    if source.last_modified:
        headers["If-Modified-Since"] = source.last_modified

    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(source.url, headers=headers)
            if resp.status_code == 304:  # raise_for_status 之前判（3xx 抛异常，既有坑）
                stats.not_modified = True
                source.last_fetched_at = datetime.now(timezone.utc)
                db.commit()
                return stats
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPError as e:
        stats.error = f"{type(e).__name__}: {e}"
        return stats

    # 变更检测：etag 优先；服务端无 etag 时用内容 sha256 对比
    new_hash = _content_hash(html)
    if resp.headers.get("etag"):
        etag = resp.headers["etag"].strip()
        if source.etag and source.etag == etag:
            stats.not_modified = True
        source.etag = etag[:500]
    elif source.content_hash and source.content_hash == new_hash:
        stats.not_modified = True
    if resp.headers.get("last-modified"):
        source.last_modified = resp.headers["last-modified"][:500]

    change_type = None
    if stats.not_modified:
        source.last_fetched_at = datetime.now(timezone.utc)
        source.content_hash = new_hash
        db.commit()
        return stats
    change_type = "first_fetch" if not source.content_hash else "content_changed"

    markdown = extract_page_markdown(html)
    title = _html_title(html)
    pub = _published_date(html)
    if monitor_words:
        joined = f"{title}\n{markdown}"
        hits = [w for w in monitor_words if w in joined]
        if hits:
            stats.extra["alert_words"] = hits  # 变更提醒钩子位（本阶段不发通知）
    stats.extra["change_type"] = change_type

    inserted_hashes: set[str] = set()

    def _ingest(payload: WebPayload, *, apply_fp: bool = True) -> bool:
        """单条落库（去重 + 规则 + sanitize）。返回是否插入。

        apply_fp=False：监测单页版本条目（guid 带 #v- 版本后缀）不参与指纹链——
        同 URL 内容变化必须新条目（设计书 B7 全量保存语义，G1 汇报偏离记录）。
        """
        if payload.guid in inserted_hashes:
            stats.guid_collisions += 1
            return False
        exists = db.query(Item.id).filter_by(source_id=source.id, guid=payload.guid).one_or_none()
        if exists:
            stats.dup_blocked += 1
            return False
        fp = url_fingerprint(payload.url) if apply_fp else None
        origin = (find_fingerprint_origin(db, source.direction_id, fp)
                  if fp else None)  # P1-2（D15）：方向内跨源同 URL → DUP 落行
        item = Item(
            source_id=source.id, guid=payload.guid, url=payload.url,
            title=payload.title, published_at=payload.published_at,
            content_text=payload.content_text, fetched_at=datetime.now(timezone.utc),
            direction_id=source.direction_id, fingerprint=fp,
        )
        if origin is not None:
            item.fetch_status = "DUP"
            item.duplicate_of = origin.id
        else:
            rule = apply_rules(title=item.title, content_text=item.content_text,
                               published_at=item.published_at)
            if rule.passed:
                item.fetch_status = "FETCHED"
            else:
                item.fetch_status = "REJECTED_RULED"
                item.rule_reject_reason = rule.reason
                stats.rule_rejected += 1
        sr = run_sanitize(SanitizeTarget(title=item.title, content_text=item.content_text,
                                         url=item.url))
        item.sanitize_status = "PASSED" if sr.passed else "REJECTED"
        item.sanitize_reason = sr.reason
        item.sanitize_detail = sr.detail or None
        if sr.passed:
            stats.sanitize_passed += 1
        else:
            stats.sanitize_rejected += 1
        db.add(item)
        db.flush()
        inserted_hashes.add(payload.guid)
        stats.inserted += 1
        return True

    if llm_extract:
        entries = llm_extract_entries(db, page_url=source.url, content_text=markdown,
                                      extraction_prompt=extraction_prompt)
        if entries is None:
            stats.failed += 1
            stats.error = "web_extract: LLM 抽取两次失败"
        else:
            for ep in entries:
                if len(ep.content_text.strip()) < config.RULE_MIN_BODY_CHARS:
                    ep.content_text = enrich_entry_text(ep.url, ep.content_text,
                                                        page_url=source.url)
                _ingest(ep)
    else:
        # 单页条目：guid 带内容版本后缀（同 URL 内容变化 → 新条目，旧条目保留）；
        # 不参与指纹链（apply_fp=False，B7 全量保存语义）
        versioned_guid = f"{normalize_url(source.url)}#v-{new_hash[:12]}"
        _ingest(WebPayload(guid=versioned_guid, url=normalize_url(source.url),
                           title=title, published_at=None if ignore_page_date else pub,
                           content_text=markdown), apply_fp=False)

    source.last_fetched_at = datetime.now(timezone.utc)
    source.content_hash = new_hash
    db.commit()
    return stats
