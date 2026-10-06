"""阅读集域名硬约束测试（产品书 US-11.1 多样性句，设计依据见
docs/design-index.md「AC-11.1」多样性约束）：每源域名至多
site_config.reading_set_domain_cap（默认 3）条进阅读集，超出截断并留痕计数。
MMR 软选样为二期可选项，不在本批（断言面只覆盖硬约束）。
"""
from datetime import datetime, timezone

import pytest

from app.authors.writer import assemble_ranked_reading_set
from app.models import Author, Direction, Item, ScoreResult, Source
from app.siteconfig import set_config


@pytest.fixture()
def domain_heavy_author(db_session):
    """可读方向 1（阈值 60）：同一域名 5 条高分条目 + 另一域名 3 条——
    阅读集默认 K=10 全装得下，域名的分布形态才是被测面。"""
    d = Direction(name="多样性方向", prompt="p", prompt_version=1, threshold=60)
    db_session.add(d)
    db_session.commit()
    src_a = Source(direction_id=d.id, url="https://a.example/feed", type="rss")
    src_b = Source(direction_id=d.id, url="https://b.example/feed", type="rss")
    db_session.add_all([src_a, src_b])
    db_session.commit()
    author = Author(name="多样性作者", model="m",
                    readable_directions=[{"direction_id": d.id, "threshold": 60}],
                    rank_provider="none")
    db_session.add(author)
    now = datetime.now(timezone.utc)
    for i, (src, url, score) in enumerate([
        (src_a, "https://a.example/news-1", 95),
        (src_a, "https://a.example/news-2", 92),
        (src_a, "https://a.example/news-3", 90),
        (src_a, "https://a.example/news-4", 88),
        (src_a, "https://a.example/news-5", 86),
        (src_b, "https://b.example/post-1", 84),
        (src_b, "https://b.example/post-2", 82),
        (src_b, "https://b.example/post-3", 80),
    ]):
        item = Item(source_id=src.id, guid=f"g{i}", url=url, title=f"t{i}",
                    content_text="正文" * 100, published_at=now,
                    fetch_status="FETCHED", direction_id=d.id)
        db_session.add(item)
        db_session.flush()
        db_session.add(ScoreResult(item_id=item.id, direction_id=d.id,
                                   quality_score=score, relevance_score=score,
                                   band="high", reason="r", prompt_version=1,
                                   model="m", passed=True, status="OK"))
    db_session.commit()
    return author


def _domain_counts(pairs) -> dict[str, int]:
    from urllib.parse import urlparse

    counts: dict[str, int] = {}
    for item, _sr in pairs:
        domain = urlparse(item.url or "").netloc
        counts[domain] = counts.get(domain, 0) + 1
    return counts


def test_default_cap_limits_per_domain(db_session, domain_heavy_author):
    """默认 cap=3：a 域名 5 条只进 3 条，b 域名 3 条全进；截断 2 条留痕。"""
    pairs, meta = assemble_ranked_reading_set(db_session, domain_heavy_author)
    counts = _domain_counts(pairs)
    assert counts.get("a.example") == 3
    assert counts.get("b.example") == 3
    assert len(pairs) == 6
    assert meta["rank_provider"] == "none"
    assert meta["domain_capped"] == 2


def test_cap_configurable_via_site_config(db_session, domain_heavy_author):
    set_config(db_session, "reading_set_domain_cap", 1)
    pairs, meta = assemble_ranked_reading_set(db_session, domain_heavy_author)
    counts = _domain_counts(pairs)
    assert counts.get("a.example") == 1
    assert counts.get("b.example") == 1
    assert len(pairs) == 2
    assert meta["domain_capped"] == 6  # a 域名截 4 条 + b 域名截 2 条


def test_cap_zero_disables_limit(db_session, domain_heavy_author):
    set_config(db_session, "reading_set_domain_cap", 0)
    pairs, meta = assemble_ranked_reading_set(db_session, domain_heavy_author)
    counts = _domain_counts(pairs)
    assert counts.get("a.example") == 5
    assert meta["domain_capped"] == 0
