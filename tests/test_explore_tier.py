"""探索层测试：选样纯函数（质量地板×距离分位×MMR）与 B 流注入契约。

覆盖口径：
- 质量 72（≥地板 50）且相似度处于最低分位的未过阈值条目 → 出现在 B 流尾部、
  带 flag="explore" 与真实低相关分；每页探索条目 ≤ 配额（默认 3）；
- 总开关关闭（site_config 全局或方向级覆盖为关）→ B 流零探索条目；
- 方向级 explore_config.enabled 覆盖全局开关；
- MMR：同质候选簇中选取不互相重复。
设计依据见 docs/design-index.md「AC-08.4」「AC-14.1」「AC-14.3」。
"""
import numpy as np

import app.config as cfg
from app.models import Direction, Item, ItemVec, ScoreResult, Source
from app.retrieval.embedder import vec_to_blob
from app.retrieval.explore import explore_pick
from app.siteconfig import set_config


def _axis(axis: int, dims=16) -> np.ndarray:
    v = np.zeros(dims, dtype=np.float32)
    v[axis] = 1.0
    return v


def _seed_scenario(db):
    """方向 + 10 条过阈值常规条目（与查询同向）+ 4 条未过阈值候选（与查询正交，
    质量 72）。返回 (direction, regular_items, candidates)。"""
    d = Direction(name="探索方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://example.com/rss")
    db.add(src)
    db.commit()
    model = cfg.MOARK_EMBED_MODEL
    d.query_vec = vec_to_blob(_axis(0))
    d.query_vec_version = d.prompt_version
    regular, candidates = [], []
    for i in range(10):
        item = Item(source_id=src.id, guid=f"r{i}", url=f"https://example.com/r{i}",
                    title=f"常规{i}", content_text="正文", fetch_status="FETCHED",
                    direction_id=d.id, sanitize_status="PASSED")
        db.add(item)
        db.flush()
        db.add(ScoreResult(item_id=item.id, direction_id=d.id, quality_score=90,
                           relevance_score=95, band="high", reason="r",
                           prompt_version=d.prompt_version, model="m",
                           passed=True, status="OK"))
        db.add(ItemVec(item_id=item.id, model_version=model, vec=vec_to_blob(_axis(0))))
        regular.append(item)
    for i, axis in enumerate((12, 13, 14, 15)):
        item = Item(source_id=src.id, guid=f"c{i}", url=f"https://example.com/c{i}",
                    title=f"候选{i}", content_text="正文", fetch_status="FETCHED",
                    direction_id=d.id, sanitize_status="PASSED")
        db.add(item)
        db.flush()
        db.add(ScoreResult(item_id=item.id, direction_id=d.id, quality_score=72,
                           relevance_score=30, band="low", reason="r",
                           prompt_version=d.prompt_version, model="m",
                           passed=False, status="OK"))
        db.add(ItemVec(item_id=item.id, model_version=model, vec=vec_to_blob(_axis(axis))))
        candidates.append(item)
    db.commit()
    return d, regular, candidates


def _b_stream(client, direction_id, **params):
    q = {"direction_id": direction_id, "sort": "score", **params}
    r = client.get("/stream/b", params=q)
    assert r.status_code == 200, r.text
    return r.json()


def test_stream_b_explore_disabled_by_default_zero_flag(auth_client, db_session):
    d, _, _ = _seed_scenario(db_session)
    body = _b_stream(auth_client, d.id)
    assert body["explore"]["enabled"] is False
    assert all("flag" not in i for i in body["items"])


def test_stream_b_explore_injection_flag_real_score_quota(auth_client, db_session):
    d, _, candidates = _seed_scenario(db_session)
    set_config(db_session, "explore_enabled", True)
    body = _b_stream(auth_client, d.id)
    flags = [i for i in body["items"] if i.get("flag") == "explore"]
    assert body["explore"]["enabled"] is True
    assert len(flags) == 3  # 每页 ≤ 配额 3（候选 4 条）
    assert body["explore"]["inserted"] == 3
    for it in flags:
        assert it["relevance"] == 30  # 真实低分不伪装
        assert it["quality"] == 72
    assert all(i["relevance"] >= 60 for i in body["items"] if "flag" not in i)


def test_direction_level_switch_overrides_global(auth_client, db_session):
    d, _, _ = _seed_scenario(db_session)
    # 全局关 + 方向级开 → 注入
    d.explore_config = {"enabled": True}
    db_session.commit()
    body = _b_stream(auth_client, d.id)
    assert body["explore"]["enabled"] is True
    assert body["explore"]["inserted"] > 0
    # 全局开 + 方向级关 → 零注入
    set_config(db_session, "explore_enabled", True)
    d.explore_config = {"enabled": False}
    db_session.commit()
    body = _b_stream(auth_client, d.id)
    assert body["explore"]["enabled"] is False
    assert body["explore"]["inserted"] == 0
    assert all("flag" not in i for i in body["items"])


# ---------- 纯函数 ----------


def test_explore_pick_quality_floor_filters():
    d = np.zeros(8, dtype=np.float32)
    d[0] = 1.0

    def cand(i, quality, axis):
        return {"id": i, "quality": quality, "relevance": 30, "passed": False,
                "vec": _axis(axis, dims=8)}

    items = [cand(1, 72, 5), cand(2, 49, 6), cand(3, 72, 7)]
    picked = explore_pick(items, d, floor=50, percentile=5, quota=3)
    assert [p["id"] for p in picked] == [1, 3]  # 质量 49 被地板挡住


def test_explore_pick_mmr_avoids_homogeneous_picks():
    d = _axis(0, dims=8)

    def cand(i, axis):
        return {"id": i, "quality": 72, "relevance": 30, "passed": False,
                "vec": _axis(axis, dims=8)}

    # 两簇候选：A 簇（轴5）两条、B 簇（轴6）两条——MMR 应跨簇各取其一
    items = [cand(1, 5), cand(2, 5), cand(3, 6), cand(4, 6)]
    picked = explore_pick(items, d, floor=50, percentile=5, quota=2)
    axes = {p["vec"].argmax() for p in picked}
    assert len(picked) == 2
    assert axes == {5, 6}


def test_explore_pick_passed_items_never_picked():
    d = _axis(0, dims=8)
    items = [{"id": 1, "quality": 90, "relevance": 95, "passed": True,
              "vec": _axis(0, dims=8)}]
    assert explore_pick(items, d, floor=50, percentile=5, quota=3) == []
