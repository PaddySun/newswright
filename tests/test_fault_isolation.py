"""故障隔离与降级秩序测试：LLM 全挂全景、Token 日预算四档降级、恢复自愈补打顺序。

覆盖口径：
- LLM 全不可用：新条目照常入库、全文可查；score 每条 FAILED 但任务可恢复不阻塞
  下一轮；B 流仍可浏览且未评分条目带"暂未评分"标注；调度无死锁；
- 预算闸四档秩序（低优先级先停）：探索层暂停 → 嵌入暂停（回退全量慢速）→
  打分转慢速（继续低速不绝停）→ 写作需站长确认；采集与呈现零降级；
- 恢复自愈：FAILED 条目下轮自动补打，命中检索优先的条目先补。
设计依据见 docs/design-index.md「AC-21.1」「AC-21.2」「AC-21.4」。
"""
import threading
import types

import numpy as np

import app.pipeline.runner as runner_mod
from app.models import (
    Direction,
    Item,
    ItemVec,
    PipelineTask,
    ScoreResult,
    Source,
    UsageLog,
)
from app.pipeline.runner import enqueue_fetch_round, process_fetch_round, score_round
from app.retrieval.embedder import vec_to_blob
from app.siteconfig import set_config


def _stats(**kw) -> types.SimpleNamespace:
    base = dict(source_id=1, url="https://feeds.example/o.xml", feed_entries=1,
                inserted=1, dup_blocked=0, rule_rejected=0, failed=0, archived=0,
                not_modified=False, sanitize_passed=1, sanitize_rejected=0,
                error=None, guid_collisions=0, rate_limited=False,
                retry_after=None, extra={})
    base.update(kw)
    return types.SimpleNamespace(**base)


def _seed_direction(db, *, n_items=1, with_vecs=False, query_vec=False):
    d = Direction(name="隔离方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url="https://feeds.example/o.xml")
    db.add(src)
    db.commit()
    items = []
    for i in range(n_items):
        item = Item(source_id=src.id, guid=f"g{i}", url=f"https://example.com/{i}",
                    title=f"标题{i}", content_text=f"条目{i}的全文内容",
                    fetch_status="FETCHED", direction_id=d.id,
                    sanitize_status="PASSED")
        db.add(item)
        items.append(item)
    db.commit()
    return d, items


# ---------- AC-21.1：LLM 全不可用全景 ----------


def test_llm_down_essential_pipeline_unaffected(db_session, auth_client, monkeypatch):
    d, _ = _seed_direction(db_session)
    created, fetch_calls = [], []

    def fake_fetch(db, src):
        # 第二轮起无新条目（同 guid 幂等），管线仍 DONE
        guid = f"live-{len(fetch_calls)}" if not fetch_calls else f"live-{len(fetch_calls)}-dup-archived"
        fetch_calls.append(guid)
        if len(fetch_calls) == 1:
            item = Item(source_id=src.id, guid=guid, url="https://example.com/live",
                        title="新条目", content_text="新条目的全文内容",
                        fetch_status="FETCHED", direction_id=src.direction_id,
                        sanitize_status="PASSED")
            db.add(item)
            db.commit()
            created.append(item.id)
        return _stats(source_id=src.id, url=src.url,
                      inserted=0 if len(fetch_calls) > 1 else 1,
                      feed_entries=0 if len(fetch_calls) > 1 else 1)

    monkeypatch.setattr(runner_mod, "_fetch_one", fake_fetch)
    round_task = enqueue_fetch_round(db_session, triggered_by="test")
    summary = process_fetch_round(db_session, round_task)
    assert summary["status"] == "DONE"  # 新条目照常入库（fetch 任务 DONE）

    def llm_down(db, item, direction):
        # 与真实 score_item 同构：provider 故障落 FAILED 行（错误原因入库）
        sr = ScoreResult(item_id=item.id, direction_id=direction.id, model="m",
                         status="FAILED", error="ProviderError: LLM 全挂 Key 失效")
        db.add(sr)
        db.commit()
        return sr

    monkeypatch.setattr("app.scoring.service.score_item", llm_down)
    score = score_round(db_session, triggered_by="test")
    dstat = score["directions"][0]
    assert dstat["scored"] == 0 and dstat["call_failed"] > 0
    failed_rows = (db_session.query(ScoreResult)
                   .filter_by(status="FAILED").count())
    assert failed_rows > 0  # 每条记 FAILED
    # 全文可查 + B 流仍可浏览，未评分条目带"暂未评分"标注
    item = db_session.get(Item, created[0])
    assert "新条目的全文内容" in (item.content_text or "")
    r = auth_client.get("/stream/b", params={"direction_id": d.id})
    assert r.status_code == 200
    body = r.json()
    assert any(u["note"] == "暂未评分" and u["id"] == created[0]
               for u in body["unscored"])
    # 调度器无死锁：下一轮 fetch 照常入队执行
    round_task2 = enqueue_fetch_round(db_session, triggered_by="test")
    assert round_task2 is not None
    summary2 = process_fetch_round(db_session, round_task2)
    assert summary2["status"] == "DONE"


# ---------- AC-21.2：预算闸四档降级 ----------


def _trigger_budget(db, *, tokens=1000):
    db.add(UsageLog(provider="stub", model="m", call_point="scoring",
                    prompt_tokens=tokens, ok=True))
    db.commit()
    set_config(db, "daily_token_budget", 500)


def test_budget_1_explore_tier_paused(db_session, auth_client):
    d, _ = _seed_direction(db_session)
    set_config(db_session, "explore_enabled", True)
    r = auth_client.get("/stream/b", params={"direction_id": d.id})
    assert r.json()["explore"]["inserted"] == 0  # 预算未触发时的正常态（无候选）
    _trigger_budget(db_session)
    r = auth_client.get("/stream/b", params={"direction_id": d.id})
    body = r.json()
    assert body["explore"].get("budget_paused") is True
    assert body["explore"]["inserted"] == 0  # 探索层暂停：选样返回空


def test_budget_2_embed_paused_falls_back_slow(db_session, monkeypatch):
    d, items = _seed_direction(db_session, n_items=2)
    _trigger_budget(db_session)
    calls = []

    def should_not_embed(db, its, **kw):
        calls.append(its)
        return {"model_version": None, "missing": 0, "embedded": 0,
                "failed": 0, "disabled": True}

    monkeypatch.setattr("app.retrieval.embedder.ensure_item_vectors", should_not_embed)

    def fake_score(db, item, direction):
        return ScoreResult(item_id=item.id, direction_id=direction.id, model="m",
                           status="OK", passed=True, relevance_score=80,
                           quality_score=80, band="high")

    monkeypatch.setattr("app.scoring.service.score_item", fake_score)
    summary = score_round(db_session, triggered_by="test")
    dstat = summary["directions"][0]
    assert calls == []  # 嵌入暂停：零补齐调用
    assert dstat["budget_embed_paused"] is True
    assert dstat["embed_disabled"] is True  # 路由自动回退全量慢速
    assert dstat["scored"] == 2  # 打分零损失


def test_budget_3_score_slow_round_cap_continues(db_session, monkeypatch):
    d, items = _seed_direction(db_session, n_items=30)
    _trigger_budget(db_session)
    scored_ids = []

    def fake_score(db, item, direction):
        scored_ids.append(item.id)
        sr = ScoreResult(item_id=item.id, direction_id=direction.id, model="m",
                         status="OK", passed=True, relevance_score=80,
                         quality_score=80, band="high")
        db.add(sr)
        db.commit()
        return sr

    monkeypatch.setattr("app.scoring.service.score_item", fake_score)
    summary = score_round(db_session, triggered_by="test")
    dstat = summary["directions"][0]
    assert dstat["budget_slow"] is True
    assert len(scored_ids) == 20  # 轮上限降为慢速档（默认 20）
    # 继续低速不绝停：下一轮幂等续跑剩余 10 条
    score_round(db_session, triggered_by="test")
    assert len(scored_ids) == 30


def test_budget_4_write_requires_confirmation(db_session, monkeypatch):
    from app.pipeline.runner import write_task

    from app.models import Author

    _trigger_budget(db_session)
    a = Author(name="作者", model="m")
    db_session.add(a)
    db_session.commit()

    def must_not_run(db, author, **kw):
        raise AssertionError("预算未确认时写作不得执行 LLM")

    monkeypatch.setattr("app.authors.writer.run_write", must_not_run)
    out = write_task(db_session, a.id, triggered_by="test")
    assert out["budget_confirmation_required"] is True
    assert out["executed"] is False
    task = db_session.get(PipelineTask, out["task_id"])
    assert task.payload["budget_confirmation_required"] is True

    # 站长确认后手动执行：照常写作
    class _Run:
        status = "OK"
        decision = "WRITE"
        article_id = None
        error = None
        id = 1

    monkeypatch.setattr("app.authors.writer.run_write",
                        lambda db, author, **kw: _Run())
    out2 = write_task(db_session, a.id, triggered_by="test", budget_confirmed=True)
    assert out2.get("budget_confirmation_required", False) is False
    assert out2["status"] == "DONE"


def test_budget_exhausted_fetch_and_presentation_unaffected(db_session, auth_client,
                                                            monkeypatch):
    d, _ = _seed_direction(db_session)
    _trigger_budget(db_session)

    def fake_fetch(db, src):
        return _stats(source_id=src.id, url=src.url)

    monkeypatch.setattr(runner_mod, "_fetch_one", fake_fetch)
    round_task = enqueue_fetch_round(db_session, triggered_by="test")
    summary = process_fetch_round(db_session, round_task)
    assert summary["status"] == "DONE"  # 采集零降级
    r = auth_client.get("/stream/b", params={"direction_id": d.id})
    assert r.status_code == 200  # 呈现零降级
    r2 = auth_client.get("/items")
    assert r2.status_code == 200


# ---------- AC-21.4：恢复自愈与补打顺序 ----------


def test_failed_items_backfilled_hit_bucket_first(db_session, monkeypatch):
    d, items = _seed_direction(db_session, n_items=2)
    from app.siteconfig import set_config as sc

    sc(db_session, "retrieval_top_k", 1)
    d.query_vec = vec_to_blob(np.eye(8, dtype=np.float32)[0])
    d.query_vec_version = d.prompt_version
    hit, miss = items
    db_session.add(ItemVec(item_id=hit.id, model_version="mv",
                           vec=vec_to_blob(np.eye(8, dtype=np.float32)[0])))
    db_session.add(ItemVec(item_id=miss.id, model_version="mv",
                           vec=vec_to_blob(np.eye(8, dtype=np.float32)[1])))
    # 上一轮双双 FAILED（无 OK 行）：下轮应自动补打
    db_session.add(ScoreResult(item_id=hit.id, direction_id=d.id, model="m",
                               status="FAILED", error="LLM down"))
    db_session.add(ScoreResult(item_id=miss.id, direction_id=d.id, model="m",
                               status="FAILED", error="LLM down"))
    db_session.commit()
    order = []

    def fake_score(db, item, direction):
        order.append(item.id)
        return ScoreResult(item_id=item.id, direction_id=direction.id, model="m",
                           status="OK", passed=True, relevance_score=80,
                           quality_score=80, band="high")

    monkeypatch.setattr("app.scoring.service.score_item", fake_score)
    summary = score_round(db_session, triggered_by="test")
    assert summary["directions"][0]["scored"] == 2  # FAILED 全部自动补打
    assert order == [hit.id, miss.id]  # 命中检索的条目先补


# ---------- 双线程池隔离 ----------


def test_value_pool_score_blocking_does_not_delay_fetch(monkeypatch, db_session):
    """score 的 LLM 长阻塞不推迟下一轮 fetch 触发：fetch 线程立即返回，
    score 在增值线程池中异步执行。"""
    import app.scheduler as sched

    release = threading.Event()
    state = {"fetch": 0, "score": 0, "threads": []}

    def fake_enqueue(db, *, triggered_by="scheduler"):
        state["fetch"] += 1
        return types.SimpleNamespace(id=999)

    def fake_process(db, task):
        return {"sources": [], "status": "DONE"}

    def fake_score_round(db, *, triggered_by="scheduler", **kw):
        state["threads"].append(threading.current_thread().name)
        state["score"] += 1
        release.wait(timeout=5)  # 模拟 LLM 长阻塞
        return {"directions": []}

    monkeypatch.setattr("app.pipeline.runner.enqueue_fetch_round", fake_enqueue)
    monkeypatch.setattr("app.pipeline.runner.process_fetch_round", fake_process)
    monkeypatch.setattr("app.pipeline.runner.score_round", fake_score_round)

    sched._tick_fetch()  # 应立即返回（不等 score 完成）
    assert state["fetch"] == 1
    # score 阻塞期间下一轮 fetch 照常触发
    sched._tick_fetch()
    assert state["fetch"] == 2
    release.set()
    # 增值池串行 FIFO：提交哨兵任务等待前面的打分全部完成
    done = threading.Event()
    sched.value_pool.submit(done.set)
    assert done.wait(timeout=5)
    assert state["score"] == 2
    assert all("value" in t for t in state["threads"])
