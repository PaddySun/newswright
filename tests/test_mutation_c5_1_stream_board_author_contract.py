"""B 流探索注入、未评分附带、热榜热度与作者全量契约测试
（C5-1 变异分诊批：app/api/routes 面）。

覆盖口径（设计依据见 docs/design-index.md「AC-14.3」「AC-21.1」与技术书
§3 /api/stream/b 条目 schema、/api/hot/topics heat 键序、/api/authors/{id}
单条全量）：
- 探索注入条目携带完整字段集（id/title/url/published_at/relevance/quality/
  band/reason/source_id/source_name/domain/flag——§3 YAML 条目 schema），
  domain 取 URL 解析 hostname；方向级 mmr_lambda 覆盖值透传给选样器；
- 未评分附带条目与主条目同构（unscored[] 同构附 note）；
- heat 按 extra.info→hover 键序取第一个可数值化值（info 不可解析时 hover 兜底）；
- 作者单条全量：readable_directions 坏行后有效行仍富化（配置完整性优先）、
  memory_counts 按 module 分组计数。
"""
from datetime import datetime, timedelta, timezone

import numpy as np

import app.config as cfg
from app.api.routes import (
    _author_full_out,
    _hot_heat,
    _inject_explore_items,
    _unscored_entries,
)
from app.models import (
    Author,
    Direction,
    Item,
    ItemVec,
    MemoryEntry,
    PipelineTask,
    ScoreResult,
    Source,
)
from app.retrieval.embedder import vec_to_blob
from app.siteconfig import set_config


def _axis(axis: int, dims=16):
    v = np.zeros(dims, dtype=np.float32)
    v[axis] = 1.0
    return v


def test_explore_injected_items_carry_full_schema(db_session):
    """探索条目字段集：注入条目携带 §3 /api/stream/b 条目 schema 全字段
    （含 domain=URL 解析 hostname 与 flag=explore——AC-14.3 探索标记）。"""
    db = db_session
    d = Direction(name="探索契约方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://example.com/explore-src")
    db.add(src)
    db.commit()
    it = Item(source_id=src.id, guid="explore-item",
              url="https://example.com/deep/page", title="探索条目标题",
              content_text="正文", fetch_status="FETCHED",
              direction_id=d.id, sanitize_status="PASSED")
    db.add(it)
    db.flush()
    db.add(ScoreResult(item_id=it.id, direction_id=d.id, quality_score=72,
                       relevance_score=30, band="low", reason="r",
                       prompt_version=1, model="m", passed=False, status="OK"))
    db.add(ItemVec(item_id=it.id, model_version=cfg.MOARK_EMBED_MODEL,
                   vec=vec_to_blob(_axis(12))))
    set_config(db, "explore_enabled", True)
    d.query_vec = vec_to_blob(_axis(0))
    d.query_vec_version = d.prompt_version
    db.commit()

    out_items = []
    meta = _inject_explore_items(db, d.id, out_items, 50)
    assert meta["inserted"] == 1
    entry = out_items[0]
    expected = {"id", "title", "url", "published_at", "relevance", "quality",
                "band", "reason", "source_id", "source_name", "domain", "flag"}
    missing = expected - set(entry)
    assert not missing, f"探索条目缺字段: {missing}"
    assert entry["flag"] == "explore"
    assert entry["domain"] == "example.com"  # URL 解析 hostname 口径


def test_explore_passes_direction_level_mmr_lambda(db_session, monkeypatch):
    """方向级 mmr_lambda 覆盖值透传给选样器（探索层参数 config-only 可调
    ——管理员调试位生效，不退化为模块默认）。"""
    db = db_session
    d = Direction(name="透传方向", prompt="p", threshold=60,
                  explore_config={"mmr_lambda": 0.9})
    db.add(d)
    db.commit()
    set_config(db, "explore_enabled", True)
    d.query_vec = vec_to_blob(_axis(0))
    d.query_vec_version = d.prompt_version
    db.commit()

    captured = {}

    def fake_pick(pool, qv, **kw):
        captured.update(kw)
        return []

    monkeypatch.setattr("app.retrieval.explore.explore_pick", fake_pick)
    _inject_explore_items(db, d.id, [], 50)
    assert captured.get("mmr_lambda") == 0.9


def test_unscored_entries_carry_schema_fields(db_session):
    """未评分附带条目与主条目同构：携带标题/原文链接/标注字段与
    「暂未评分」注记（§3 unscored[] 同构附 note）。"""
    db = db_session
    d = Direction(name="同构方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://example.com/unscored")
    db.add(src)
    db.commit()
    it = Item(source_id=src.id, guid="unscored-item",
              url="https://example.com/u/1", title="未评分条目标题",
              content_text="正文", fetch_status="FETCHED",
              direction_id=d.id, sanitize_status="PASSED")
    db.add(it)
    db.add(PipelineTask(kind="score", status="FAILED", payload={},
                        updated_at=datetime.now(timezone.utc)
                        - timedelta(hours=1)))
    db.commit()
    rows = _unscored_entries(db, d.id)
    assert len(rows) == 1
    entry = rows[0]
    for key in ("id", "title", "url", "flag", "note", "source_name",
                "domain", "published_at"):
        assert key in entry, f"未评分条目缺字段: {key}"
    assert entry["flag"] == "unscored"
    assert entry["note"] == "暂未评分"


def test_hot_heat_skips_bool_and_falls_back_to_hover():
    """heat 键序兜底：info 键为布尔值（bool 排除，不误作 1/0）时取 hover 键
    （§3 heat 按 extra.info→hover 键序数值化——逐键尝试不截断）。"""
    assert _hot_heat({"info": True, "hover": "12345"}) == 12345.0


def test_author_full_out_keeps_valid_rows_after_malformed_direction(db_session):
    """readable_directions 富化配置完整性优先：坏行（非 dict 形态）跳过
    后，后续有效行仍富化出方向名（§3 行失 id 保条目——坏行不得截断清单）。"""
    db = db_session
    d = Direction(name="有效方向", prompt="p")
    db.add(d)
    db.commit()
    a = Author(name="坏行作者", model="m",
               readable_directions=["not-a-dict-row",
                                    {"direction_id": d.id, "threshold": 50}])
    db.add(a)
    db.commit()
    out = _author_full_out(db, a)
    rds = out["readable_directions"]
    assert len(rds) == 1  # 非 dict 坏行跳过
    assert rds[0]["direction_name"] == "有效方向"  # 坏行后的有效行仍富化


def test_author_full_out_counts_memory_entries_by_module(db_session):
    """memory_counts 按 module 分组计数（§3 单条全量 memory_counts{module:n}
    ——计数账本如实）。"""
    db = db_session
    a = Author(name="计数作者", model="m")
    db.add(a)
    db.flush()
    for module in ("feedback", "feedback", "style"):
        db.add(MemoryEntry(author_id=a.id, module=module, content="c",
                           source_event="feedback"))
    db.commit()
    out = _author_full_out(db, a)
    assert out["memory_counts"] == {"feedback": 2, "style": 1}
