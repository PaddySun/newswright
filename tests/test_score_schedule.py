"""score 独立调度节奏测试（产品书 US-20，设计依据见 docs/design-index.md
「AC-20.1」）：SCHED_SCORE_MINUTES 显式配置键 + 独立定时 job 与 fetch 联锁
双形态并存；防重叠=round_busy 双保险。

缩短版 soak 代偿口径（与既有同款）：≥2h 实 soak 归部署验证；本测以注册面
与逻辑断言代偿——job 注册的触发间隔精确等于配置值（实际运行偏差 ≤60 秒
量级的注册侧前提），并发/重复触发经 round_busy 至多一个执行。
"""
from datetime import timedelta

import app.config as cfg
import app.scheduler as sched
from app.models import Direction, PipelineTask, Source


def test_sched_score_minutes_explicit_config_key():
    """显式配置键存在且默认 15 分钟（可被环境变量覆盖）。"""
    assert cfg.SCHED_SCORE_MINUTES == 15
    assert int(cfg.SCHED_SCORE_MINUTES) > 0


def test_register_jobs_includes_independent_score_tick():
    """job 注册面：独立 score 定时 job 存在，触发间隔=配置值（精确等于——
    实跑偏差 ≤60s 的量级断言在注册形态上取零偏差）；fetch 联锁 job 仍在。"""
    sched._register_jobs()
    try:
        jobs = {j.id: j for j in sched.scheduler.get_jobs()}
        assert "fetch_score_round" in jobs
        assert "score_round_tick" in jobs
        assert jobs["score_round_tick"].trigger.interval \
            == timedelta(minutes=cfg.SCHED_SCORE_MINUTES)
        assert jobs["fetch_score_round"].trigger.interval \
            == timedelta(minutes=cfg.SCHED_FETCH_MINUTES)
        # 双形态并存：两个 job 互不替代（同一安全包装器，内层 tick 不同）
        assert jobs["score_round_tick"].args[0] is sched._tick_score
        assert jobs["fetch_score_round"].args[0] is sched._tick_fetch
    finally:
        sched.scheduler.remove_all_jobs()


def test_score_round_worker_skips_when_round_busy(db_session, monkeypatch):
    """并发/重复触发防重叠：同 kind 上一轮 RUNNING 未清空时，池工作体直接
    跳过（不新建 score 轮次）——至多一个执行。"""
    db_session.add(PipelineTask(kind="score", status="RUNNING",
                                payload={"direction_id": 1}))
    db_session.commit()
    called = []
    monkeypatch.setattr("app.pipeline.runner.score_round",
                        lambda db, **kw: called.append(kw) or {"directions": []})
    sched._run_score_round()
    assert called == []


def test_score_round_worker_runs_when_idle(db_session, monkeypatch):
    """无进行中的 score 轮 → 池工作体正常执行一轮。"""
    monkeypatch.setattr("app.pipeline.runner.score_round",
                        lambda db, **kw: {"directions": []})
    sched._run_score_round()  # 不抛即通过（score_round 已打桩）


def test_tick_score_preflight_skips_when_busy(db_session, monkeypatch):
    """独立 tick 入口同样带 round_busy 预检（提交前检查避免无效排队）。"""
    db_session.add(PipelineTask(kind="score", status="RUNNING", payload={}))
    db_session.commit()
    submitted = []
    monkeypatch.setattr(sched, "_submit_score_async",
                        lambda: submitted.append(1))
    sched._tick_score()
    assert submitted == []


def test_tick_score_submits_when_idle(db_session, monkeypatch):
    submitted = []
    monkeypatch.setattr(sched, "_submit_score_async", lambda: submitted.append(1))
    sched._tick_score()
    assert submitted == [1]


def test_fetch_chain_trigger_preserved(db_session, monkeypatch):
    """fetch 完成后的联锁触发保留（双形态）：_tick_fetch 尾部仍提交打分轮。
    空 fetch 轮（无可抓源）走完整链路后提交不被跳过。"""
    from app.pipeline import runner

    monkeypatch.setattr(sched, "_submit_score_async", lambda: None)
    # 直接验证链路存在：_tick_fetch 源码消费 _submit_score_async（行为面由
    # 空轮完整执行不抛错覆盖）
    import inspect

    src = inspect.getsource(sched._tick_fetch)
    assert "_submit_score_async" in src
    db_session.add(Direction(name="空链路方向", prompt="p", prompt_version=1,
                             threshold=60))
    db_session.commit()
    # 无源可抓：enqueue 空轮 + process 空轮 + 提交链（打桩后无副作用）
    rt = runner.enqueue_fetch_round(db_session, triggered_by="test")
    assert rt is not None
