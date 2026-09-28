"""搜索通道（能力④C）：关键词 → 底座搜索（过额度闸）→ 结果转 item → 全量管线。

- 关键词配置走 Source 行（type=search，source_config: keyword/provider/count/
  freshness）——复用 (source_id, guid) 去重、源级退避与统计；同 URL 被不同关键词
  命中会各生成一条 item（source_id 不同），如实记录该口径。
- item：guid=归一化结果 URL，全文=content（缺则 snippet），raw 条目存档于 item.raw。
- 规则口径偏离（记录）：搜索召回的多为常青内容（实测 bocha freshness=oneMonth 仍返回
  老页面），RSS 的 30 天过期口径不适用——搜索通道过期阈值默认 365 天
  （source_config.max_age_days 可覆盖），新鲜度由 API freshness 参数在召回侧控制。
- 额度超限：任务 DONE + payload.stats.quota_blocked=true（SKIPPED_QUOTA 语义），
  不计失败退避，下轮自然恢复。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import config
from ..ingest.rss import SourceFetchStats, normalize_url
from ..ingest.rules import apply_rules
from ..ingest.sanitize import SanitizeTarget, run_sanitize
from ..models import Item, SearchCallLog, Source
from . import registry
from .base import SearchError
from .quota import check_and_count

log = logging.getLogger("newswright.search.pipeline")


def fetch_search_source(db: Session, source: Source) -> SourceFetchStats:
    cfg_ = source.source_config or {}
    keyword = str(cfg_.get("keyword") or source.url)
    provider_name = str(cfg_.get("provider") or "bocha")
    group = str(cfg_.get("group") or "default")
    count = int(cfg_.get("count") or config.SEARCH_RESULT_ITEMS_PER_KEYWORD)
    opts: dict = {}
    if cfg_.get("freshness"):
        opts["freshness"] = cfg_["freshness"]

    stats = SourceFetchStats(source_id=source.id, url=source.url)

    # 额度闸：超限不发出调用，记 blocked 日志 + SKIPPED_QUOTA 语义
    allowed, state = check_and_count(db, provider_name)
    if not allowed:
        db.add(SearchCallLog(provider=provider_name, query=keyword, keyword_group=group,
                             result_count=0, latency_ms=0, ok=False, status="blocked",
                             error="SKIPPED_QUOTA"))
        db.commit()
        stats.extra["quota_blocked"] = True
        stats.extra["quota_state"] = state
        log.info("关键词 %r 超出 %s 额度（SKIPPED_QUOTA），下轮自然恢复", keyword, provider_name)
        return stats

    try:
        provider = registry.get_provider(provider_name)
        t0 = time.monotonic()
        results = provider.search(keyword, count=count, **opts)
        latency_ms = int((time.monotonic() - t0) * 1000)
    except SearchError as e:
        db.add(SearchCallLog(provider=provider_name, query=keyword, keyword_group=group,
                             result_count=0, latency_ms=0, ok=False, status="error",
                             error=str(e)[:500]))
        db.commit()
        stats.error = f"search: {e}"
        return stats

    db.add(SearchCallLog(provider=provider_name, query=keyword, keyword_group=group,
                         result_count=len(results), latency_ms=latency_ms,
                         ok=True, status="ok"))
    stats.feed_entries = len(results)
    stats.extra["provider"] = provider_name
    stats.extra["latency_ms"] = latency_ms

    for r in results:
        guid = normalize_url(r.url)
        if not guid:
            stats.guid_collisions += 1
            continue
        exists = db.query(Item.id).filter_by(source_id=source.id, guid=guid).one_or_none()
        if exists:
            stats.dup_blocked += 1
            continue
        body = (r.content or r.snippet or "").strip()
        item = Item(
            source_id=source.id, guid=guid[:1000], url=r.url[:2000],
            title=r.title[:2000], published_at=r.published_at,
            content_text=body, raw=r.raw or None,
            fetched_at=datetime.now(timezone.utc),
        )
        rule = apply_rules(title=item.title, content_text=item.content_text,
                           published_at=item.published_at,
                           max_age_days=int(cfg_.get("max_age_days") or 365))
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
        stats.inserted += 1

    db.commit()
    return stats
