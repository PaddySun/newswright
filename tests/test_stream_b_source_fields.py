"""B 流条目来源字段测试（GET /api/stream/b 增 source_name/domain/published_at
——UI2 W0a，服务 P1 卡片）。

覆盖口径：items[] 与 unscored[] 每条三新字段在位（domain 由条目 url 解析，
小写无端口；source_name 为 Source.name，未配名存量源为 null；published_at
为条目列原值可 null）；既有字段与顶层 interleave/explore/unscored 结构不回归；
来源配名后 source_name 透出该名。
设计依据见 docs/design-index.md「L1」「AC-14.x」。
"""
from datetime import datetime, timezone

import pytest

from app.models import Direction, Item, PipelineTask, ScoreResult, Source


def _seed_stream(db, *, source_name=None, url="https://Feed.Example:8443/rss"):
    d = Direction(name="来源字段方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url=url, name=source_name)
    db.add(src)
    db.commit()
    published = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    items = []
    for i in range(3):
        item = Item(source_id=src.id, guid=f"g-stream{i}",
                    url=f"https://example.com/article/{i}",
                    title=f"流条目{i}", content_text=f"正文{i}",
                    published_at=published if i == 0 else None,
                    fetch_status="FETCHED", sanitize_status="PASSED",
                    direction_id=d.id)
        db.add(item)
        items.append(item)
    db.commit()
    for item in items:
        db.add(ScoreResult(item_id=item.id, direction_id=d.id,
                           quality_score=70, relevance_score=80 + item.id,
                           band="high", reason="r", prompt_version=1,
                           model="m", passed=True, status="OK"))
    db.commit()
    return d, src, items


def test_stream_b_items_carry_source_name_domain_published_at(auth_client,
                                                              db_session):
    d, src, items = _seed_stream(db_session)
    body = auth_client.get("/api/stream/b", params={"direction_id": d.id}).json()
    assert len(body["items"]) == 3
    cards = {card["id"]: card for card in body["items"]}
    for item in items:
        card = cards[item.id]
        # 三新字段
        assert card["source_name"] is None  # 未配名存量源
        assert card["domain"] == "example.com"
        if item.published_at is not None:
            # SQLite 往返为 naive UTC——按日期前缀断言（不逐字比对时区形态）
            assert card["published_at"] is not None
            assert card["published_at"].startswith("2026-10-03")
        else:
            assert card["published_at"] is None
        # 既有字段不回归
        for field in ("id", "title", "url", "relevance", "quality", "band",
                      "reason", "source_id"):
            assert field in card
        assert card["source_id"] == src.id


def test_stream_b_top_level_structure_not_regressed(auth_client, db_session):
    """顶层结构零变动：items/interleave/explore/unscored 四键仍在，interleave
    元信息形态不变（enabled/probability/inserted）。"""
    d, _, _ = _seed_stream(db_session)
    body = auth_client.get("/api/stream/b", params={"direction_id": d.id}).json()
    assert set(body) == {"items", "interleave", "explore", "unscored"}
    assert set(body["interleave"]) == {"enabled", "probability", "inserted"}
    assert set(body["explore"]) == {"enabled", "inserted"}
    assert body["unscored"] == []


def test_stream_b_named_source_outputs_source_name(auth_client, db_session):
    d, _, _ = _seed_stream(db_session, source_name="我的订阅源")
    body = auth_client.get("/api/stream/b", params={"direction_id": d.id}).json()
    assert all(card["source_name"] == "我的订阅源" for card in body["items"])


def test_stream_b_unscored_entries_carry_three_fields(auth_client, db_session):
    """unscored 标注列表（近期打分失败时的合法降级稳态）同样带三新字段，
    既有 flag/note 标注不回归。"""
    d, src, items = _seed_stream(db_session)
    db_session.add(PipelineTask(kind="score", status="FAILED",
                                payload={}, last_error="stub"))
    db_session.commit()
    extra = Item(source_id=src.id, guid="g-unscored",
                 url="https://example.com/late-entry", title="未评分条目",
                 content_text="全文在", fetch_status="FETCHED",
                 sanitize_status="PASSED", direction_id=d.id,
                 published_at=datetime(2026, 10, 4, tzinfo=timezone.utc))
    db_session.add(extra)
    db_session.commit()
    body = auth_client.get("/api/stream/b", params={"direction_id": d.id}).json()
    hits = [u for u in body["unscored"] if u["id"] == extra.id]
    assert len(hits) == 1
    entry = hits[0]
    assert entry["flag"] == "unscored" and entry["note"] == "暂未评分"
    assert entry["source_name"] is None
    assert entry["domain"] == "example.com"
    assert entry["published_at"] is not None
