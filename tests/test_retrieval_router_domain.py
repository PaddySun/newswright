"""检索路由与语义判重域测试：方向内/同模型版本向量隔离、版本对豁免边界、
分桶排序语义（无向量条目继续参与、同分不崩、embed_disabled 桶统计）、
判重阈值配置语义与 origin 池推进语义。

覆盖口径：
- 方向内作用域（AC-08.3「同方向内」+D15）与同模型版本纪律（生产配置表
  model_version 纪律）：向量加载仅取目标方向、目标版本的向量；
- 版本对豁免=双方皆含版本后缀且同源（G3 裁定⑤三向之一：new 为版本条目而
  origin 为普通条目时不豁免，判重照常发生）；
- partition_items：候选集合不变、命中桶按相似度排序、无向量条目不截断其后
  条目的命中资格（AC-08.2/DT-2 零静默丢弃）、embed_disabled 态桶统计键
  （G3 W1b：payload.stats 落 routed_hits/routed_misses/embed_disabled）、
  同相似度并列不因排序键缺失而崩；
- mark_semantic_duplicates：site_config 阈值写入后生效（AC-08.3 阈值进
  site_config）、批内无向量条目不阻断后续条目判重、等值阈值判重（≥ 语义）、
  origin 池逐条推进（低相似 origin 不阻断后续高相似 origin、豁免对不阻断
  后续可判重 origin）。
设计依据见 docs/design-index.md「AC-08.2」「AC-08.3」「DT-2」。
"""
import numpy as np

from app.models import Direction, Item, ItemVec, Source
from app.retrieval.embedder import vec_to_blob
from app.retrieval.router import (
    _load_direction_vectors,
    mark_semantic_duplicates,
    partition_items,
)
from app.siteconfig import set_config


def _seed_direction(db, name="路由方向"):
    d = Direction(name=name, prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url=f"https://{name}.com/rss")
    db.add(src)
    db.commit()
    return d, src


def _mk_item(db, src, guid, direction_id):
    item = Item(source_id=src.id, guid=guid, url=f"https://x.com/{guid}",
                title=f"标题 {guid}", content_text=f"{guid} 全文",
                fetch_status="FETCHED", direction_id=direction_id,
                sanitize_status="PASSED")
    db.add(item)
    db.commit()
    return item


def _axis(axis, dims=8):
    v = np.zeros(dims, dtype=np.float32)
    v[axis] = 1.0
    return v


def _tilted(cos_x, dims=8):
    """与 x 轴 query=[1,0,...] 夹角确定的多维单位向量（首分量=cos）。"""
    v = np.zeros(dims, dtype=np.float32)
    v[0] = cos_x
    v[1] = (1 - cos_x ** 2) ** 0.5
    return v


# ---------- 向量加载隔离（方向内 / 同模型版本） ----------


def test_load_direction_vectors_scoped_to_direction_and_version(db_session):
    """向量加载只取目标方向、目标 model_version：跨方向向量不混入（键隔离）、
    跨版本向量不覆盖（值隔离——同条目旧版本向量不得顶替当前版本值）（AC-08.3
    方向内作用域 + model_version 纪律）。"""
    d1, src1 = _seed_direction(db_session, "方向一")
    d2, src2 = _seed_direction(db_session, "方向二")
    i1 = _mk_item(db_session, src1, "g1", d1.id)
    i2 = _mk_item(db_session, src2, "g2", d2.id)
    db_session.add(ItemVec(item_id=i1.id, model_version="m1", vec=vec_to_blob(_axis(0))))
    db_session.add(ItemVec(item_id=i2.id, model_version="m1", vec=vec_to_blob(_axis(1))))
    db_session.add(ItemVec(item_id=i1.id, model_version="m2", vec=vec_to_blob(_axis(2))))
    db_session.commit()

    vecs = _load_direction_vectors(db_session, d1.id, "m1")
    assert set(vecs.keys()) == {i1.id}
    assert np.allclose(vecs[i1.id], _axis(0), atol=1e-6)  # 值域=m1 向量而非 m2 顶替


# ---------- 版本对豁免边界（裁定⑤） ----------


def test_version_new_item_vs_plain_origin_still_marked(db_session):
    """new 为版本条目而 origin 为普通条目（同源、语义相同）：不构成豁免对，
    判重照常发生——豁免要求双方皆含版本后缀（G3 裁定⑤）。"""
    d, src = _seed_direction(db_session, "豁免域")
    origin = _mk_item(db_session, src, "plain-page", d.id)
    new_item = _mk_item(db_session, src, "plain-page#v-xyz", d.id)
    for it in (origin, new_item):
        db_session.add(ItemVec(item_id=it.id, model_version="m", vec=vec_to_blob(_axis(1))))
    db_session.commit()
    marked = mark_semantic_duplicates(db_session, d, [new_item], model_version="m",
                                      threshold=0.92)
    assert [i.id for i in marked] == [new_item.id]
    assert new_item.duplicate_of == origin.id


# ---------- partition_items：分桶语义 ----------


def test_partition_items_embed_disabled_bucket_stats_keys(db_session):
    """查询向量未就绪（embed_disabled 态）：全体按未命中，桶统计键携带真实
    候选数（G3 W1b payload.stats 键口径）。"""
    d, src = _seed_direction(db_session, "禁用态")
    items = [_mk_item(db_session, src, f"g{i}", d.id) for i in range(3)]
    ordered, stats = partition_items(db_session, d, list(items), query_vec=None,
                                     model_version="m")
    assert len(ordered) == 3
    assert stats["routed_misses"] == 3
    assert stats["routed_hits"] == 0
    assert stats["embed_disabled"] is True


def test_partition_items_no_vector_item_does_not_truncate_hits(db_session):
    """批内无向量条目不阻断其后条目的命中资格：高相似有向量条目仍进命中桶
    （AC-08.2 命中优先、零静默丢弃）。"""
    d, src = _seed_direction(db_session, "无向量截断")
    no_vec = _mk_item(db_session, src, "g-novec", d.id)
    hit = _mk_item(db_session, src, "g-hit", d.id)
    db_session.add(ItemVec(item_id=hit.id, model_version="m", vec=vec_to_blob(_axis(0))))
    db_session.commit()
    ordered, stats = partition_items(db_session, d, [no_vec, hit],
                                     query_vec=_axis(0), model_version="m", top_k=1)
    assert [i.id for i in ordered] == [hit.id, no_vec.id]
    assert stats["routed_hits"] == 1


def test_partition_items_tied_similarity_does_not_crash(db_session):
    """两候选相似度并列：排序完成、候选集合不变（命中排序语义在并列场景的
    功能正确性）。"""
    d, src = _seed_direction(db_session, "并列")
    a = _mk_item(db_session, src, "g-a", d.id)
    b = _mk_item(db_session, src, "g-b", d.id)
    for it in (a, b):
        db_session.add(ItemVec(item_id=it.id, model_version="m", vec=vec_to_blob(_axis(0))))
    db_session.commit()
    ordered, stats = partition_items(db_session, d, [a, b], query_vec=_axis(0),
                                     model_version="m", top_k=2)
    assert {i.id for i in ordered} == {a.id, b.id}
    assert stats["routed_hits"] == 2


# ---------- mark_semantic_duplicates：阈值与 origin 池推进 ----------


def test_mark_duplicates_site_config_threshold_takes_effect(db_session):
    """阈值经 site_config 写入后生效：相似度 0.7 在配置阈值 0.5 下判重、在缺省
    0.92 下不判重（AC-08.3 阈值进 site_config 可标定）。"""
    d, src = _seed_direction(db_session, "阈值域")
    origin = _mk_item(db_session, src, "g-origin", d.id)
    new_item = _mk_item(db_session, src, "g-new", d.id)
    db_session.add(ItemVec(item_id=origin.id, model_version="m", vec=vec_to_blob(_axis(0))))
    db_session.add(ItemVec(item_id=new_item.id, model_version="m",
                           vec=vec_to_blob(_tilted(0.7))))
    db_session.commit()

    set_config(db_session, "semantic_dedup_threshold", 0.5)
    marked = mark_semantic_duplicates(db_session, d, [new_item], model_version="m")
    assert [i.id for i in marked] == [new_item.id]
    assert new_item.duplicate_of == origin.id

    new_item.duplicate_of = None
    db_session.commit()
    set_config(db_session, "semantic_dedup_threshold", 0.92)
    marked_default = mark_semantic_duplicates(db_session, d, [new_item],
                                              model_version="m")
    assert marked_default == []


def test_mark_duplicates_no_vector_item_does_not_block_batch(db_session):
    """批内靠前条目无向量：跳过该条目后继续判重其后条目（渐进补齐常态混合批）。"""
    d, src = _seed_direction(db_session, "混批")
    origin = _mk_item(db_session, src, "g-origin", d.id)
    no_vec = _mk_item(db_session, src, "g-novec", d.id)
    dup = _mk_item(db_session, src, "g-dup", d.id)
    db_session.add(ItemVec(item_id=origin.id, model_version="m", vec=vec_to_blob(_axis(1))))
    db_session.add(ItemVec(item_id=dup.id, model_version="m", vec=vec_to_blob(_axis(1))))
    db_session.commit()
    marked = mark_semantic_duplicates(db_session, d, [no_vec, dup], model_version="m",
                                      threshold=0.92)
    assert [i.id for i in marked] == [dup.id]
    assert dup.duplicate_of == origin.id


def test_mark_duplicates_exact_threshold_boundary_marks(db_session):
    """相似度恰等于阈值：判重发生（≥ 阈值语义，AC-08.3 达阈值）。"""
    d, src = _seed_direction(db_session, "等值域")
    origin = _mk_item(db_session, src, "g-origin", d.id)
    new_item = _mk_item(db_session, src, "g-new", d.id)
    db_session.add(ItemVec(item_id=origin.id, model_version="m", vec=vec_to_blob(_axis(3))))
    db_session.add(ItemVec(item_id=new_item.id, model_version="m", vec=vec_to_blob(_axis(3))))
    db_session.commit()
    marked = mark_semantic_duplicates(db_session, d, [new_item], model_version="m",
                                      threshold=1.0)
    assert [i.id for i in marked] == [new_item.id]


def test_mark_duplicates_low_similarity_origin_does_not_block(db_session):
    """origin 池中低相似条目不阻断后续高相似条目的判重：dup 指向高相似 origin。"""
    d, src = _seed_direction(db_session, "推进域")
    far_origin = _mk_item(db_session, src, "g-far", d.id)
    near_origin = _mk_item(db_session, src, "g-near", d.id)
    dup = _mk_item(db_session, src, "g-dup", d.id)
    db_session.add(ItemVec(item_id=far_origin.id, model_version="m",
                           vec=vec_to_blob(_tilted(0.3))))
    db_session.add(ItemVec(item_id=near_origin.id, model_version="m",
                           vec=vec_to_blob(_axis(0))))
    db_session.add(ItemVec(item_id=dup.id, model_version="m", vec=vec_to_blob(_axis(0))))
    db_session.commit()
    marked = mark_semantic_duplicates(db_session, d, [dup], model_version="m",
                                      threshold=0.92)
    assert [i.id for i in marked] == [dup.id]
    assert dup.duplicate_of == near_origin.id


def test_mark_duplicates_exempt_origin_does_not_block(db_session):
    """origin 池中的同源版本条目（与 new 构成豁免对）不阻断其后普通条目的判重：
    new（版本条目）仍指向普通 origin（裁定⑤：豁免对跳过不中止遍历）。"""
    d, src = _seed_direction(db_session, "豁免推进")
    version_origin = _mk_item(db_session, src, "page#v-old", d.id)
    near_origin = _mk_item(db_session, src, "g-near", d.id)
    new_version_item = _mk_item(db_session, src, "page#v-new", d.id)
    db_session.add(ItemVec(item_id=version_origin.id, model_version="m",
                           vec=vec_to_blob(_axis(1))))
    db_session.add(ItemVec(item_id=near_origin.id, model_version="m",
                           vec=vec_to_blob(_axis(1))))
    db_session.add(ItemVec(item_id=new_version_item.id, model_version="m",
                           vec=vec_to_blob(_axis(1))))
    db_session.commit()
    marked = mark_semantic_duplicates(db_session, d, [new_version_item],
                                      model_version="m", threshold=0.92)
    assert [i.id for i in marked] == [new_version_item.id]
    assert new_version_item.duplicate_of == near_origin.id
