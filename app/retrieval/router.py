"""打分路由与语义近重复：命中优先、未命中慢速、零静默丢弃。

- partition_items 只改顺序不改候选集合：有查询向量且有自身向量的条目按与方向
  查询的余弦相似度取 top-K 为命中桶排在前，其余（无向量/未命中）排后照常打分。
  嵌入禁用/查询未就绪时全体按未命中处理（全量慢速的内建回退路径）。
- mark_semantic_duplicates 只标记不删除：同方向内余弦相似度达阈值的条目落
  duplicate_of 引用（与 URL 指纹同列承载），不进打分、fetch_status 不动、全文照存。
  同源版本条目对（双方 guid 皆含 #v- 版本后缀）豁免判重；版本条目不作为其他
  条目的判重 origin（页面快照不是独立事件源）。
设计依据见 docs/design-index.md「AC-08.2」「AC-08.3」。
"""
from __future__ import annotations

import logging

import numpy as np
from sqlalchemy.orm import Session

from .. import config
from ..siteconfig import get_config
from ..models import Item, ItemVec, Source
from .embedder import blob_to_vec, cosine_similarity

log = logging.getLogger("newswright.retrieval")

VERSION_SUFFIX_MARK = "#v-"


def is_version_item(item: Item) -> bool:
    """定点监测版本条目判定：guid 带版本后缀（变更追踪语义，每版本即信号本身）。"""
    return VERSION_SUFFIX_MARK in (item.guid or "")


def _is_exempt_pair(new_item: Item, origin: Item) -> bool:
    """判重豁免对：同源且双方皆版本条目（同源版本历史不互判重复）。"""
    return (new_item.source_id == origin.source_id
            and is_version_item(new_item) and is_version_item(origin))


def _load_direction_vectors(db: Session, direction_id: int,
                            model_version: str) -> dict[int, np.ndarray]:
    """方向内已有向量（同模型版本）：item_id → 向量。"""
    rows = (
        db.query(ItemVec.item_id, ItemVec.vec)
        .join(Item, ItemVec.item_id == Item.id)
        .join(Source, Item.source_id == Source.id)
        .filter(Source.direction_id == direction_id,
                ItemVec.model_version == model_version)
        .all()
    )
    return {item_id: blob_to_vec(vec) for item_id, vec in rows}


def partition_items(
    db: Session,
    direction,
    candidates: list[Item],
    *,
    query_vec: np.ndarray | None,
    model_version: str | None = None,
    top_k: int | None = None,
) -> tuple[list[Item], dict]:
    """路由分桶（纯逻辑）：命中桶在前、其余在后，候选集合不变。

    返回 (排序后条目, 桶统计)。统计键：
    - routed_hits / routed_misses：命中 top-K 与未命中（含无向量）条数；
    - embed_disabled：嵌入禁用或查询向量未就绪（全体按未命中的回退态标记）。
    """
    stats = {"routed_hits": 0, "routed_misses": 0, "embed_disabled": False}
    if not candidates:
        return [], stats
    if query_vec is None or not model_version:
        stats["embed_disabled"] = True
        stats["routed_misses"] = len(candidates)
        return list(candidates), stats
    vecs = _load_direction_vectors(db, direction.id, model_version)
    k = top_k if top_k is not None else int(get_config(db, "retrieval_top_k") or 5)
    scored: list[tuple[float, Item]] = []
    no_vec: list[Item] = []
    for item in candidates:
        vec = vecs.get(item.id)
        if vec is None:
            no_vec.append(item)
            continue
        scored.append((cosine_similarity(query_vec, vec), item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    hits = [item for _sim, item in scored[:k]]
    # 未命中段按相似度降序（慢速队列内仍保留次序信息），无向量条目排在其后
    misses = [item for _sim, item in scored[k:]] + no_vec
    stats["routed_hits"] = len(hits)
    stats["routed_misses"] = len(misses)
    return hits + misses, stats


def mark_semantic_duplicates(
    db: Session,
    direction,
    items: list[Item],
    *,
    model_version: str | None = None,
    threshold: float | None = None,
) -> list[Item]:
    """语义近重复标记：新条目 vs 方向内已有向量（同模型版本），余弦 ≥ 阈值 →
    duplicate_of=最早命中条目 id。只标记不删除、不动采集状态、全文照存。

    origin 池 = 方向内既有向量 + 本批中 id 更小（先入库）的条目——本批内彼此
    相似的条目对，后入库者判重指向先入库者，早入库者不反向判重。
    返回被标记判重的条目列表（调用方从打分候选中剔除）。
    """
    if not items or not model_version:
        return []
    if threshold is None:
        threshold = float(get_config(db, "semantic_dedup_threshold") or 0.92)
    vecs = _load_direction_vectors(db, direction.id, model_version)
    marked: list[Item] = []
    new_ids = {i.id for i in items}
    # origin 池起步 = 方向内既有向量（不含本批）；本批按 id 升序处理后逐个入池，
    # 后入库条目可与先入库条目判重，反之不可
    origin_pool: dict[int, np.ndarray] = {
        iid: v for iid, v in vecs.items() if iid not in new_ids
    }
    for item in sorted(items, key=lambda i: i.id):
        vec = vecs.get(item.id)
        if vec is None:
            continue
        eligible: list[int] = []
        for other_id, other_vec in origin_pool.items():
            if cosine_similarity(vec, other_vec) < threshold:
                continue
            origin = db.get(Item, other_id)
            if (origin is None or is_version_item(origin)
                    or _is_exempt_pair(item, origin)):
                # 版本条目不作 origin：页面快照不是独立事件源（含单方版本对，
                # 不能只靠取最小 id 兜底——版本条目 id 更小时会误指）
                continue
            eligible.append(other_id)
        if eligible:
            # origin 取最早入库条目（id 最小者），与 URL 指纹判重的指向语义一致
            item.duplicate_of = min(eligible)
            marked.append(item)
        origin_pool[item.id] = vec
    if marked:
        db.commit()
        log.info("语义近重复标记：%d 条（方向 %s，阈值 %.2f）",
                 len(marked), direction.id, threshold)
    return marked
