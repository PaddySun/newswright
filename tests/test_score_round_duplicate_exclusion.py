"""打分轮判重排除测试：duplicate_of 已指向 origin 的条目不进打分。

覆盖口径（DT-2 打分路由「重复不打分」+ AC-08.3 近重复关联，设计依据见
docs/design-index.md「DT-2」）：判重条目（URL 指纹/语义近重复）已在入库时
标记 duplicate_of，score_round 候选查询必须排除——重复内容不烧打分 LLM。
"""
from app.models import Direction, Item, ScoreResult, Source
from app.pipeline.runner import score_round


def test_score_round_skips_duplicated_items(db_session, monkeypatch):
    d = Direction(name="判重排除方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://example.com/rss")
    db_session.add(src)
    db_session.commit()
    origin = Item(source_id=src.id, guid="o", url="https://example.com/o",
                  title="原文", content_text="正文" * 50, fetch_status="FETCHED",
                  direction_id=d.id, sanitize_status="PASSED")
    db_session.add(origin)
    db_session.flush()
    dup = Item(source_id=src.id, guid="d", url="https://example.com/d",
               title="判重条目", content_text="正文" * 50, fetch_status="FETCHED",
               direction_id=d.id, sanitize_status="PASSED",
               duplicate_of=origin.id)
    db_session.add(dup)
    db_session.commit()

    scored_ids = []

    def fake_score(db, item, direction):
        scored_ids.append(item.id)
        return ScoreResult(item_id=item.id, direction_id=direction.id, model="m",
                           status="OK", passed=True, relevance_score=80,
                           quality_score=80, band="high")

    monkeypatch.setattr("app.scoring.service.score_item", fake_score)
    monkeypatch.setattr("app.retrieval.embedder.ensure_item_vectors",
                        lambda db, its, **kw: None)
    monkeypatch.setattr("app.retrieval.query.ensure_direction_query_vec",
                        lambda db, direction, **kw: False)
    summary = score_round(db_session, triggered_by="test")
    assert scored_ids == [origin.id]
    assert summary["directions"][0]["scored"] == 1
