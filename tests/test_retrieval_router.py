"""打分路由测试：命中优先、未命中慢速照打、嵌入禁用/查询失败全量慢速回退。

覆盖口径：
- 路由只改顺序不改候选集合：未命中条目仍被打分（零静默漏检），仅排在命中
  条目之后；usage_log 留有逐条 scoring 计量行作为打分证据；
- 查询向量缓存键 = (direction_id, prompt_version)：提示词升版失效重生成；
  生成失败不缓存、本轮全量慢速、下轮重试；
- 嵌入禁用（模型键置空）→ 路由整体回退全量慢速，打分零损失。
设计依据见 docs/design-index.md「AC-08.2」。
"""
import numpy as np
import pytest

import app.config as cfg
from app.models import Direction, Item, ItemVec, ScoreResult, Source, UsageLog
from app.pipeline.runner import score_round
from app.retrieval.embedder import vec_to_blob
from app.retrieval.query import ensure_direction_query_vec


def _seed_direction_with_items(db, *, n=2):
    d = Direction(name="方向", prompt="p", threshold=60)
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
    return d, items


def _vec(seed: float, dims=8) -> np.ndarray:
    """沿首轴的单位向量（weight=seed 的坐标值）。余弦比较需方向差异：
    用轴向量而非标量缩放（余弦对缩放不敏感）。"""
    v = np.zeros(dims, dtype=np.float32)
    v[0] = seed
    return v


def _axis_vec(axis: int, weight=1.0, dims=8) -> np.ndarray:
    v = np.zeros(dims, dtype=np.float32)
    v[axis] = weight
    return v


class StubLLM:
    """查询生成的 LLM 打桩：可注入失败，记录调用次数。"""

    def __init__(self, *, text="查询文本", fail=False):
        self.text = text
        self.fail = fail
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        from app.providers.base import ProviderError

        if self.fail:
            raise ProviderError("stub: LLM 不可用")
        return self.text, "stub-model"


class StubEmbed:
    """嵌入打桩：固定返回单位向量（首维 1）。"""

    def __init__(self, db):
        self.db = db
        self.calls = 0

    @property
    def model_name(self):
        return "stub-embed-model"

    def embed(self, texts, *, expected_dims=None, call_point="embed", **kw):
        self.calls += 1
        from app.providers.base import record_usage

        record_usage(self.db, provider="stub", model=self.model_name,
                     call_point=call_point, item_count=len(texts), ok=True)
        return [[1.0] + [0.0] * 7 for _ in texts]


# ---------- 路由分桶与 score_round 接线 ----------


def test_miss_item_still_scored_after_hits(db_session, monkeypatch):
    d, (hit, miss) = _seed_direction_with_items(db_session, n=2)
    d.query_vec = vec_to_blob(_vec(1.0))
    d.query_vec_version = d.prompt_version
    from app.siteconfig import set_config

    set_config(db_session, "retrieval_top_k", 1)
    db_session.add(ItemVec(item_id=hit.id, model_version=cfg.MOARK_EMBED_MODEL,
                           vec=vec_to_blob(_axis_vec(0))))
    db_session.add(ItemVec(item_id=miss.id, model_version=cfg.MOARK_EMBED_MODEL,
                           vec=vec_to_blob(_axis_vec(1))))
    db_session.commit()

    order, scored_ids = [], []

    def fake_score_item(db, item, direction):
        order.append(item.id)
        scored_ids.append(item.id)
        from app.providers.base import record_usage

        record_usage(db, provider="stub", model="m", call_point="scoring", ok=True)
        return ScoreResult(item_id=item.id, direction_id=direction.id, model="m",
                           status="OK", passed=True, relevance_score=90,
                           quality_score=90, band="high")

    monkeypatch.setattr("app.scoring.service.score_item", fake_score_item)
    summary = score_round(db_session, triggered_by="test")
    stats = summary["directions"][0]
    assert scored_ids == [hit.id, miss.id]  # 未命中仍打分，仅顺序后移
    assert stats["routed_hits"] == 1 and stats["routed_misses"] == 1
    scoring_rows = db_session.query(UsageLog).filter_by(call_point="scoring").all()
    assert len(scoring_rows) == 2  # usage_log 证明两条都有 scoring 调用


def test_embed_disabled_full_slow_path_zero_loss(db_session, monkeypatch):
    d, items = _seed_direction_with_items(db_session, n=3)
    monkeypatch.setattr(cfg, "MOARK_EMBED_MODEL", "none")

    def fake_score_item(db, item, direction):
        from app.providers.base import record_usage

        record_usage(db, provider="stub", model="m", call_point="scoring", ok=True)
        return ScoreResult(item_id=item.id, direction_id=direction.id, model="m",
                           status="OK", passed=True, relevance_score=50,
                           quality_score=50, band="mid")

    monkeypatch.setattr("app.scoring.service.score_item", fake_score_item)
    summary = score_round(db_session, triggered_by="test")
    stats = summary["directions"][0]
    assert stats["scored"] == 3  # 打分零损失
    assert stats["embed_disabled"] is True
    assert db_session.query(UsageLog).filter_by(call_point="scoring").count() == 3


def test_query_gen_failure_falls_back_all_slow(db_session, monkeypatch):
    d, items = _seed_direction_with_items(db_session, n=2)
    monkeypatch.setattr(cfg, "MOARK_EMBED_MODEL", "Qwen3-Embedding-0.6B")
    # 嵌入调用打桩（LLM 查询生成失败在先，嵌入不应被触达）
    monkeypatch.setattr(
        "app.retrieval.query.DeepSeekProvider",
        lambda db: StubLLM(fail=True),
    )

    def fake_score_item(db, item, direction):
        return ScoreResult(item_id=item.id, direction_id=direction.id, model="m",
                           status="OK", passed=True, relevance_score=50,
                           quality_score=50, band="mid")

    monkeypatch.setattr("app.scoring.service.score_item", fake_score_item)
    summary = score_round(db_session, triggered_by="test")
    stats = summary["directions"][0]
    assert stats["scored"] == 2
    assert stats.get("embed_disabled") is True or stats.get("embed_fallback") is True


# ---------- 方向查询向量：版本缓存与失效 ----------


def test_query_vec_cached_until_prompt_version_bump(db_session):
    d, _ = _seed_direction_with_items(db_session, n=1)
    llm, emb = StubLLM(), StubEmbed(db_session)
    assert ensure_direction_query_vec(db_session, d, llm=llm, embed_provider=emb) is True
    assert llm.calls == 1 and emb.calls == 1
    assert d.query_vec_version == d.prompt_version
    # 同版本再次调用：缓存命中零调用
    assert ensure_direction_query_vec(db_session, d, llm=llm, embed_provider=emb) is True
    assert llm.calls == 1 and emb.calls == 1
    # 提示词升版：缓存失效重生成
    d.prompt_version = int(d.prompt_version) + 1
    db_session.commit()
    assert ensure_direction_query_vec(db_session, d, llm=llm, embed_provider=emb) is True
    assert llm.calls == 2 and emb.calls == 2
    assert d.query_vec_version == d.prompt_version


def test_query_gen_failure_not_cached_retry_next_round(db_session):
    d, _ = _seed_direction_with_items(db_session, n=1)
    llm, emb = StubLLM(fail=True), StubEmbed(db_session)
    assert ensure_direction_query_vec(db_session, d, llm=llm, embed_provider=emb) is False
    assert d.query_vec is None and d.query_vec_version is None
    # 下轮 LLM 恢复：重试成功
    llm2 = StubLLM()
    assert ensure_direction_query_vec(db_session, d, llm=llm2, embed_provider=emb) is True
    assert llm2.calls == 1


def test_query_gen_disabled_embed_returns_false(db_session, monkeypatch):
    d, _ = _seed_direction_with_items(db_session, n=1)
    monkeypatch.setattr(cfg, "MOARK_EMBED_MODEL", "none")
    assert ensure_direction_query_vec(db_session, d, llm=StubLLM(),
                                      embed_provider=StubEmbed(db_session)) is False


# ---------- 纯逻辑：分桶排序 ----------


def test_partition_items_pure_ordering_no_candidate_change(db_session):
    from app.retrieval.router import partition_items

    d, items = _seed_direction_with_items(db_session, n=3)
    low, high, novec = items
    db_session.add(ItemVec(item_id=high.id, model_version="m",
                           vec=vec_to_blob(_axis_vec(0))))
    db_session.add(ItemVec(item_id=low.id, model_version="m",
                           vec=vec_to_blob(_axis_vec(0, 0.5) + _axis_vec(1))))
    db_session.commit()
    ordered, stats = partition_items(db_session, d, list(items), query_vec=_axis_vec(0),
                                     model_version="m", top_k=1)
    assert [i.id for i in ordered] == [high.id, low.id, novec.id]  # 命中在前、未命中其后
    assert stats["routed_hits"] == 1 and stats["routed_misses"] == 2
    assert {i.id for i in ordered} == {i.id for i in items}  # 候选集合不变
    ordered_all_miss, stats2 = partition_items(db_session, d, list(items),
                                               query_vec=None, model_version="m")
    assert stats2["embed_disabled"] is True
    assert len(ordered_all_miss) == 3
