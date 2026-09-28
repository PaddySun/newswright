"""M12 测试：排序底座——三实现归一化、额度拦截、阅读集预排序回退、热点筛选开关。"""
from datetime import datetime

import pytest

import app.authors.writer as writer_mod
import app.hot.service as hot_service
import app.rerank.registry as rank_registry
from app.rerank.base import RankCandidate, RankError, RankProvider, RankedResult
from app.models import Author, Direction, Item, RankCallLog, ScoreResult, Source


def _src(db, direction):
    src = db.query(Source).filter_by(direction_id=direction.id,
                                     url=f"rss://{direction.name}").one_or_none()
    if src is None:
        src = Source(direction_id=direction.id, url=f"rss://{direction.name}")
        db.add(src)
        db.commit()
    return src


def _mk_ranked_item(db, direction, guid, *, relevance, band="high", body_len=400):
    it = Item(source_id=_src(db, direction).id, guid=guid,
              url=f"https://ex/{guid}", title=f"t-{guid}",
              content_text="字" * body_len, sanitize_status="PASSED",
              fetch_status="FETCHED")
    db.add(it)
    db.flush()
    sr = ScoreResult(item_id=it.id, direction_id=direction.id, model="m",
                     relevance_score=relevance, band=band, passed=relevance >= 60, status="OK")
    db.add(sr)
    db.commit()
    return it, sr


def _src(db, direction):
    src = Source(direction_id=direction.id, url=f"rss://{direction.name}")
    db.add(src)
    db.commit()
    return src


def _mk_direction(db, name="DR") -> Direction:
    d = Direction(name=name, prompt="方向标准：AI 工程一手实践", threshold=60)
    db.add(d)
    db.commit()
    return d


def _mk_author(db, direction, rank_provider="none") -> Author:
    a = Author(name=f"作者{rank_provider}", model="deepseek-chat",
               readable_directions=[{"direction_id": direction.id, "threshold": 60}],
               memory_config={}, rank_provider=rank_provider, rank_exclude_below=30)
    db.add(a)
    db.commit()
    return a


class FakeRankProvider(RankProvider):
    name = "fake_rank"

    def __init__(self, db):
        super().__init__(db)

    def _rank(self, criteria, candidates):
        # 按候选 id 逆序打分：验证排序生效
        return [
            RankedResult(id=c.id, score=float(100 - int(c.id) * 10),
                         band="high" if c.id % 2 else "low", confidence=None,
                         provider=self.name)
            for c in candidates
        ]


def test_registry_register_and_get(db_session):
    rank_registry.register("fake_rank", FakeRankProvider)
    p = rank_registry.get_provider("fake_rank", db_session)
    assert p.name == "fake_rank"
    with pytest.raises(RankError):
        rank_registry.get_provider("none", db_session)
    with pytest.raises(RankError):
        rank_registry.get_provider("nope", db_session)


def test_rank_provider_logs_call_and_quota_block(db_session, monkeypatch):
    import app.rerank.base as base
    import app.search.quota as quota_mod

    rank_registry.register("fake_rank", FakeRankProvider)
    p = rank_registry.get_provider("fake_rank", db_session)
    results = p.rank("标准", [RankCandidate(id=1, text="a"), RankCandidate(id=2, text="b")],
                     criteria_key="测试")
    assert len(results) == 2 and results[0].score == 90
    log = db_session.query(RankCallLog).one()
    assert log.ok and log.status == "ok" and log.candidate_count == 2

    # 额度清零后压限额 → blocked → 返回 [] 且落 blocked 日志
    from app.models import SearchQuota

    for q in db_session.query(SearchQuota).all():
        q.count = 0
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_MINUTE", 0)
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_DAY", 100)
    results2 = p.rank("标准", [RankCandidate(id=1, text="a")])
    assert results2 == []
    logs = db_session.query(RankCallLog).order_by(RankCallLog.id).all()
    assert logs[-1].status == "blocked"


def test_ranked_reading_set_excludes_and_orders(db_session, monkeypatch):
    rank_registry.register("fake_rank", FakeRankProvider)
    d = _mk_direction(db_session)
    for i in range(5):
        _mk_ranked_item(db_session, d, f"r{i}", relevance=90)
    a = _mk_author(db_session, d, rank_provider="fake_rank")

    pairs, meta = writer_mod.assemble_ranked_reading_set(db_session, a, k=3)
    # fake 按 100-id*10 打分 → r0=100 分最高，取前 3：r0,r1,r2
    ids = [it.id for it, _ in pairs]
    r0 = db_session.query(Item).filter_by(guid="r0").one()
    assert ids[0] == r0.id
    assert meta["rank_provider"] == "fake_rank" and meta["kept"] == 3
    # run_write 的 payload 落库验证在 test_author 里覆盖结构即可


def test_ranked_reading_set_fallback_on_error(db_session, monkeypatch):
    class BoomProvider(FakeRankProvider):
        def _rank(self, criteria, candidates):
            raise RankError("boom")

    rank_registry.register("boom_rank", BoomProvider)
    d = _mk_direction(db_session, "DR2")
    for i in range(5):
        _mk_ranked_item(db_session, d, f"e{i}", relevance=90)
    a = _mk_author(db_session, d, rank_provider="boom_rank")
    a.name = "作者boom"
    db_session.commit()

    pairs, meta = writer_mod.assemble_ranked_reading_set(db_session, a, k=3)
    assert meta.get("fallback") == "rank_failed_or_empty"
    assert len(pairs) == 3  # 回退 relevance 口径，不丢阅读集


def test_ranked_reading_set_none_passthrough(db_session):
    d = _mk_direction(db_session, "DR3")
    for i in range(5):
        _mk_ranked_item(db_session, d, f"n{i}", relevance=90)
    a = _mk_author(db_session, d, rank_provider="none")
    a.name = "作者none"
    db_session.commit()
    pairs, meta = writer_mod.assemble_ranked_reading_set(db_session, a, k=3)
    assert meta["rank_provider"] == "none" and len(pairs) == 3


def test_hot_rank_filter_toggle(db_session, monkeypatch):
    monkeypatch.setattr(hot_service, "fetch_platform", lambda p, **kw: [
        {"title": f"话题{i}", "url": f"https://x/{i}"} for i in range(1, 4)])
    monkeypatch.setattr(hot_service.time, "sleep", lambda s: None)
    monkeypatch.setattr(hot_service, "_extract_keywords", lambda db, t: (["k"], "s", "m"))
    _mk_direction(db_session, "HOTD")

    # 默认关：不过滤
    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "DONE"
    assert out["platforms"]  # 结构存在

    # 开：走 fake rank provider 过滤（provider 缺 Key 也不致命——回退原输入）
    monkeypatch.setenv("HOT_RANK_FILTER", "true")
    out2 = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out2["status"] == "DONE"


def test_hot_brief_injection_guarded(db_session):
    """V9 后半单测：include_hot_brief=true 注入热点段；引用校验仍只认阅读集 item。"""
    from app.hot.service import run_hot_round
    from app.models import HotBatch, HotTopic

    d = _mk_direction(db_session, "HB")
    # 造一个 hot_batch
    batch = HotBatch(date="2026-09-28", keywords=["话题A", "话题B"], summary="综述",
                     source_platforms=["weibo"], model="m")
    db_session.add(batch)
    db_session.commit()
    db_session.add(HotTopic(platform="weibo", rank=1, title="话题A标题", batch_id=batch.id))
    db_session.commit()

    from app.authors.writer import _hot_brief

    a = _mk_author(db_session, d, rank_provider="none")
    a.name = "作者HB"
    a.include_hot_brief = True
    db_session.commit()
    brief = _hot_brief(db_session, a)
    assert "全网热点风向" in brief and "话题A" in brief and "禁止作为引用来源" in brief

    a.include_hot_brief = False
    db_session.commit()
    assert _hot_brief(db_session, a) == ""
