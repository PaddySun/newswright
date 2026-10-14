"""条目详情端点契约测试（GET /api/items/{item_id}——UI2 W0a，服务 P4 条目
落地页）。

覆盖口径：200 全字段（含各方向打分各取最新一条 + 方向名）；不存在 → 404
coded ITEM_NOT_FOUND；URL 域名解析失败为 null；DUP 条目全文可查（全文照存
语义，AC-18.2）；来源未配名时 name=null 原样透出（呈现缺省=域名归前端）。
设计依据见 docs/design-index.md「AC-18.2」「L1」。
"""
from datetime import datetime, timezone

import pytest

from app.models import Direction, Item, ScoreResult, Source


@pytest.fixture()
def scored_item_two_directions(db_session):
    """一条目 × 两方向打分：方向 A 两条（旧 FAILED + 新 OK——多次打分取最新），
    方向 B 一条 OK。来源 URL 带端口与大写主机（域名解析口径断言面）。"""
    dir_a = Direction(name="方向A", prompt="pa", prompt_version=2)
    dir_b = Direction(name="方向B", prompt="pb", prompt_version=1)
    db_session.add_all([dir_a, dir_b])
    db_session.commit()
    src = Source(direction_id=dir_a.id, url="https://Arxiv.org:8443/rss/feed.xml")
    db_session.add(src)
    db_session.commit()
    published = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
    fetched = datetime(2026, 10, 2, 9, 30, tzinfo=timezone.utc)
    item = Item(source_id=src.id, guid="g-detail", url="https://example.org/paper",
                title="详情条目标题", content_text="条目全文内容，超过最小长度。",
                published_at=published, fetched_at=fetched, fetch_status="FETCHED",
                sanitize_status="PASSED")
    db_session.add(item)
    db_session.commit()
    old_failed = ScoreResult(item_id=item.id, direction_id=dir_a.id,
                             quality_score=10, relevance_score=20, band="low",
                             reason="旧分（失败轮）", prompt_version=1, model="m-old",
                             passed=False, status="FAILED")
    new_ok = ScoreResult(item_id=item.id, direction_id=dir_a.id,
                         quality_score=80, relevance_score=92, band="high",
                         reason="新分（重试后）", prompt_version=2, model="m-new",
                         passed=True, status="OK")
    score_b = ScoreResult(item_id=item.id, direction_id=dir_b.id,
                          quality_score=70, relevance_score=75, band="mid",
                          reason="方向B的分", prompt_version=1, model="m-b",
                          passed=False, status="OK")
    db_session.add_all([old_failed, new_ok, score_b])
    db_session.commit()
    return {"item": item, "dir_a": dir_a, "dir_b": dir_b, "source": src}


def test_item_detail_returns_full_contract_fields(auth_client,
                                                  scored_item_two_directions):
    seeded = scored_item_two_directions
    r = auth_client.get(f"/api/items/{seeded['item'].id}")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "id", "title", "url", "published_at", "fetched_at", "fetch_status",
        "rule_reject_reason", "content_text", "sanitize_status", "sanitize_reason",
        "sanitize_detail", "source_keyword", "duplicate_of", "source", "scores",
    }
    assert body["content_text"] == "条目全文内容，超过最小长度。"
    assert body["fetch_status"] == "FETCHED"
    assert body["published_at"] is not None and body["fetched_at"] is not None
    # 域名解析：小写、无端口、无 scheme
    assert body["source"]["domain"] == "arxiv.org"
    assert body["source"]["url"] == seeded["source"].url
    assert body["source"]["id"] == seeded["source"].id


def test_item_detail_scores_latest_per_direction(auth_client,
                                                 scored_item_two_directions):
    """每个 direction_id 取最新一条（ORDER BY id DESC 取首）：方向 A 出新 OK
    不出旧 FAILED；方向名 join 在位。"""
    seeded = scored_item_two_directions
    body = auth_client.get(f"/api/items/{seeded['item'].id}").json()
    scores = body["scores"]
    assert len(scores) == 2
    by_direction = {s["direction_id"]: s for s in scores}
    a = by_direction[seeded["dir_a"].id]
    assert a["status"] == "OK" and a["model"] == "m-new"
    assert a["quality"] == 80 and a["relevance"] == 92
    assert a["band"] == "high" and a["passed"] is True
    assert a["reason"] == "新分（重试后）" and a["prompt_version"] == 2
    assert a["direction_name"] == "方向A"
    assert a["created_at"] is not None
    b = by_direction[seeded["dir_b"].id]
    assert b["status"] == "OK" and b["direction_name"] == "方向B"
    assert b["passed"] is False


def test_item_detail_not_found_coded_error(auth_client):
    r = auth_client.get("/api/items/99999")
    assert r.status_code == 404
    assert r.json() == {"code": "ITEM_NOT_FOUND",
                        "message": "条目不存在（可能已被清理）"}


def test_item_detail_unparsable_urls_yield_null_domain(auth_client, db_session):
    """条目 url 与来源 url 均解析不出主机名时 domain 为 null（不抛错）。"""
    d = Direction(name="域名解析方向", prompt="p")
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="::not-a-url")
    db_session.add(src)
    db_session.commit()
    item = Item(source_id=src.id, guid="g-badurl", url="not a url at all",
                title="无主机名条目", content_text="x")
    db_session.add(item)
    db_session.commit()
    body = auth_client.get(f"/api/items/{item.id}").json()
    assert "domain" not in body  # 顶层无 domain 字段（契约：domain 在 source 对象内）
    assert body["source"]["domain"] is None


def test_item_detail_dup_item_full_text_readable(auth_client, db_session):
    """DUP 条目同样可查：全文照存语义（AC-18.2），duplicate_of 指向原条目。"""
    d = Direction(name="DUP方向", prompt="p")
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://dup.example/feed")
    db_session.add(src)
    db_session.commit()
    original = Item(source_id=src.id, guid="g-orig", url="https://dup.example/a",
                    title="原条目", content_text="原文", fetch_status="FETCHED")
    db_session.add(original)
    db_session.commit()
    dup = Item(source_id=src.id, guid="g-dup", url="https://dup.example/a?utm=x",
               title="重复条目", content_text="重复条目也存了全文",
               fetch_status="DUP", duplicate_of=original.id)
    db_session.add(dup)
    db_session.commit()
    r = auth_client.get(f"/api/items/{dup.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["fetch_status"] == "DUP"
    assert body["duplicate_of"] == original.id
    assert body["content_text"] == "重复条目也存了全文"


def test_item_detail_source_name_null_passthrough(auth_client,
                                                  scored_item_two_directions):
    """未配名来源 name=null 原样透出——后端不兜底拼接域名（呈现缺省归前端）。"""
    body = auth_client.get(
        f"/api/items/{scored_item_two_directions['item'].id}").json()
    assert body["source"]["name"] is None
