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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import config
from .db import SessionLocal

log = logging.getLogger("newswright.scheduler")

scheduler = BackgroundScheduler(timezone="UTC")
_started = False

# 增值功能线程池（与采集线程隔离）：fetch 轮完成后把 score 链提交到此池异步执行，
# fetch 线程立即返回——打分 LLM 长阻塞不占用抓取并发。max_workers=1 串行化增值
# 轮次，与 round_busy 防重叠构成双保险。采集与呈现不在此池，永不因增值层排队降级。
value_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="newswright-value")


def _submit_score_async() -> None:
    """把打分轮提交增值线程池（自带会话；防重叠在提交前后双重检查）。"""

    def _run() -> None:
        from .pipeline.runner import round_busy, score_round

        try:
            with SessionLocal() as db:
                if round_busy(db, "score"):
                    log.info("上一轮 score 未结束，异步打分跳过（防重叠）")
                    return
                score = score_round(db, triggered_by="scheduler")
                for d in score.get("directions") or []:
                    log.info("score 方向[%s] %s 打分=%s",
                             d.get("name"), d.get("status"), d.get("scored"))
        except Exception:  # noqa: BLE001  增值层异常绝不冒泡伤及采集线程
            log.error("异步打分轮异常:\n%s", traceback.format_exc())

    value_pool.submit(_run)


def submit_write_tasks_async() -> None:
    """把 PENDING write 任务消化提交增值线程池（自带会话）。

    异步写作消费主路径：API 端点建任务后即时提交（不等待周期 tick）；
    周期 tick（_tick_write_consume）作兜底消化遗留任务（创建后进程重启等场景）。
    与打分轮同池串行——增值轮次串行化纪律（max_workers=1）。"""

    def _run() -> None:
        from .pipeline.runner import process_write_tasks

        try:
            with SessionLocal() as db:
                consumed = process_write_tasks(db)
                for t in consumed:
                    log.info("write 任务[%s] %s", t.get("task_id"), t.get("status"))
        except Exception:  # noqa: BLE001  增值层异常绝不冒泡伤及采集线程
            log.error("异步 write 任务消化异常:\n%s", traceback.format_exc())

    value_pool.submit(_run)


def _tick_write_consume() -> None:
    """周期兜底：消化遗留 PENDING write 任务（正常路径由 API 端点即时提交）。"""
    submit_write_tasks_async()


def _tick_fetch() -> None:
    """fetch 轮：入队 → 执行 → score 链提交增值线程池异步执行（fetch 线程立即返回）。

    单实例 max_instances=1 + 轮次防重叠双保险；提交前 round_busy 预检避免无效排队。
    """
    from .pipeline.runner import (
        enqueue_fetch_round,
        process_fetch_round,
        round_busy,
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
    _submit_score_async()


def _tick_hot() -> None:
    """hot 轮：热榜聚合 + 关键词提炼（M10 实装；此前仅记日志不产生任务）。"""
    try:
        from .hot.service import run_hot_round  # noqa: F401  M10 提供
    except ImportError:
        log.info("hot 通道未实装（M10），本轮跳过")
        return
    with SessionLocal() as db:
        run_hot_round(db, triggered_by="scheduler")


def _tick_backup() -> None:
    """每日备份：本地目录插件执行一次 SQLite 在线备份（失败 WARN 不阻断任何轮）。"""
    try:
        from .backup import default_backup_target

        with SessionLocal() as db:
            target = default_backup_target(db)
            if target is None:
                log.info("无已注册备份目标，本轮跳过")
                return
            path = target.run_backup()
            log.info("每日备份完成: %s", path)
    except Exception:  # noqa: BLE001  备份失败 WARN + 任务可恢复
        log.warning("每日备份异常（下轮重试，不阻断其他轮次）:\n%s",
                    traceback.format_exc())


def _reclaim_once() -> None:
    """P0-1 僵死回收（AC-20.2）：start() 首个 tick 前执行一次——调度器重启后
    首次 tick 即回收跨重启残留的 RUNNING 任务，fetch 轮次不被永久阻塞。"""
    from .pipeline.runner import reclaim_stale_tasks

    with SessionLocal() as db:
        n = reclaim_stale_tasks(db)
        if n:
            log.info("启动回收：%d 个僵死任务置 FAILED", n)


def start() -> None:
    """注册 job 并启动。重复调用安全（幂等）。"""
    global _started
    if _started:
        return
    _reclaim_once()  # P0-1：首个 tick 前回收一次
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
    scheduler.add_job(
        run_job_safely, args=[_tick_backup],
        trigger=IntervalTrigger(hours=24),
        id="daily_backup", max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        run_job_safely, args=[_tick_write_consume],
        trigger=IntervalTrigger(minutes=1),
        id="write_consume", max_instances=1, coalesce=True,
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
    """job 包装：每次执行前先跑一次 P0-1 僵死回收（覆盖 run-once/score 等非调度任务）；
    异常全量落日志，绝不杀调度器线程。"""
    try:
        from .pipeline.runner import reclaim_stale_tasks

        with SessionLocal() as db:
            reclaim_stale_tasks(db)
        fn()
    except Exception:  # noqa: BLE001
        log.error("调度 tick 异常:\n%s", traceback.format_exc())
