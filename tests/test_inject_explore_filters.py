"""B 流探索注入过滤域测试：候选池的方向/状态/版本过滤与注入去重续注。

覆盖口径（拍板⑤ 探索层 + AC-21.2 降级第一档，设计依据见
docs/design-index.md「AC-14.3」）：
- 探索候选池 = 本方向 OK 打分 + 当前嵌入模型版本向量 + FETCHED + 未判重
  条目（跨方向条目、失败打分行、旧版本向量、非 FETCHED、判重条目都不进池）；
- 已在常规结果里的 pick 跳过后继续注入后续 pick（配额不被单条去重截断）；
- 嵌入禁用时零注入（探索层依赖嵌入——降级秩序承载域）。
"""
import numpy as np

import app.config as cfg
from app.api.routes import _inject_explore_items
from app.models import Direction, Item, ItemVec, ScoreResult, Source
from app.retrieval.embedder import vec_to_blob
from app.siteconfig import set_config


def _axis(axis: int, dims=16):
    v = np.zeros(dims, dtype=np.float32)
    v[axis] = 1.0
    return v


def _seed_direction(db, name):
    d = Direction(name=name, prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url=f"https://example.com/{name}")
    db.add(src)
    db.commit()
    return d, src


def _scored_item(db, src, guid, *, status="OK", passed=False, vec_axis=12,
                 model=None, fetch_status="FETCHED", dup=None):
    it = Item(source_id=src.id, guid=guid, url=f"https://example.com/{guid}",
              title=f"标题{guid}", content_text="正文", fetch_status=fetch_status,
              direction_id=src.direction_id, sanitize_status="PASSED",
              duplicate_of=dup)
    db.add(it)
    db.flush()
    db.add(ScoreResult(item_id=it.id, direction_id=src.direction_id,
                       quality_score=72, relevance_score=30, band="low",
                       reason="r", prompt_version=1, model="m", passed=passed,
                       status=status))
    if vec_axis is not None:
        db.add(ItemVec(item_id=it.id, model_version=model or cfg.MOARK_EMBED_MODEL,
                       vec=vec_to_blob(_axis(vec_axis))))
    db.commit()
    return it


def _ready(db, d):
    set_config(db, "explore_enabled", True)
    d.query_vec = vec_to_blob(_axis(0))
    d.query_vec_version = d.prompt_version
    db.commit()


def test_explore_pool_scoped_to_direction_and_clean_rows(db_session):
    """候选池五过滤：跨方向/FAILED 行/旧版本向量/非 FETCHED/判重都不注入。"""
    db = db_session
    d_a, src_a = _seed_direction(db, "过滤方向A")
    d_b, src_b = _seed_direction(db, "过滤方向B")
    _ready(db, d_a)
    keep = _scored_item(db, src_a, "keep")
    _scored_item(db, src_b, "cross")                            # 跨方向
    _scored_item(db, src_a, "failed", status="FAILED")          # 失败打分行
    _scored_item(db, src_a, "oldver", model="legacy-model")     # 旧版本向量
    _scored_item(db, src_a, "unfetched", fetch_status="ARCHIVED")
    _scored_item(db, src_a, "dup", dup=keep.id)                 # 判重
    out_items = []
    meta = _inject_explore_items(db, d_a.id, out_items, 50)
    assert meta["inserted"] == 1
    assert [i["id"] for i in out_items] == [keep.id]


def test_explore_skips_existing_but_continues(db_session, monkeypatch):
    """pick 与常规结果重叠时跳过该条、继续注入后续 pick（配额不被截断）。"""
    db = db_session
    d_a, src_a = _seed_direction(db, "续注方向")
    _ready(db, d_a)
    regular = _scored_item(db, src_a, "regular", passed=True, vec_axis=None)
    candidate = _scored_item(db, src_a, "candidate")

    def _pick_entry(item_id):
        return {"id": item_id, "title": "t", "url": "u", "relevance": 30,
                "quality": 72, "band": "low", "reason": "r", "source_id": 1}

    monkeypatch.setattr("app.retrieval.explore.explore_pick",
                        lambda pool, qv, **kw: [_pick_entry(regular.id),
                                                _pick_entry(candidate.id)])
    out_items = [{"id": regular.id}]  # 常规结果已含 regular
    meta = _inject_explore_items(db, d_a.id, out_items, 50)
    assert meta["inserted"] == 1
    assert [i["id"] for i in out_items[1:]] == [candidate.id]


def test_explore_paused_when_embed_disabled(db_session, monkeypatch):
    """嵌入禁用时零注入（探索层依赖嵌入，AC-21.2 降级承载）。"""
    db = db_session
    d_a, src_a = _seed_direction(db, "嵌入禁用方向")
    _ready(db, d_a)
    _scored_item(db, src_a, "cand")
    monkeypatch.setattr("app.retrieval.embedder.embed_enabled", lambda: False)
    out_items = []
    meta = _inject_explore_items(db, d_a.id, out_items, 50)
    assert meta["inserted"] == 0
    assert out_items == []
