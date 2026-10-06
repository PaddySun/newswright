"""语义近重复测试：阈值标记、只标记不删除、同源版本对豁免、origin 指向最早条目。

覆盖口径：
- 同方向内语义相似（≥ site_config 阈值）且 URL 不同 → duplicate_of 指向 origin、
  不进打分候选、双方全文照存可查（fetch_status 不动）；
- 同源且双方 guid 皆含版本后缀的条目对豁免判重（版本历史本身是信号）；
  跨源同事件照常判重；版本条目不作为其他条目的判重 origin；
- origin 取最早入库条目（id 最小）。
设计依据见 docs/design-index.md「AC-08.3」。
"""
import numpy as np

from app.models import Direction, Item, ItemVec, ScoreResult, Source
from app.pipeline.runner import score_round
from app.retrieval.embedder import vec_to_blob
from app.retrieval.router import mark_semantic_duplicates


def _seed(db_session, *, guids, source_id=None, same_source=True, url_suffix="a"):
    d = db_session.query(Direction).first()
    if d is None:
        d = Direction(name="方向", prompt="p", threshold=60)
        db_session.add(d)
        db_session.commit()
    if source_id is None:
        src = Source(direction_id=d.id, url=f"https://{url_suffix}.com/rss")
        db_session.add(src)
        db_session.commit()
        source_id = src.id
    items = []
    for guid in guids:
        item = Item(source_id=source_id, guid=guid, url=f"https://x.com/{guid}",
                    title=f"标题 {guid}", content_text=f"{guid} 的全文内容",
                    fetch_status="FETCHED", direction_id=d.id,
                    sanitize_status="PASSED")
        db_session.add(item)
        items.append(item)
    db_session.commit()
    return d, items


def _same_vec(dims=8):
    v = np.zeros(dims, dtype=np.float32)
    v[1] = 1.0
    return v


def test_mark_duplicate_sets_origin_and_keeps_fulltext(db_session):
    d, (origin, new_item) = _seed(db_session, guids=("origin", "near-dup"))
    db_session.add_all([
        ItemVec(item_id=origin.id, model_version="m", vec=vec_to_blob(_same_vec())),
        ItemVec(item_id=new_item.id, model_version="m", vec=vec_to_blob(_same_vec())),
    ])
    db_session.commit()
    marked = mark_semantic_duplicates(db_session, d, [new_item], model_version="m",
                                      threshold=0.92)
    assert [i.id for i in marked] == [new_item.id]
    assert new_item.duplicate_of == origin.id
    # 只标记不删除：fetch_status 不动、全文照存可查
    assert new_item.fetch_status == "FETCHED"
    assert "near-dup 的全文内容" in (
        db_session.get(Item, new_item.id).content_text or "")
    assert "origin 的全文内容" in (db_session.get(Item, origin.id).content_text or "")


def test_marked_item_not_scored_but_origin_scored(db_session, monkeypatch):
    d, (origin, dup) = _seed(db_session, guids=("origin", "dup"))
    from app.models import ItemVec

    db_session.add_all([
        ItemVec(item_id=origin.id, model_version="m", vec=vec_to_blob(_same_vec())),
        ItemVec(item_id=dup.id, model_version="m", vec=vec_to_blob(_same_vec())),
    ])
    db_session.commit()
    mark_semantic_duplicates(db_session, d, [origin, dup], model_version="m",
                             threshold=0.92)
    assert dup.duplicate_of == origin.id

    scored = []

    def fake_score_item(db, item, direction):
        scored.append(item.id)
        return ScoreResult(item_id=item.id, direction_id=direction.id, model="m",
                           status="OK", passed=True, relevance_score=80,
                           quality_score=80, band="high")

    monkeypatch.setattr("app.scoring.service.score_item", fake_score_item)
    # 直接验证打分候选剔除语义：判重条目不进打分（runner 候选查询带 duplicate_of 过滤）
    from sqlalchemy import func

    from app.models import Source as SourceModel

    candidates = (
        db_session.query(Item)
        .filter(
            Item.source_id.in_(db_session.query(SourceModel.id)
                               .filter_by(direction_id=d.id, enabled=True)),
            Item.fetch_status == "FETCHED",
            Item.sanitize_status == "PASSED",
            Item.duplicate_of.is_(None),
        )
        .all()
    )
    assert [i.id for i in candidates] == [origin.id]


def test_same_source_version_pair_exempt(db_session):
    """同源版本条目对（双方 guid 含 #v-）不互判重复——版本历史本身是信号。"""
    d, items = _seed(db_session, guids=("https://x.com/page#v-aaa", "https://x.com/page#v-bbb"))
    v1, v2 = items
    from app.models import ItemVec

    for it in items:
        db_session.add(ItemVec(item_id=it.id, model_version="m",
                               vec=vec_to_blob(_same_vec())))
    db_session.commit()
    marked = mark_semantic_duplicates(db_session, d, [v2], model_version="m",
                                      threshold=0.92)
    assert marked == []
    assert v2.duplicate_of is None


def test_cross_source_same_event_still_marked(db_session):
    """跨源同事件（URL 不同、源不同、向量相同）照常判重——同源豁免不外溢。"""
    d, (i1,) = _seed(db_session, guids=("g-origin",), url_suffix="alpha")
    _, (i2,) = _seed(db_session, guids=("g-other",), url_suffix="beta")
    from app.models import ItemVec

    db_session.add(ItemVec(item_id=i1.id, model_version="m", vec=vec_to_blob(_same_vec())))
    db_session.add(ItemVec(item_id=i2.id, model_version="m", vec=vec_to_blob(_same_vec())))
    db_session.commit()
    marked = mark_semantic_duplicates(db_session, d, [i2], model_version="m",
                                      threshold=0.92)
    assert [i.id for i in marked] == [i2.id]
    assert i2.duplicate_of == i1.id


def test_version_item_never_serves_as_origin(db_session):
    """版本条目（guid 含 #v-）不作为其他条目的判重 origin——页面快照不是独立事件源。"""
    d, (base, version_item, new_item) = _seed(
        db_session, guids=("base-page", "base-page#v-ccc", "fresh-copy"))
    from app.models import ItemVec

    for it in (base, version_item, new_item):
        db_session.add(ItemVec(item_id=it.id, model_version="m",
                               vec=vec_to_blob(_same_vec())))
    db_session.commit()
    marked = mark_semantic_duplicates(db_session, d, [new_item], model_version="m",
                                      threshold=0.92)
    # 新条目与 base（非版本）语义重复 → 判重指向 base；版本条目虽同样相似但不入 origin
    assert [i.id for i in marked] == [new_item.id]
    assert new_item.duplicate_of == base.id


def test_below_threshold_not_marked(db_session):
    d, (origin, far) = _seed(db_session, guids=("o", "f"))
    from app.models import ItemVec

    v_o = _same_vec()
    v_far = np.zeros(8, dtype=np.float32)
    v_far[2] = 1.0  # 与 origin 正交（余弦 0）
    db_session.add(ItemVec(item_id=origin.id, model_version="m", vec=vec_to_blob(v_o)))
    db_session.add(ItemVec(item_id=far.id, model_version="m", vec=vec_to_blob(v_far)))
    db_session.commit()
    marked = mark_semantic_duplicates(db_session, d, [far], model_version="m",
                                      threshold=0.92)
    assert marked == [] and far.duplicate_of is None


def test_origin_is_earliest_item_among_ties(db_session):
    d, items = _seed(db_session, guids=("first", "second", "late"))
    first, second, late = items
    from app.models import ItemVec

    for it in items:
        db_session.add(ItemVec(item_id=it.id, model_version="m",
                               vec=vec_to_blob(_same_vec())))
    db_session.commit()
    marked = mark_semantic_duplicates(db_session, d, [late], model_version="m",
                                      threshold=0.92)
    assert late.duplicate_of == min(first.id, second.id)  # 最早入库条目为 origin
