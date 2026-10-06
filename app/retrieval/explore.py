"""探索层选样：质量地板 × 距离分位 × MMR 多样性（纯函数，默认关）。

候选 = 方向内已打分但未过方向阈值的条目中质量分达地板、且与方向查询相似度
位于最低分位者；分位参照 = 该方向全部已嵌入已打分条目的相似度分布。
MMR 迭代选取：在候选中优先选"与方向最不相似且与已选条目最不相似"者，防止
探索条目彼此同质。参数全部可配（site_config 全局 + 方向级覆盖），默认关。
设计依据见 docs/design-index.md「AC-08.4」「AC-14.3」。
"""
from __future__ import annotations

import logging

import numpy as np

from .embedder import cosine_similarity

log = logging.getLogger("newswright.retrieval")

# MMR 权重：探索语义下"离方向更远"主导（λ<0.5），多样性占次要权重
MMR_LAMBDA = 0.3


def explore_params(db, direction=None, *, get_config) -> dict:
    """合成探索层生效参数：方向级 explore_config 逐键覆盖 site_config 全局值。

    返回 {enabled, floor, percentile, quota}；enabled = 方向级显式值优先，
    否则取全局开关。
    """
    enabled = bool(get_config(db, "explore_enabled"))
    params = {
        "enabled": enabled,
        "floor": int(get_config(db, "explore_quality_floor") or 50),
        "percentile": int(get_config(db, "explore_distance_percentile") or 5),
        "quota": int(get_config(db, "explore_quota_per_page") or 3),
    }
    cfg = (getattr(direction, "explore_config", None) or {}) if direction is not None else {}
    if "enabled" in cfg:
        params["enabled"] = bool(cfg["enabled"])
    for key in ("floor", "percentile", "quota"):
        if key in cfg and cfg[key] is not None:
            params[key] = int(cfg[key])
    return params


def explore_pick(
    scored_items: list[dict],
    query_vec: np.ndarray | None,
    *,
    floor: int,
    percentile: int,
    quota: int,
) -> list[dict]:
    """探索选样纯函数。scored_items 元素形态：
    {id, quality, relevance, passed, vec(ndarray|None)}。

    返回被选中的条目列表（≤quota，保持选取顺序）：质量 ≥ floor、未过方向阈值
    （passed=False，阈值判定由打分侧落库）、相似度 ∈ 最低 percentile 分位
    （参照=全部传入条目的相似度分布）的候选中做 MMR 选取。query_vec 缺失或
    候选不足时返回空列表。
    """
    if query_vec is None or quota <= 0 or not scored_items:
        return []
    sims: dict[int, float] = {}
    for it in scored_items:
        vec = it.get("vec")
        sims[it["id"]] = cosine_similarity(query_vec, vec) if vec is not None else None
    known = [s for s in sims.values() if s is not None]
    if not known:
        return []
    cut = float(np.percentile(np.asarray(known, dtype=np.float64), percentile))
    candidates = [
        it for it in scored_items
        if not it.get("passed", True)
        and (it.get("quality") or 0) >= floor
        and sims.get(it["id"]) is not None
        and sims[it["id"]] <= cut
    ]
    candidates.sort(key=lambda it: sims[it["id"]])
    picked: list[dict] = []
    while candidates and len(picked) < quota:
        best, best_score = None, None
        for it in candidates:
            sim_q = sims[it["id"]]
            sim_sel = max(
                (cosine_similarity(it["vec"], p["vec"]) for p in picked if p.get("vec") is not None),
                default=0.0,
            )
            score = -MMR_LAMBDA * sim_q - (1 - MMR_LAMBDA) * sim_sel
            if best_score is None or score > best_score:
                best, best_score = it, score
        picked.append(best)
        candidates.remove(best)
    return picked
