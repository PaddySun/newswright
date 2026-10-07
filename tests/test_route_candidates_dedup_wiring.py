"""打分路由判重接线测试：_route_candidates 对语义判重者的剔除链。

覆盖口径（DT-2 打分路由 + AC-08.3 近重复关联，设计依据见
docs/design-index.md「DT-2」）：
- 语义近重复标记返回的判重者被剔除出打分候选（方向：判重者出、保留者留）；
- 剔除链不得反转（判重者保留/保留者剔除都是路由语义破坏）；
- mark_semantic_duplicates 收到的 model_version 即当前嵌入模型口径（模型
  版本纪律——换模型历史向量视同无向量，防相似度漂移口径的接线前提）；
- ensure_item_vectors 收到的候选即本轮候选集（向量补齐的对象域）。
"""
import numpy as np

import app.pipeline.runner as runner_mod
from app.models import Direction, Item, Source
from app.retrieval.embedder import vec_to_blob


def _seed(db, n=2):
    d = Direction(name="判重接线方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://example.com/rss")
    db.add(src)
    db.commit()
    items = []
    for i in range(n):
        item = Item(source_id=src.id, guid=f"g{i}", url=f"https://example.com/{i}",
                    title=f"标题{i}", content_text="正文" * 100, fetch_status="FETCHED",
                    direction_id=d.id, sanitize_status="PASSED")
        db.add(item)
        items.append(item)
    db.commit()
    d.query_vec = vec_to_vec()
    d.query_vec_version = d.prompt_version
    db.commit()
    return d, items


def vec_to_vec():
    v = np.zeros(8, dtype=np.float32)
    v[0] = 1.0
    return vec_to_blob(v)


def test_marked_duplicate_excluded_from_candidates(db_session, monkeypatch):
    """判重者剔除出打分候选、保留者仍在（判重链方向性 + 候选实参接线）。"""
    d, items = _seed(db_session)
    dup, origin = items[0], items[1]
    seen = {}

    def fake_mark(db, direction, cands, *, model_version, **kw):
        seen["cands"] = list(cands)
        return [dup]

    monkeypatch.setattr("app.retrieval.embedder.ensure_item_vectors",
                        lambda db, its, **kw: None)
    monkeypatch.setattr("app.retrieval.query.ensure_direction_query_vec",
                        lambda db, direction, **kw: True)
    monkeypatch.setattr("app.retrieval.query.direction_query_vector",
                        lambda direction: None)
    monkeypatch.setattr("app.retrieval.router.partition_items",
                        lambda db, direction, cands, **kw: (list(cands),
                                                            {"routed_hits": 0,
                                                             "routed_misses": len(cands)}))
    monkeypatch.setattr("app.retrieval.router.mark_semantic_duplicates", fake_mark)
    ordered, stats = runner_mod._route_candidates(db_session, d, list(items))
    assert [i.id for i in ordered] == [origin.id]
    assert [i.id for i in seen["cands"]] == [i.id for i in items]


def test_mark_receives_current_model_version(db_session, monkeypatch):
    """mark_semantic_duplicates 收到当前嵌入模型口径（model_version 接线）+ 查询
    就绪检查收到执行会话（ensure db 实参透传）。"""
    d, items = _seed(db_session)
    seen = {}

    def fake_mark(db, direction, cands, *, model_version, **kw):
        seen["model_version"] = model_version
        return []

    def fake_ensure(db, direction, **kw):
        seen["ensure_db"] = db
        return True

    monkeypatch.setattr("app.retrieval.embedder.ensure_item_vectors",
                        lambda db, its, **kw: None)
    monkeypatch.setattr("app.retrieval.query.ensure_direction_query_vec", fake_ensure)
    monkeypatch.setattr("app.retrieval.query.direction_query_vector",
                        lambda direction: None)
    monkeypatch.setattr("app.retrieval.router.partition_items",
                        lambda db, direction, cands, **kw: (list(cands), {}))
    monkeypatch.setattr("app.retrieval.router.mark_semantic_duplicates", fake_mark)
    runner_mod._route_candidates(db_session, d, list(items))
    import app.config as cfg

    assert seen["model_version"] == cfg.MOARK_EMBED_MODEL
    assert seen["ensure_db"] is db_session


def test_ensure_item_vectors_receives_candidate_list(db_session, monkeypatch):
    """向量补齐的对象域 = 本轮候选集（None 化即路由退化，接线契约）。"""
    d, items = _seed(db_session)
    seen = {}

    def fake_ensure(db, its, **kw):
        seen["ids"] = [i.id for i in (its or [])]
        return None

    monkeypatch.setattr("app.retrieval.embedder.ensure_item_vectors", fake_ensure)
    monkeypatch.setattr("app.retrieval.query.ensure_direction_query_vec",
                        lambda db, direction, **kw: True)
    monkeypatch.setattr("app.retrieval.query.direction_query_vector",
                        lambda direction: None)
    monkeypatch.setattr("app.retrieval.router.partition_items",
                        lambda db, direction, cands, **kw: (list(cands), {}))
    monkeypatch.setattr("app.retrieval.router.mark_semantic_duplicates",
                        lambda db, direction, cands, **kw: [])
    runner_mod._route_candidates(db_session, d, list(items))
    assert seen["ids"] == [i.id for i in items]
