"""阅读集装配契约测试：状态/条目域过滤、阈值准入边界、域名上限零与负值语义、
rank 路径 K 截断与装配循环。

覆盖口径（设计依据见 docs/design-index.md「US-11」「DT-2」「AC-11.1」）：
- 候选域 = ScoreResult.status=="OK" 且 passed 且 Item.fetch_status=="FETCHED"
  （writer._assemble_with_domain_cap 查询过滤链——FAILED/ARCHIVED 行不进阅读集）；
- 准入边界 = relevance ≥ 方向阈值（模块 docstring 钉 ≥，恰等于阈值可入）；
- 域名硬约束 = site_config.reading_set_domain_cap，≤0 = 不设限（docstring 钉）；
- rank 路径 = 预排序池 → 低分排除 → top-K 截断；按方向分组装配遇未知方向与
  排序明细缺失时跳过该候选继续收集（多方向与限额截断场景不丢合格候选）。

网络纪律：FakeRankProvider 脚本化输出，不真联网；生产代码零改动。
"""
from datetime import datetime, timezone

import pytest

import app.rerank.registry as rank_registry
from app.authors.writer import _assemble_with_domain_cap, assemble_ranked_reading_set
from app.models import Author, Direction, Item, ScoreResult, Source
from app.rerank.base import RankCandidate, RankProvider, RankedResult
from app.siteconfig import set_config


def _mk_item(db, src, guid, url, rel, *, status="OK", passed=True,
             fetch_status="FETCHED", direction_id=None):
    it = Item(source_id=src.id, guid=guid, url=url, title=f"标题{guid}",
              content_text="正文" * 100, published_at=datetime.now(timezone.utc),
              fetch_status=fetch_status, direction_id=direction_id or src.direction_id)
    db.add(it)
    db.flush()
    db.add(ScoreResult(item_id=it.id, direction_id=direction_id or src.direction_id,
                       quality_score=rel, relevance_score=rel, band="high",
                       reason="r", prompt_version=1, model="m",
                       passed=passed, status=status))
    db.commit()
    return it


@pytest.fixture()
def assembly_env(db_session):
    """方向 A（阈值 90）+ 方向 B（阈值 50）双方向可读作者。"""
    db = db_session
    da = Direction(name="高阈值方向", prompt="p", threshold=90)
    db.add(da)
    db.commit()
    db.add(Direction(id=2, name="低阈值方向", prompt="p", threshold=50))
    db.commit()
    sa = Source(direction_id=da.id, url="https://a.example/feed")
    db.add(sa)
    db.commit()
    sb = Source(direction_id=2, url="https://b.example/feed")
    db.add(sb)
    db.commit()
    author = Author(name="装配契约作者", model="m", rank_provider="none",
                    readable_directions=[{"direction_id": da.id, "threshold": 90},
                                         {"direction_id": 2, "threshold": 50}])
    db.add(author)
    db.commit()
    return db, author, da, sa, sb


def test_non_ok_score_rows_excluded(assembly_env):
    """非 OK 打分行不进阅读集（状态域过滤）。"""
    db, author, d, sa, sb = assembly_env
    good = _mk_item(db, sa, "ok1", "https://a.example/ok1", 95)
    bad = _mk_item(db, sa, "bad1", "https://a.example/bad1", 99,
                   status="FAILED", passed=True)
    pairs, _ = _assemble_with_domain_cap(db, author)
    ids = [i.id for i, _ in pairs]
    assert good.id in ids and bad.id not in ids


def test_non_fetched_items_excluded(assembly_env):
    """ARCHIVED（首导窗口外重打分）条目不进阅读集（条目域过滤）。"""
    db, author, d, sa, sb = assembly_env
    good = _mk_item(db, sa, "f1", "https://a.example/f1", 95)
    archived = _mk_item(db, sa, "arch1", "https://a.example/arch1", 99,
                        fetch_status="ARCHIVED")
    pairs, _ = _assemble_with_domain_cap(db, author)
    ids = [i.id for i, _ in pairs]
    assert good.id in ids and archived.id not in ids


def test_threshold_boundary_is_inclusive(assembly_env):
    """恰等于方向阈值的条目可入阅读集（准入边界 ≥ 语义）。"""
    db, author, d, sa, sb = assembly_env
    at_threshold = _mk_item(db, sa, "edge1", "https://a.example/edge1", 90)
    below = _mk_item(db, sa, "under1", "https://a.example/under1", 89)
    pairs, _ = _assemble_with_domain_cap(db, author)
    ids = [i.id for i, _ in pairs]
    assert at_threshold.id in ids and below.id not in ids


def test_multi_direction_low_relevance_does_not_stop_collection(assembly_env):
    """高阈值方向低分条目被跳过后，低阈值方向的合格条目仍被收集
    （阈值过滤是跳过不是终止）。"""
    db, author, da, sa, sb = assembly_env
    b_high = _mk_item(db, sb, "b1", "https://b.example/b1", 80)   # B 阈值 50，收集
    a_low = _mk_item(db, sa, "a_low", "https://a.example/a_low", 70)  # A 阈值 90，跳过
    b_mid = _mk_item(db, sb, "b2", "https://b.example/b2", 60)    # B 合格，必须仍在
    pairs, _ = _assemble_with_domain_cap(db, author)
    ids = [i.id for i, _ in pairs]
    assert b_high.id in ids and b_mid.id in ids and a_low.id not in ids


def test_domain_cap_zero_disables_limit(assembly_env):
    """cap=0 = 不设限（docstring 契约）：同域名超额条目全部可入。"""
    db, author, da, sa, sb = assembly_env
    set_config(db, "reading_set_domain_cap", 0)
    for i in range(5):
        _mk_item(db, sa, f"cap{i}", f"https://a.example/cap{i}", 95 - i)
    pairs, _ = _assemble_with_domain_cap(db, author)
    assert len(pairs) == 5


def test_domain_cap_negative_disables_limit(assembly_env):
    """cap 负值 = 不设限（≤0 语义覆盖负数）：负配置不得清空阅读集。"""
    db, author, da, sa, sb = assembly_env
    set_config(db, "reading_set_domain_cap", -1)
    for i in range(3):
        _mk_item(db, sa, f"neg{i}", f"https://a.example/neg{i}", 95 - i)
    pairs, _ = _assemble_with_domain_cap(db, author)
    assert len(pairs) == 3


class FullRankProvider(RankProvider):
    """全部候选返回递减明细的排序桩（top-K 截断的被测面）。"""

    name = "full_rank"

    def _rank(self, criteria, candidates):
        return [RankedResult(id=c.id, score=float(100 - idx * 10), band="high",
                             confidence=None, provider=self.name)
                for idx, c in enumerate(candidates)]


def test_rank_respects_explicit_k(assembly_env, monkeypatch):
    """rank 路径显式 k 截断生效：排序后阅读集恰 k 条。"""
    db, author, da, sa, sb = assembly_env
    rank_registry.register("full_rank", FullRankProvider)
    author.rank_provider = "full_rank"
    db.commit()
    for i in range(4):
        _mk_item(db, sa, f"rk{i}", f"https://a.example/rk{i}", 95 - i)
    pairs, meta = assemble_ranked_reading_set(db, author, k=2)
    assert len(pairs) == 2
    assert meta.get("fallback") is None


def test_rank_unknown_direction_does_not_stop_grouping(db_session, monkeypatch):
    """rank 按方向分组装配：配置指向已删除方向（无 Direction 行）时跳过该组，
    其他方向的合格候选照常收集（跳过非终止）。"""
    db = db_session
    d1 = Direction(name="存活方向", prompt="p", threshold=60)
    db.add(d1)
    db.commit()
    s1 = Source(direction_id=d1.id, url="https://alive.example/feed")
    db.add(s1)
    db.commit()
    # 孤儿方向 999：readable_directions 引用但 Direction 行不存在（FK 不启用域）
    s9 = Source(direction_id=999, url="https://ghost.example/feed")
    db.add(s9)
    db.commit()
    author = Author(name="孤儿方向作者", model="m", rank_provider="full_rank2",
                    readable_directions=[{"direction_id": 999, "threshold": 60},
                                         {"direction_id": d1.id, "threshold": 60}])
    db.add(author)
    db.commit()
    rank_registry.register("full_rank2", FullRankProvider)
    # 孤儿方向条目 relevance 更高（分组顺序在前）
    ghost = _mk_item(db, s9, "ghost1", "https://ghost.example/g1", 99,
                     direction_id=999)
    alive = _mk_item(db, s1, "alive1", "https://alive.example/a1", 95)
    pairs, meta = assemble_ranked_reading_set(db, author, k=5)
    ids = [i.id for i, _ in pairs]
    assert alive.id in ids
    assert meta.get("fallback") is None


class MissingDirectionRankProvider(RankProvider):
    """排序成功但跳过部分候选明细的排序桩（服务端限额截断形态）：
    明细缺失位在组中间——其后的候选仍带明细，跳过与终止才可区分。"""

    name = "missing_detail_rank"

    def _rank(self, criteria, candidates):
        out = []
        for idx, c in enumerate(candidates):
            if idx == 1:
                continue  # 第二候选明细缺失（限额截断形态）
            out.append(RankedResult(id=c.id, score=float(100 - idx * 10),
                                    band="high", confidence=None,
                                    provider=self.name))
        return out


def test_rank_partial_details_keep_scored_candidates(assembly_env, monkeypatch):
    """排序明细缺失的候选被跳过，其后的候选保留（跳过非终止）。"""
    db, author, da, sa, sb = assembly_env
    rank_registry.register("detail_rank", MissingDirectionRankProvider)
    author.rank_provider = "detail_rank"
    db.commit()
    i1 = _mk_item(db, sa, "md1", "https://a.example/md1", 95)
    i2 = _mk_item(db, sa, "md2", "https://a.example/md2", 94)
    i3 = _mk_item(db, sa, "md3", "https://a.example/md3", 93)
    pairs, meta = assemble_ranked_reading_set(db, author, k=5)
    ids = [i.id for i, _ in pairs]
    assert i1.id in ids and i3.id in ids and i2.id not in ids
    assert meta.get("fallback") is None
