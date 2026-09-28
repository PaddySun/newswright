"""定时调度（能力①，morningdeck FeedSchedulerJob 模式 + BettaFish 无调度的反面教训）。

纪律：
- 调度与执行分离：APScheduler 只负责到点调 tick_*；tick 里先把轮次任务置 PENDING
  （enqueue_*），再走 process_* worker 路径执行——任务状态一律经 pipeline_task 落库。
- 防重叠：同一 kind 上一轮 RUNNING/PENDING 未清空时不置新轮（查库判定，不引入分布式锁）。
- 退避：连续失败 ≥3 次的源跳过并计数，每 4 轮放行一次探测（runner.enqueue_fetch_round）。
- score 紧跟 fetch（同一 job 链）；hot 独立周期。写作不进调度（另一台机器实验中）。
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import config
from .db import SessionLocal

log = logging.getLogger("newswright.scheduler")

scheduler = BackgroundScheduler(timezone="UTC")
_started = False


def _tick_fetch() -> None:
    """fetch 轮：入队 → 执行 → 紧跟 score 轮。单实例 max_instances=1 + 轮次防重叠双保险。"""
    from .pipeline.runner import (
        enqueue_fetch_round,
        process_fetch_round,
        round_busy,
        score_round,
    )

    with SessionLocal() as db:
        round_task = enqueue_fetch_round(db, triggered_by="scheduler")
        if round_task is None:
            log.info("上一轮 fetch_round 未结束，本轮跳过（防重叠）")
            return
        summary = process_fetch_round(db, round_task)
        log.info("fetch_round #%s %s（%d 源）", round_task.id, summary.get("status"),
                 len(summary.get("sources") or []))
        if round_busy(db, "score"):
            log.info("上一轮 score 未结束，本轮打分跳过（防重叠）")
            return
        score = score_round(db, triggered_by="scheduler")
        for d in score.get("directions") or []:
            log.info("score 方向[%s] %s 打分=%s", d.get("name"), d.get("status"), d.get("scored"))


def _tick_hot() -> None:
    """hot 轮：热榜聚合 + 关键词提炼（M10 实装；此前仅记日志不产生任务）。"""
    try:
        from .hot.service import run_hot_round  # noqa: F401  M10 提供
    except ImportError:
        log.info("hot 通道未实装（M10），本轮跳过")
        return
    with SessionLocal() as db:
        run_hot_round(db, triggered_by="scheduler")


def start() -> None:
    """注册 job 并启动。重复调用安全（幂等）。"""
    global _started
    if _started:
        return
    scheduler.add_job(
        run_job_safely, args=[_tick_fetch],
        trigger=IntervalTrigger(minutes=config.SCHED_FETCH_MINUTES),
        id="fetch_score_round", max_instances=1, coalesce=True,
        next_run_time=datetime.now(timezone.utc),  # 启动即跑第一轮
    )
    scheduler.add_job(
        run_job_safely, args=[_tick_hot],
        trigger=IntervalTrigger(minutes=config.SCHED_HOT_MINUTES),
        id="hot_round", max_instances=1, coalesce=True,
    )
    scheduler.start()
    _started = True
    log.info("调度器已启动：fetch+%dmin（含 score 链）、hot+%dmin",
             config.SCHED_FETCH_MINUTES, config.SCHED_HOT_MINUTES)


def shutdown() -> None:
    global _started
    if _started:
        scheduler.shutdown(wait=False)
        _started = False


def status() -> dict:
    """调度器状态 + 最近轮次（GET /scheduler/status 用）。"""
    jobs = []
    if _started:
        for j in scheduler.get_jobs():
            jobs.append({
                "id": j.id, "next_run_at": str(j.next_run_time),
                "trigger": str(j.trigger),
            })
    return {
        "running": _started,
        "jobs": jobs,
        "intervals": {"fetch_minutes": config.SCHED_FETCH_MINUTES,
                      "hot_minutes": config.SCHED_HOT_MINUTES},
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def run_job_safely(fn) -> None:
    """job 包装：异常全量落日志，绝不杀调度器线程。"""
    try:
        fn()
    except Exception:  # noqa: BLE001
        log.error("调度 tick 异常:\n%s", traceback.format_exc())
