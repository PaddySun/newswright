"""C1-8 分诊批次 10：外部能力家族（hot/search/rerank/embedding）幸存变异体闭合测试。

> 追溯注记：本文件原名 tests/test_mutation_c1_8.py（原批次代号见文件名），按对象重命名于 F1⑫治理批。

条款依据（技术书 v1.7 / 产品书 v1.6）：
- ADR-8 provider 统一纪律（重试 ≤2 指数退避 / 计量落账 / 报错脱敏 / 连接构造 D-A 尾斜杠、
  D-B Bearer+Content-Type / 额度闸接入位）；ADR-8 计费对账（billing_units 唯一可信源）。
- ADR-3 embedding 走 API：call_point=embed、item_count 按批落行、延迟计量、双护栏。
- AC-05.4 搜索额度闸（不发出 / search_call_log status=blocked error=SKIPPED_QUOTA / 恢复）。
- AC-05.6 热榜全量落库 / 单平台失败不中断 / 全平台失败 FAILED 不 mock / summary ≤200。
- AC-05.2/D15/P1-2 方向内 URL 指纹 DUP 落行；AC-06.1/06.2 sanitize 强制阶段与统计。
- §4.1 三账本（usage_log/search_call_log/rank_call_log）+ DT-5 payload.stats。
- EV1-EV8 实测纪律（count guards / 25 条分批 / model_version 归因）。

红线：全部 provider 打桩，零真实 API 调用（C1-7 联网事故教训）；零生产代码改动。
"""
import re
import time as _time_mod

import app.embedding.base as emb_base
from datetime import datetime, timedelta, timezone

import pytest

import app.hot.service as hot_service
import app.rerank.base as rerank_base
import app.rerank.registry as rank_registry
import app.search.pipeline as search_pipeline
import app.search.quota as quota_mod
import app.search.registry as search_registry
from app.embedding import registry as embed_registry
from app.embedding.base import EmbeddingError, EmbeddingProvider
from app.embedding.moark import MoarkEmbeddingProvider
from app.models import (
    Direction,
    HotBatch,
    HotTopic,
    Item,
    PipelineTask,
    RankCallLog,
    SearchCallLog,
    Source,
    UsageLog,
)
from app.rerank.base import RankCandidate, RankError, RankProvider, RankedResult
from app.rerank.jev_rank import BochaJevRankProvider, MoarkJevRankProvider
from app.search.base import SearchError, SearchResult


# ---------- 共享桩体 ----------

class RecordingEmbedProvider(EmbeddingProvider):
    """打桩 embed：记录调用，meter 可配，失败脚本可配。永不触网。"""
    name = "fake_embed"
    model_name = "fake-model"

    def __init__(self, db, *, meter=None, failures=None, guard=None):
        super().__init__(db)
        self.calls = []
        self.meter = meter if meter is not None else {}
        self.failures = list(failures or [])  # 每元素 = ("plain", msg) 或 ("retryable", msg)
        self.guard = guard  # 超过该调用次数抛 RuntimeError（防变异体死循环）

    def _embed_request(self, inputs, dimensions):
        self.calls.append({"inputs": list(inputs), "dimensions": dimensions})
        if self.guard is not None and len(self.calls) > self.guard:
            raise RuntimeError("guard: 变异体重试失控")
        if self.failures:
            kind, msg = self.failures.pop(0)
            e = EmbeddingError(msg)
            if kind == "retryable":
                e.retryable = True  # type: ignore[attr-defined]
            raise e
        dim = 4
        vecs = [[0.1] * dim for _ in inputs]
        return vecs, dict(self.meter)


class RecordingRankProvider(RankProvider):
    """打桩 rank：记录实参，按脚本返回分数或抛错。"""
    name = "fake_rank"

    def __init__(self, db, *, scores=None, error=None):
        super().__init__(db)
        self.ranked_calls = []
        self.scores = scores or {}
        self.error = error

    def _rank(self, criteria, candidates):
        self.ranked_calls.append({
            "criteria": criteria,
            "candidates": [(c.id, c.text) for c in candidates],
        })
        if self.error:
            raise RankError(self.error)
        return [
            RankedResult(id=c.id, score=float(self.scores.get(c.id, 0)), band="mid",
                         confidence=None, provider=self.name)
            for c in candidates
        ]


def _patch_clock(monkeypatch, module, start, delta):
    """时钟脚本：monotonic 依次返回 start, start+delta, start, start+delta…"""
    seq = iter([start, start + delta] * 50)
    monkeypatch.setattr(module.time, "monotonic", lambda: next(seq))


# ---------- embedding：计量/重试/构造/注册（ADR-3 / ADR-8） ----------

def test_embed_success_metering_row_full(db_session, monkeypatch):
    """ADR-3 计量全套：按批落行、item_count、延迟、billing_units 透传、ref 归因。"""
    p = RecordingEmbedProvider(db_session)
    # meter 动态按批返回：prompt_tokens=10*条数, billing_units=7
    p.meter = {"prompt_tokens": 0, "billing_units": 7}
    orig_req = p._embed_request

    def req(inputs, dimensions):
        p.meter["prompt_tokens"] = 10 * len(inputs)
        return orig_req(inputs, dimensions)

    p._embed_request = req
    _patch_clock(monkeypatch, emb_base, 100.0, 0.9999)

    vecs = p.embed(["a", "b", "c"], batch_size=2, dimensions=128,
                   ref_type="item", ref_id=5, call_point="embed")
    assert len(vecs) == 3
    assert [c["dimensions"] for c in p.calls] == [128, 128]

    rows = db_session.query(UsageLog).filter_by(provider="fake_embed").order_by(UsageLog.id).all()
    assert len(rows) == 2  # AC-08.1 按批落行
    assert [r.item_count for r in rows] == [2, 1]
    assert [r.prompt_tokens for r in rows] == [20, 10]
    assert all(r.completion_tokens == 0 for r in rows)
    assert all(r.billing_units == 7 for r in rows)  # ADR-8 计费对账可信源
    assert all(r.latency_ms == 999 for r in rows)
    assert all(r.ok is True and r.call_point == "embed" for r in rows)
    assert all(r.ref_type == "item" and r.ref_id == 5 for r in rows)
    assert all(r.model == "fake-model" for r in rows)


def test_embed_meter_missing_keys_default_zero(db_session, monkeypatch):
    """meter 缺 token/billing 键 → 账面 0（缺 key 不崩、不虚记 1）。"""
    p = RecordingEmbedProvider(db_session, meter={})
    p.embed(["a", "b"], batch_size=2)
    rows = db_session.query(UsageLog).all()
    assert len(rows) == 1
    assert rows[0].prompt_tokens == 0
    assert rows[0].completion_tokens == 0
    assert rows[0].billing_units == 0


def test_embed_default_call_point_is_embed(db_session):
    """ADR-3：call_point 缺省 = 'embed'。"""
    p = RecordingEmbedProvider(db_session, meter={"prompt_tokens": 1})
    p.embed(["a"], batch_size=1)
    row = db_session.query(UsageLog).one()
    assert row.call_point == "embed"


def test_embed_retry_cap_exponential_backoff_and_error_records(db_session, monkeypatch):
    """ADR-8：重试≤2（共 3 次尝试）、指数退避 sleep [1,2]、耗尽 raise 含失败事实、
    失败也逐次落账（item_count/latency/ok=False/error 事实）。guard 防变异体死循环。"""
    p = RecordingEmbedProvider(db_session, meter={"prompt_tokens": 3, "billing_units": 1},
                               failures=[("retryable", "HTTP 503: boom")] * 10,
                               guard=5)
    _patch_clock(monkeypatch, emb_base, 200.0, 0.9999)
    sleeps = []
    monkeypatch.setattr(_time_mod, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(EmbeddingError, match="boom"):
        p.embed(["a", "b"], batch_size=2, ref_type="item", ref_id=9)
    assert len(p.calls) == 3  # 重试≤2 → 共 3 次尝试
    assert sleeps == [1, 2]  # 指数退避

    rows = db_session.query(UsageLog).filter_by(provider="fake_embed").all()
    assert len(rows) == 3
    assert all(r.ok is False for r in rows)
    assert all(r.item_count == 2 for r in rows)
    assert all(r.latency_ms == 999 for r in rows)
    assert all("EmbeddingError" in (r.error or "") and "boom" in (r.error or "") for r in rows)
    assert all(r.ref_type == "item" and r.ref_id == 9 for r in rows)


def test_embed_non_retryable_single_attempt(db_session, monkeypatch):
    """ADR-8：非 retryable 的 ProviderError 不重试——1 次尝试即耗尽。"""
    p = RecordingEmbedProvider(db_session, meter={"prompt_tokens": 1},
                               failures=[("plain", "HTTP 400: bad")] * 5, guard=5)
    sleeps = []
    monkeypatch.setattr(_time_mod, "sleep", lambda s: sleeps.append(s))
    with pytest.raises(EmbeddingError, match="bad"):
        p.embed(["a"])
    assert len(p.calls) == 1
    assert sleeps == []


def test_moark_embed_provider_construction(db_session, monkeypatch):
    """ADR-8 D-A（base_url 尾斜杠兼容）/ D-B（api_key 缺省读 config）/ 会话绑定。"""
    import app.config as cfg

    p = MoarkEmbeddingProvider(db_session, base_url="https://api.example.com/",
                               api_key="k-test", model="m1")
    assert p._base_url == "https://api.example.com"  # D-A：去尾斜杠
    assert p._api_key == "k-test"
    assert p._model == "m1" and p.model_name == "m1"

    p2 = MoarkEmbeddingProvider(db_session)
    assert p2._base_url == cfg.MOARK_BASE_URL.rstrip("/")
    assert p2._api_key == cfg.MOARK_API_KEY  # D-B：Bearer 契约的 Key 来源
    assert p2._model == cfg.MOARK_EMBED_MODEL
    assert p2.db is db_session  # 计量落账依赖会话

    # 行为面：经注册表出的实例可完成一次打桩 embed 并落账
    monkeypatch.setattr(p2, "_embed_request", lambda inputs, dims: ([[0.1]], {"prompt_tokens": 2}))
    p2.embed(["x"])
    row = db_session.query(UsageLog).filter_by(provider="moark_embed").one()
    assert row.item_count == 1 and row.model == cfg.MOARK_EMBED_MODEL


def test_embedding_registry_semantics(db_session):
    """registry docstring：注册-获取语义、model 参数化、会话绑定、类型化报错。"""
    import app.config as cfg

    assert "moark" in embed_registry.available()
    p = embed_registry.get_provider("moark", db_session)
    assert isinstance(p, MoarkEmbeddingProvider)
    assert p.db is db_session
    assert p.model_name == cfg.MOARK_EMBED_MODEL
    p3 = embed_registry.get_provider("moark", db_session, model="bge-m3")
    assert p3.model_name == "bge-m3"
    assert p3.db is db_session
    from app.embedding.base import EmbeddingError as EE
    with pytest.raises(EE):
        embed_registry.get_provider("none", db_session)
    with pytest.raises(EE):
        embed_registry.get_provider("no_such", db_session)


# ---------- hot：run_hot_round（AC-05.6 / DT-5 / R2 stats 面） ----------

def _mk_hot_fetch(monkeypatch, mapping):
    monkeypatch.setattr(hot_service.config, "HOT_PLATFORMS", list(mapping.keys()))
    monkeypatch.setattr(hot_service, "fetch_platform", lambda p, **kw: mapping[p])
    monkeypatch.setattr(_time_mod, "sleep", lambda s: None)


WEIBO = [{"title": f"微博热点{i}", "url": f"https://weibo.com/t/{i}",
          "extra": {"info": f"{10000 - i}度"}} for i in range(1, 26)]
ZHIHU = [{"title": f"知乎问题{i}", "url": f"https://zhihu.com/q/{i}", "extra": None}
         for i in range(1, 21)]
ZHIHU_SPECIAL = [{"title": "特别条目", "url": "https://zhihu.com/q/special", "extra": "not-a-dict"}]


def _mk_extract(monkeypatch, keywords=None, summary="", model="m-x", fail=None):
    rec = {"calls": []}

    def fake(db, topics):
        rec["calls"].append({"db": db, "topics": list(topics)})
        if fail:
            raise fail
        return (keywords or ["kwA", "kwB"]), summary, model

    monkeypatch.setattr(hot_service, "_extract_keywords", fake)
    return rec


def test_hot_round_e2e_full_payload_and_batch(db_session, monkeypatch):
    """AC-05.6 全量落库 + §4.1 hot_batch/hot_topic 字段保真 + DT-5 payload.stats
    + 提炼输入按 batch_id 圈定 + 实参透传。"""
    _mk_hot_fetch(monkeypatch, {"weibo": WEIBO, "zhihu": ZHIHU + ZHIHU_SPECIAL})
    rec = _mk_extract(monkeypatch, summary="综述" * 150, model="model-x")  # 300 字

    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "DONE"
    assert out["topics_stored"] == 46
    assert out["keywords"] == ["kwA", "kwB"]
    assert len(out["summary"]) == 200  # AC-05.6 summary ≤200
    batch = db_session.query(HotBatch).one()
    assert out["batch_id"] == batch.id

    task = db_session.get(PipelineTask, out["task_id"])
    assert task.kind == "hot_round"
    assert task.payload["triggered_by"] == "test"
    stats = task.payload["stats"]
    assert set(stats.keys()) == {"platforms", "topics_stored", "batch_id",
                                 "keywords", "kw_error", "hot_rank_filter"}
    assert stats["topics_stored"] == 46 and stats["batch_id"] == batch.id
    assert stats["keywords"] == ["kwA", "kwB"] and stats["kw_error"] is None

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", batch.date)  # YYYY-MM-DD 本地日期
    assert batch.keywords == ["kwA", "kwB"]
    assert batch.summary == "综述" * 150  # 库内全量；返回面截 200
    assert batch.model == "model-x"
    assert sorted(batch.source_platforms) == ["weibo", "zhihu"]

    assert db_session.query(HotTopic).count() == 46  # 全量落库
    w1 = db_session.query(HotTopic).filter_by(platform="weibo", rank=1).one()
    assert w1.title == "微博热点1" and w1.url == "https://weibo.com/t/1"
    assert w1.extra == {"info": "9999度"} and w1.keyword_contrib is True
    w25 = db_session.query(HotTopic).filter_by(platform="weibo", rank=25).one()
    assert w25.keyword_contrib is False
    spec = db_session.query(HotTopic).filter_by(title="特别条目").one()
    assert spec.extra is None  # 非 dict extra 落 None

    # 提炼输入：本轮 batch 的 keyword_contrib 条目（weibo 前 20 + zhihu 前 20）
    assert len(rec["calls"][0]["topics"]) == 40
    assert rec["calls"][0]["db"] is db_session


def test_hot_round_second_round_input_scoped_to_batch(db_session, monkeypatch):
    """覆盖式 batch 语义：第 2 轮提炼输入只含本轮 keyword_contrib 条目。"""
    _mk_hot_fetch(monkeypatch, {"weibo": WEIBO})
    rec = _mk_extract(monkeypatch)
    hot_service.run_hot_round(db_session, triggered_by="test")
    out2 = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out2["status"] == "DONE"
    assert len(rec["calls"][-1]["topics"]) == 20  # 而非 40


def test_hot_round_default_trigger_full_round(db_session, monkeypatch):
    """W5 归因先例：缺省 triggered_by=scheduler 落入任务 payload。"""
    _mk_hot_fetch(monkeypatch, {"weibo": WEIBO})
    _mk_extract(monkeypatch)
    out = hot_service.run_hot_round(db_session)
    task = db_session.get(PipelineTask, out["task_id"])
    assert task.payload["triggered_by"] == "scheduler"


def test_hot_round_anti_overlap_busy(db_session, monkeypatch):
    """防重叠：round_busy(kind='hot_round') 命中 → skip 形状。"""
    kinds = []
    monkeypatch.setattr(hot_service.config, "HOT_PLATFORMS", ["weibo"])
    monkeypatch.setattr(hot_service, "round_busy",
                        lambda db, kind: kinds.append(kind) or True)
    out = hot_service.run_hot_round(db_session)
    assert out["skipped"] is True and "reason" in out
    assert kinds == ["hot_round"]
    assert db_session.query(PipelineTask).count() == 0


def test_hot_round_claim_failure_skipped_shape(db_session, monkeypatch):
    """认领失败 → {skipped: True, reason}（P0-1 认领语义）。"""
    _mk_hot_fetch(monkeypatch, {"weibo": WEIBO})
    _mk_extract(monkeypatch)
    monkeypatch.setattr(hot_service, "_claim", lambda db, task: False)
    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["skipped"] is True and "reason" in out


def test_hot_round_partial_failure_platform_stats(db_session, monkeypatch):
    """AC-05.6 单平台失败不中断；失败平台统计行如实呈现（error 事实）。"""
    def flaky(p, **kw):
        if p == "weibo":
            raise RuntimeError("api down")
        return ZHIHU

    monkeypatch.setattr(hot_service.config, "HOT_PLATFORMS", ["weibo", "zhihu"])
    monkeypatch.setattr(hot_service, "fetch_platform", flaky)
    monkeypatch.setattr(_time_mod, "sleep", lambda s: None)
    _mk_extract(monkeypatch)

    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "DONE"
    stats = out["platforms"]
    failed = [s for s in stats if not s["ok"]]
    ok = [s for s in stats if s["ok"]]
    assert len(failed) == 1 and len(ok) == 1
    f = failed[0]
    assert f["platform"] == "weibo"
    assert f["error"] == "RuntimeError: api down"
    assert isinstance(f["ms"], int)
    assert out["topics_stored"] == 20
    batch = db_session.query(HotBatch).one()
    assert batch.source_platforms == ["zhihu"]  # 只有成功平台进 batch


def test_hot_round_all_failed_extended(db_session, monkeypatch):
    """AC-05.6 全平台失败 FAILED 不 mock：返回 platforms + payload.stats.platforms。"""
    def down(p, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(hot_service.config, "HOT_PLATFORMS", ["weibo", "zhihu", "bilibili"])
    monkeypatch.setattr(hot_service, "fetch_platform", down)
    monkeypatch.setattr(_time_mod, "sleep", lambda s: None)

    out = hot_service.run_hot_round(db_session, triggered_by="test")
    assert out["status"] == "FAILED"
    assert out["platforms"] and all(s["ok"] is False for s in out["platforms"])
    task = db_session.get(PipelineTask, out["task_id"])
    assert task.status == "FAILED"
    assert task.payload["stats"]["platforms"] == out["platforms"]
    assert "全部平台拉取失败" in (task.last_error or "")
    assert db_session.query(HotBatch).count() == 0
    assert db_session.query(HotTopic).count() == 0


def test_hot_round_extract_failure_keeps_topics_and_records_kw_error(db_session, monkeypatch):
    """提炼失败不丢榜单数据；kw_error 计入 stats。提炼失败已拍板为分态面：
    任务 DONE + degraded 标记，关键词落标题分词兜底（不再为空表）。"""
    _mk_hot_fetch(monkeypatch, {"weibo": WEIBO[:3]})
    _mk_extract(monkeypatch, fail=RuntimeError("llm boom"))

    out = hot_service.run_hot_round(db_session, triggered_by="test")
    task = db_session.get(PipelineTask, out["task_id"])
    stats = task.payload["stats"]
    assert stats["kw_error"] == "RuntimeError: llm boom"
    assert stats["degraded"] == ["hot_keywords"] and stats["kw_fallback"] == "title_tokens"
    assert task.status == "DONE" and task.last_error is None
    assert stats["keywords"] == ["微博", "博热", "热点"]  # 标题分词兜底（数字段剔除）
    assert db_session.query(HotTopic).count() == 3  # 榜单数据保全
    batch = db_session.query(HotBatch).one()
    assert batch.keywords == stats["keywords"] and batch.summary == "" and batch.model == ""


# ---------- hot：_rank_filter_topics（能力⑤应用点2 默认关） ----------

def _mk_filter_env(db_session, monkeypatch, *, scores, error=None, env=True, n=3):
    d = Direction(name="HOTD8", prompt="方向提示词P", threshold=60)
    db_session.add(d)
    batch = HotBatch(date="2026-10-04", keywords=[], summary="", source_platforms=["x"], model="")
    db_session.add(batch)
    db_session.flush()
    topics = []
    for i in range(1, n + 1):
        t = HotTopic(platform="x", rank=i, title=f"话题{i}", url=f"https://x/{i}",
                     keyword_contrib=True, batch_id=batch.id)
        db_session.add(t)
        topics.append(t)
    db_session.commit()

    provider = RecordingRankProvider(db_session, scores=scores, error=error)
    factory_calls = []

    def fake_factory(name, db):
        factory_calls.append({"name": name, "db": db})
        return provider

    monkeypatch.setattr(rank_registry, "get_provider", fake_factory)
    if env:
        monkeypatch.setenv("HOT_RANK_FILTER", "true")
        monkeypatch.setenv("HOT_RANK_PROVIDER", "fake_rank")
    else:
        monkeypatch.delenv("HOT_RANK_FILTER", raising=False)
        monkeypatch.delenv("HOT_RANK_PROVIDER", raising=False)
    return topics, provider, factory_calls, d


def test_hot_rank_filter_default_off_meta(db_session, monkeypatch):
    """能力⑤应用点2：默认关——不过滤，meta {hot_rank_filter: False}。"""
    topics, _, factory_calls, _ = _mk_filter_env(db_session, monkeypatch,
                                                 scores={}, env=False)
    kept, meta = hot_service._rank_filter_topics(db_session, topics)
    assert kept == topics
    assert meta == {"hot_rank_filter": False}
    assert factory_calls == []  # 未启用不取 provider


def test_hot_rank_filter_on_semantics(db_session, monkeypatch):
    """开关 on（=true 生效）：按分数过滤、meta 逐键、rank 实参透传、factory 实参。"""
    topics, provider, factory_calls, d = _mk_filter_env(
        db_session, monkeypatch, scores={1: 80.0, 2: 30.0, 3: 10.0})
    kept, meta = hot_service._rank_filter_topics(db_session, topics)
    assert [t.id for t in kept] == [topics[0].id]  # 仅 80 ≥ 缺省 40
    assert meta == {"hot_rank_filter": True, "provider": "fake_rank",
                    "input": 3, "kept": 1}
    assert factory_calls[0]["name"] == "fake_rank"
    assert factory_calls[0]["db"] is db_session
    call = provider.ranked_calls[0]
    assert call["criteria"] == d.prompt  # criteria=方向提示词
    assert call["candidates"] == [(t.id, t.title) for t in topics]


def test_hot_rank_filter_on_via_rank_call_key(db_session, monkeypatch):
    """criteria_key 归因：hot:{方向名}（经 rank_call_log 落账面断言）。"""
    topics, provider, _, d = _mk_filter_env(db_session, monkeypatch,
                                            scores={1: 80.0, 2: 30.0, 3: 10.0})
    hot_service._rank_filter_topics(db_session, topics)
    log = db_session.query(RankCallLog).one()
    assert log.criteria_key == f"hot:{d.name}"
    assert log.provider == "fake_rank" and log.candidate_count == 3


def test_hot_rank_filter_rank_error_fallback_meta(db_session, monkeypatch):
    """RankError → 回退原输入，meta 如实记录（error/fallback）。"""
    topics, _, _, _ = _mk_filter_env(db_session, monkeypatch, scores={},
                                     error="rank down")
    kept, meta = hot_service._rank_filter_topics(db_session, topics)
    assert kept == topics
    assert meta == {"hot_rank_filter": True, "provider": "fake_rank",
                    "error": "rank down", "fallback": True}


def test_hot_rank_filter_no_enabled_direction(db_session, monkeypatch):
    """无启用方向 → 原输入 + meta 键面。"""
    topics, _, _, _ = _mk_filter_env(db_session, monkeypatch, scores={})
    # 全部方向禁用
    for d in db_session.query(Direction).all():
        d.enabled = False
    db_session.commit()
    kept, meta = hot_service._rank_filter_topics(db_session, topics)
    assert kept == topics
    assert set(meta.keys()) == {"hot_rank_filter", "error"}
    assert meta["hot_rank_filter"] is True


# ---------- rerank：RankProvider 底座（AC-05.4 同款 / §4.1 rank_call_log） ----------

def _register_c18_rank(monkeypatch, provider):
    rank_registry.register("c18_rank", lambda db: provider)
    return provider


def test_rank_quota_blocked_row_full(db_session, monkeypatch):
    """额度闸 blocked：返回 [] + rank_call_log 逐字段（AC-05.4 同款语义）。"""
    p = RecordingRankProvider(db_session, scores={1: 90.0})
    _register_c18_rank(monkeypatch, p)
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_MINUTE", 0)
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_DAY", 100)

    out = p.rank("标准X", [RankCandidate(id=1, text="a")], criteria_key="ck9")
    assert out == []
    log = db_session.query(RankCallLog).one()
    assert log.provider == "fake_rank"
    assert log.candidate_count == 0
    assert log.criteria_key == "ck9"
    assert log.latency_ms == 0
    assert log.ok is False
    assert log.status == "blocked"
    assert log.error == "SKIPPED_QUOTA"
    assert p.ranked_calls == []  # 调用未发出


def test_rank_ok_row_truncation_and_criteria(db_session, monkeypatch):
    """正常调用：criteria 透传、候选截断（cap 30 / 文本 500）、成功账行逐字段。"""
    from app import config as cfg
    p = RecordingRankProvider(db_session, scores={i: 50.0 for i in range(40)})
    _register_c18_rank(monkeypatch, p)
    _patch_clock(monkeypatch, rerank_base, 300.0, 0.9999)

    cands = [RankCandidate(id=i, text="字" * 600) for i in range(35)]
    results = p.rank("方向标准词", cands, criteria_key="CK")
    assert len(results) == 30  # RANK_MAX_CANDIDATES
    call = p.ranked_calls[0]
    assert call["criteria"] == "方向标准词"
    assert len(call["candidates"]) == 30
    assert all(len(t) == cfg.RANK_TEXT_MAX_CHARS for _, t in call["candidates"])

    log = db_session.query(RankCallLog).one()
    assert log.candidate_count == 30
    assert log.criteria_key == "CK"
    assert log.latency_ms == 999
    assert log.ok is True and log.status == "ok"

    # criteria_key 缺省 → None（非占位串）
    p2 = RecordingRankProvider(db_session, scores={1: 1.0})
    rank_registry.register("c18_rank2", lambda db: p2)
    p2 = rank_registry.get_provider("c18_rank2", db_session)
    p2.rank("标准", [RankCandidate(id=1, text="a")])
    log2 = db_session.query(RankCallLog).order_by(RankCallLog.id.desc()).first()
    assert log2.criteria_key is None


def test_rank_error_row_full(db_session, monkeypatch):
    """RankError：抛出原错误 + 失败账行逐字段。"""
    p = RecordingRankProvider(db_session, scores={}, error="rank boom")
    _register_c18_rank(monkeypatch, p)
    _patch_clock(monkeypatch, rerank_base, 400.0, 0.9999)

    with pytest.raises(RankError, match="rank boom"):
        p.rank("标准", [RankCandidate(id=1, text="a"), RankCandidate(id=2, text="b")],
               criteria_key="CK2")
    log = db_session.query(RankCallLog).one()
    assert log.ok is False and log.status == "error"
    assert log.error == "rank boom"
    assert log.candidate_count == 2
    assert log.latency_ms == 999
    assert log.criteria_key == "CK2"


def test_rank_registry_fixed_model_bindings(db_session):
    """EV6 四固定 reranker 配置 + neohorse Jev 配置：注册名 → model 全参绑定。"""
    import app.config as cfg

    fixed = {
        "moark_reranker_qwen3_06b": "Qwen3-Reranker-0.6B",
        "moark_reranker_qwen3_4b": "Qwen3-Reranker-4B",
        "moark_reranker_qwen3_8b": "Qwen3-Reranker-8B",
        "moark_reranker_bge_v2_m3": "bge-reranker-v2-m3",
    }
    for name, model in fixed.items():
        p = rank_registry.get_provider(name, db_session)
        assert p._model == model, name
        assert p.db is db_session

    nh = rank_registry.get_provider("moark_jev_neohorse", db_session)
    assert nh.name == "moark_jev_neohorse"
    assert isinstance(nh, MoarkJevRankProvider)
    assert nh.db is db_session
    assert nh._base_url == cfg.MOARK_BASE_URL
    assert nh._api_key == cfg.MOARK_API_KEY
    assert nh._model == cfg.MOARK_JEV_MODEL_NEOHORSE


def test_bocha_jev_provider_construction(db_session, monkeypatch):
    """bocha_jev：Key 缺省读 config（D-B），构造参数全透传。
    Key 注入测试值——不依赖真实密钥（CI 无 .env）。"""
    import app.config as cfg

    monkeypatch.setattr(cfg, "BOCHA_API_KEY", "test-key")
    p = rank_registry.get_provider("bocha_jev", db_session)
    assert p.name == "bocha_jev"
    assert p.db is db_session
    assert p._base_url == cfg.BOCHA_JEV_BASE_URL
    assert p._api_key == "test-key"
    assert p._model == cfg.BOCHA_JEV_MODEL
    p2 = BochaJevRankProvider(db_session, api_key="explicit-key")
    assert p2._api_key == "explicit-key"
    monkeypatch.setattr(cfg, "BOCHA_API_KEY", "")
    with pytest.raises(RankError, match="缺少 API Key"):
        BochaJevRankProvider(db_session)  # config 亦缺 → 拒构造


# ---------- search：额度闸 quota（AC-05.4） ----------

def test_quota_provider_env_override_and_defaults(db_session, monkeypatch):
    """quota docstring：SEARCH_QUOTA_<PROVIDER>_MINUTE/_DAY env 优先，缺省全局。"""
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_MINUTE", 5)
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_DAY", 50)
    assert quota_mod._provider_limits("px") == (5, 50)
    monkeypatch.setenv("SEARCH_QUOTA_PX_MINUTE", "3")
    monkeypatch.setenv("SEARCH_QUOTA_PX_DAY", "9")
    assert quota_mod._provider_limits("px") == (3, 9)
    assert quota_mod._provider_limits("other") == (5, 50)


def test_quota_state_window_keys(db_session, monkeypatch):
    """双窗键格式：分钟 %Y-%m-%dT%H:%M、日 %Y-%m-%d（AC-05.4 下一分钟恢复语义）。"""
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_MINUTE", 8)
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_DAY", 200)
    now = datetime(2026, 10, 4, 13, 45)
    state = quota_mod.quota_state(db_session, "px", now=now)
    assert state["minute_key"] == "2026-10-04T13:45"
    assert state["day_key"] == "2026-10-04"
    assert state["minute"] == {"limit": 8, "used": 0}
    assert state["day"] == {"limit": 200, "used": 0}


def test_quota_isolation_per_provider(db_session):
    """provider 维度隔离：pa 的预占不进 pb 的计数。"""
    now = datetime(2026, 10, 4, 13, 45)
    allowed_a, s_a = quota_mod.check_and_count(db_session, "pa", now=now)
    assert allowed_a and s_a["minute"]["used"] == 1
    allowed_b, s_b = quota_mod.check_and_count(db_session, "pb", now=now)
    assert allowed_b and s_b["minute"]["used"] == 1
    assert s_b["day"]["used"] == 1


# ---------- search：registry（模块 docstring 注册-获取语义） ----------

def test_search_registry_real_entries(monkeypatch):
    """已注册名 bocha 可得 BochaSearchProvider 实例；未知名类型化 SearchError。
    Key 注入测试值——不依赖真实密钥（CI 无 .env）。"""
    from app.search.bocha import BochaSearchProvider

    monkeypatch.setattr("app.config.BOCHA_API_KEY", "test-key")
    assert search_registry.available() == ["bocha", "tencent"]
    p = search_registry.get_provider("bocha")
    assert isinstance(p, BochaSearchProvider)
    assert p._api_key == "test-key"
    with pytest.raises(SearchError):
        search_registry.get_provider("no_such_xyz")


# ---------- search：fetch_search_source 通道（§4.1 search_call_log / D15 / AC-06） ----------

def _mk_search_source(db, name, cfg_extra=None, direction=None):
    if direction is None:
        direction = Direction(name=name + "-D", prompt="p", threshold=60)
        db.add(direction)
        db.commit()
    cfg_ = {"keyword": f"测试词{name}", "provider": "fakeprov", "group": "g9",
            "count": 3, "freshness": "oneDay"}
    cfg_.update(cfg_extra or {})
    src = Source(direction_id=direction.id, url=f"search://fakeprov/{name}",
                 type="search", source_config=cfg_)
    db.add(src)
    db.commit()
    return src


def _patch_search_provider(monkeypatch, search_fn):
    """打桩：factory 记录 name，search 记录 (q, count, opts) 实参。"""
    calls = []

    class P:
        name = "fakeprov"

        def search(self, q, count=10, **kw):
            calls.append({"q": q, "count": count, "kw": dict(kw)})
            return search_fn(q, count, kw)

    monkeypatch.setattr(search_registry, "get_provider",
                        lambda name, db=None: calls.append({"name": name}) or P())
    return calls


def _results(specs):
    out = []
    for s in specs:
        out.append(SearchResult(
            title=s.get("title", "结果"),
            url=s.get("url", "https://ex.com/a"),
            snippet=s.get("snippet", "摘要"),
            content=s.get("content", "全文" * 200),
            published_at=s.get("published_at", datetime(2026, 9, 27)),
            raw={"k": 1},
        ))
    return out


def test_search_channel_quota_blocked_row_full(db_session, monkeypatch):
    """AC-05.4：超限不发出；search_call_log blocked 行逐字段；stats 归因。"""
    src = _mk_search_source(db_session, "B1")
    calls = _patch_search_provider(monkeypatch, lambda q, c, kw: [])
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_MINUTE", 0)
    monkeypatch.setattr(quota_mod.config, "SEARCH_QUOTA_DEFAULT_DAY", 100)

    stats = search_pipeline.fetch_search_source(db_session, src)
    assert calls == []  # 调用未发出（额度闸在 get_provider 之前）
    assert stats.extra.get("quota_blocked") is True
    assert stats.inserted == 0
    assert stats.source_id == src.id and stats.url == src.url
    log = db_session.query(SearchCallLog).one()
    assert log.provider == "fakeprov"
    assert log.query == "测试词B1"
    assert log.keyword_group == "g9"
    assert log.result_count == 0 and log.latency_ms == 0
    assert log.ok is False and log.status == "blocked"
    assert log.error == "SKIPPED_QUOTA"


def test_search_channel_e2e_row_shapes(db_session, monkeypatch):
    """通道端到端：source_config 全实参透传、ok 账行、item 行保真、规则/sanitize 分桶。"""
    src = _mk_search_source(db_session, "E1")
    recent = datetime.now(timezone.utc) - timedelta(days=3)
    old = datetime.now(timezone.utc) - timedelta(days=400)
    d365half = datetime.now(timezone.utc) - timedelta(days=365, hours=12)  # age 365.5 天
    d400 = datetime.now(timezone.utc) - timedelta(days=400)
    d40 = datetime.now(timezone.utc) - timedelta(days=40)
    specs = [
        {"url": "https://ex.com/a/1", "title": "标题一"},                        # FETCHED
        {"url": "", "title": "无URL"},                                           # guid 空跳过
        {"url": "", "title": "无URL二"},                                         # 第二个 guid 空跳过
        {"url": "https://ex.com/a/2", "title": "标题二", "published_at": d400},  # 规则过期拒绝
        {"url": "https://ex.com/a/3", "title": "标题三", "content": "禁词内容" * 50},  # sanitize 拒
        {"url": "https://ex.com/a/4", "title": "标题四"},                        # FETCHED
        {"url": "https://ex.com/a/5", "title": "标题五", "published_at": d365half},  # 365.5 天 > 365 拒
        {"url": "https://ex.com/a/6", "title": "标题六", "published_at": d40},   # 40 天:缺省 365 收
        {"url": "https://ex.com/a/7", "title": "标题七", "content": "又一禁词" * 40},  # 第二个 sanitize 拒
    ]
    calls = _patch_search_provider(monkeypatch, lambda q, c, kw: _results(specs))
    _patch_clock(monkeypatch, search_pipeline, 500.0, 0.9999)
    monkeypatch.setattr(search_pipeline.config, "SANITIZE_ENABLED", True)
    monkeypatch.setattr(search_pipeline.config, "SANITIZE_DENY_KEYWORDS", ["禁词", "又一禁词"])

    stats = search_pipeline.fetch_search_source(db_session, src)
    # source_config 全实参透传（provider/keyword/count/freshness）
    assert calls[0] == {"name": "fakeprov"}
    assert calls[1]["q"] == "测试词E1"
    assert calls[1]["count"] == 3
    assert calls[1]["kw"] == {"freshness": "oneDay"}

    # F2 账目口径统一（与 RSS 同式）：inserted 只含 FETCHED/DUP 落行（4 落行），
    # 规则拒绝行单列 rule_rejected（3）；无 guid 拦截行入 dup_blocked 桶——等式
    # 9（feed_entries）= 4 + 2 + 3 + 0 + 0 平衡
    assert stats.inserted == 4
    assert stats.guid_collisions == 2
    assert stats.dup_blocked == 2
    assert stats.rule_rejected == 3  # 二条过期 + 一条 too_short(禁词样本 160 字<min)
    assert stats.feed_entries == (stats.inserted + stats.dup_blocked + stats.rule_rejected
                                  + stats.failed + stats.archived)
    assert stats.sanitize_passed == 5 and stats.sanitize_rejected == 2

    # ok 账行
    log = db_session.query(SearchCallLog).one()
    assert log.provider == "fakeprov" and log.query == "测试词E1"
    assert log.keyword_group == "g9" and log.result_count == 9  # 返回条数含无 guid 条目
    assert log.latency_ms == 999 and log.ok is True and log.status == "ok"

    items = {it.title: it for it in db_session.query(Item).filter_by(source_id=src.id).all()}
    assert len(items) == 7
    it1 = items["标题一"]
    assert it1.url == "https://ex.com/a/1"
    assert it1.fetch_status == "FETCHED"
    assert it1.content_text.startswith("全文")
    assert it1.raw == {"k": 1}
    assert it1.fetched_at is not None
    assert it1.direction_id == src.direction_id
    assert it1.fingerprint  # url_fingerprint 落行
    assert it1.sanitize_status == "PASSED"
    it2 = items["标题二"]
    assert it2.fetch_status == "REJECTED_RULED" and it2.rule_reject_reason
    assert it2.sanitize_status == "PASSED"
    it3 = items["标题三"]
    assert it3.sanitize_status == "REJECTED" and it3.sanitize_reason
    assert it3.sanitize_detail and it3.sanitize_detail.get("stage")
    it5 = items["标题五"]
    assert it5.fetch_status == "REJECTED_RULED" and it5.rule_reject_reason
    assert it5.sanitize_status == "PASSED"
    it6 = items["标题六"]
    assert it6.fetch_status == "FETCHED"  # 40 天 < 缺省 365 天口径


def test_search_channel_max_age_override_and_default_boundary(db_session, monkeypatch):
    """搜索过期口径：缺省 365 天（docstring 钉死）、source_config.max_age_days 可覆盖。"""
    src = _mk_search_source(db_session, "M1")
    d365half = datetime.now(timezone.utc) - timedelta(days=365, hours=12)  # age=365.5 天
    specs = [{"url": "https://ex.com/m/1", "title": "老文", "published_at": d365half}]
    _patch_search_provider(monkeypatch, lambda q, c, kw: _results(specs))
    stats = search_pipeline.fetch_search_source(db_session, src)
    it = db_session.query(Item).filter_by(source_id=src.id).one()
    assert it.fetch_status == "REJECTED_RULED"  # age 365.5 > 缺省 365（366 则收→边界钉死）

    # 覆盖：max_age_days=30 → 40 天老文拒绝
    src2 = _mk_search_source(db_session, "M2", cfg_extra={"max_age_days": 30})
    d40 = datetime.now(timezone.utc) - timedelta(days=40)
    _patch_search_provider(monkeypatch, lambda q, c, kw: _results(
        [{"url": "https://ex.com/m/2", "title": "四十天", "published_at": d40}]))
    stats2 = search_pipeline.fetch_search_source(db_session, src2)
    it2 = db_session.query(Item).filter_by(source_id=src2.id).one()
    assert it2.fetch_status == "REJECTED_RULED"


def test_search_channel_provider_error_row(db_session, monkeypatch):
    """SearchError：stats.error 留痕 + error 账行逐字段。"""
    src = _mk_search_source(db_session, "X1")

    class P:
        name = "fakeprov"

        def search(self, q, count=10, **kw):
            raise SearchError("search boom")

    monkeypatch.setattr(search_registry, "get_provider", lambda name, db=None: P())
    stats = search_pipeline.fetch_search_source(db_session, src)
    assert "search boom" in stats.error
    log = db_session.query(SearchCallLog).one()
    assert log.ok is False and log.status == "error"
    assert log.error == "search boom"
    assert log.result_count == 0 and log.latency_ms == 0
    assert log.keyword_group == "g9" and log.provider == "fakeprov"


def test_search_channel_cross_source_fingerprint_dup(db_session, monkeypatch):
    """D15/P1-2：同方向跨源同 URL → DUP 落行（全文照存）；(source_id,guid) 源内去重。"""
    from app.ingest.fingerprint import url_fingerprint

    d = Direction(name="DUPD8", prompt="p", threshold=60)
    db_session.add(d)
    db_session.flush()
    src_a = Source(direction_id=d.id, url="rss://a")
    db_session.add(src_a)
    db_session.commit()
    url = "https://dup.example.com/article/9"
    it_a = Item(source_id=src_a.id, guid="https://dup.example.com/article/9", url=url,
                title="原文章", content_text="原文全文", sanitize_status="PASSED",
                fetch_status="FETCHED", fingerprint=url_fingerprint(url),
                direction_id=d.id)
    db_session.add(it_a)
    db_session.commit()

    src_b = _mk_search_source(db_session, "D1", direction=d)
    _patch_search_provider(monkeypatch, lambda q, c, kw: _results(
        [{"url": url, "title": "重复文章", "content": "重复全文" * 100}]))
    stats = search_pipeline.fetch_search_source(db_session, src_b)
    assert stats.inserted == 1  # DUP 也落行
    it_b = db_session.query(Item).filter_by(source_id=src_b.id).one()
    assert it_b.fetch_status == "DUP"
    assert it_b.duplicate_of == it_a.id
    assert it_b.content_text.startswith("重复全文")  # 全文照存
    assert it_b.fingerprint == it_a.fingerprint


def test_search_channel_fulltext_falls_back_to_snippet(db_session, monkeypatch):
    """item 全文口径：content 缺则 snippet（docstring 钉死）。"""
    src = _mk_search_source(db_session, "F1")
    _patch_search_provider(monkeypatch, lambda q, c, kw: _results(
        [{"url": "https://ex.com/f/1", "title": "无全文", "content": "",
          "snippet": "摘要内容" * 30}]))
    search_pipeline.fetch_search_source(db_session, src)
    it = db_session.query(Item).filter_by(source_id=src.id).one()
    assert it.content_text.startswith("摘要内容")
