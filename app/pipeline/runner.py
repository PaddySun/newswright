"""全链路编排：任务状态一律经 pipeline_task 落库（DB 即队列雏形），禁止只在内存。

fetch round：每个启用源一个 kind=fetch 任务；score/write 随 M4/M5 扩展。
调度（能力①，M8）：调度器只负责把轮次任务置 PENDING，执行走 process_fetch_round 的
worker 路径——调度与执行分离；防重叠查 RUNNING 轮次任务，退避看 Source.backoff_*。
P0-1（G1）：僵死 RUNNING 任务按 kind 分档回收；全部终态迁移 CAS 化（迟到完成写拒绝）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from .. import config
from ..models import Direction, PipelineTask, Source
from ..ingest.rss import fetch_source
from ..ingest.web import fetch_web_source
from ..models import Item

log = logging.getLogger("newswright.pipeline")

ROUND_KINDS = ("fetch_round", "hot_round")

# P0-1 僵死回收阈值（分钟，按 kind 分档，一处定义）：技术书 §4.2 状态机注记
# "超 30/60/120min（rescore 并入 score=60min）"。hot_round 统筹解释：hot 属采集型，
# 按 30 分钟档（与 fetch 同类）。阈值取宽不取严：回收只兜进程中断，正常慢轮次不误伤。
RECLAIM_STALE_MINUTES: dict[str, int] = {
    "fetch": 30,
    "fetch_round": 30,
    "hot_round": 30,
    "score": 60,
    "rescore": 60,
    "write": 120,
}


def _grouped_thresholds() -> dict[int, list[str]]:
    """按阈值分档（同档一次批式 UPDATE）。"""
    grouped: dict[int, list[str]] = {}
    for kind, minutes in RECLAIM_STALE_MINUTES.items():
        grouped.setdefault(minutes, []).append(kind)
    return grouped


def reclaim_stale_tasks(db: Session, *, now: datetime | None = None) -> int:
    """P0-1 僵死任务回收（AC-20.2）：单进程设计下，跨重启仍 RUNNING 的任务必然僵死
    （morningdeck 118 条 stuck 同款疾病的唯一调度死锁路径）。

    执行形态 = 按档分组的批式 CAS：UPDATE ... WHERE status='RUNNING' AND
    updated_at < cutoff，命中行置 FAILED + last_error=stale_reclaim + attempts+1。
    迟到完成写被 CAS 拒绝（见 _finish）。挂载点：scheduler.start() 首个 tick 前 +
    run_job_safely 每次执行前。返回回收数并 INFO 日志。
    """
    now = now or datetime.now(timezone.utc)
    reclaimed = 0
    for minutes, kinds in _grouped_thresholds().items():
        cutoff = now - timedelta(minutes=minutes)
        res = db.execute(
            update(PipelineTask)
            .where(PipelineTask.kind.in_(kinds), PipelineTask.status == "RUNNING",
                   PipelineTask.updated_at < cutoff)
            .values(status="FAILED", attempts=PipelineTask.attempts + 1,
                    last_error=f"stale_reclaim: RUNNING 超 {minutes} 分钟（疑似进程中断）",
                    updated_at=now)
            .execution_options(synchronize_session=False)
        )
        reclaimed += res.rowcount
    db.commit()
    if reclaimed:
        log.info("P0-1 僵死回收：%d 个 RUNNING 任务置 FAILED（stale_reclaim）", reclaimed)
    return reclaimed


def _new_task(db: Session, *, kind: str, payload: dict) -> PipelineTask:
    t = PipelineTask(kind=kind, status="PENDING", payload=payload)
    db.add(t)
    db.commit()
    # 日志上下文注入点：任务创建即把 task_id/call_point 写入 contextvars
    # （结构化日志 Filter 统一注入，业务 log 调用不手工拼字段）
    from ..logging_setup import set_log_context

    set_log_context(task_id=t.id, call_point=kind)
    return t


def _claim(db: Session, task: PipelineTask) -> bool:
    """PENDING→RUNNING 原子抢占；已被其他 worker 抢走则返回 False。"""
    res = db.execute(
        update(PipelineTask)
        .where(PipelineTask.id == task.id, PipelineTask.status == "PENDING")
        .values(status="RUNNING", attempts=PipelineTask.attempts + 1,
                updated_at=datetime.now(timezone.utc))
    )
    db.commit()
    return res.rowcount > 0


def _finish(db: Session, task: PipelineTask, *, status: str, stats: dict | None = None,
            error: str | None = None, payload_extra: dict | None = None) -> None:
    """CAS 收尾（AC-20.2/P0-1）：UPDATE ... SET status/payload/last_error
    WHERE id=? AND status='RUNNING'。

    rowcount=0 → 迟到完成（任务已被回收或被其他路径终结）：WARN 日志后静默丢弃、
    不抛异常（技术书 §4.2 note："回收后迟到的完成写不进去"——防线程挂死场景状态穿透）。
    内存对象同步赋值，调用方读 task.status/payload 不失真。
    stats 并入 payload.stats（DT-5 口径）；payload_extra 为顶层键合并（write_task 用）。
    """
    values: dict = {"status": status, "updated_at": datetime.now(timezone.utc)}
    if payload_extra:
        values["payload"] = {**task.payload, **payload_extra}
    if stats:
        values["payload"] = {**values.get("payload", task.payload), "stats": stats}
    if error:
        values["last_error"] = error[:2000]
    res = db.execute(
        update(PipelineTask)
        .where(PipelineTask.id == task.id, PipelineTask.status == "RUNNING")
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    from ..logging_setup import set_log_context

    set_log_context(task_id=None, call_point=None)  # 任务终态：清空认领上下文
    task.status = status
    if "payload" in values:
        task.payload = values["payload"]
    if error:
        task.last_error = values["last_error"]
    if res.rowcount == 0:
        log.warning("迟到完成被拒 task=%s target=%s（已非 RUNNING，疑似被 stale_reclaim 回收）",
                    task.id, status)


def _fetchable_sources(db: Session) -> list[Source]:
    """本轮可抓取的源：源自身启用，且所属方向处于 active 生命周期。

    非 active 方向（disabled/expired/deleted）的源不再进入采集调度——方向级
    开关是源的上级闸门（数据全保留，只是不再抓取）。
    """
    return (
        db.query(Source)
        .join(Direction, Source.direction_id == Direction.id)
        .filter(Source.enabled.is_(True), Direction.status == Direction.STATUS_ACTIVE)
        .all()
    )


def expire_due_temp_directions(db: Session, *, now: datetime | None = None) -> int:
    """临时方向 TTL 到期扫描：expires_at 已过且仍为 active 的 temp 方向翻为 expired。

    懒扫描形态：每次采集入队与方向列表读取前执行一次，无需独立定时器。
    历史数据全保留（设计依据见 docs/design-index.md「AC-03.4」）。返回翻转数。
    """
    now = now or datetime.now(timezone.utc)
    rows = (
        db.query(Direction)
        .filter(Direction.temp.is_(True), Direction.status == Direction.STATUS_ACTIVE,
                Direction.expires_at.isnot(None), Direction.expires_at <= now)
        .all()
    )
    for d in rows:
        d.apply_status(Direction.STATUS_EXPIRED)
    if rows:
        db.commit()
    return len(rows)


def fetch_round(db: Session, *, triggered_by: str = "manual") -> dict:
    """抓一轮全部启用源。返回逐源统计；任何源失败不中断其他源。"""
    expire_due_temp_directions(db)
    sources = _fetchable_sources(db)
    summary: dict[str, object] = {"triggered_by": triggered_by, "sources": []}
    for src in sources:
        task = _new_task(db, kind="fetch", payload={"source_id": src.id, "url": src.url})
        task.status = "RUNNING"
        task.attempts += 1
        db.commit()
        try:
            stats = _fetch_one(db, src)
            status = "FAILED" if stats.error else "DONE"
            _finish(db, task, status=status,
                    stats=_fetch_stats_dict(stats), error=stats.error)
            _update_source_health(db, src, stats)
        except Exception as e:  # noqa: BLE001
            # P1-1：先回滚再落终态——异常可能源自会话损坏（rollback-only 状态），
            # 不回滚则 _finish 的 commit 也会失败 → 任务卡 RUNNING → 只能靠 P0-1 兜底
            db.rollback()
            _finish(db, task, status="FAILED", error=f"{type(e).__name__}: {e}")
            _update_source_health(db, src, _error_stats(f"{type(e).__name__}: {e}"))
        summary["sources"].append({
            "source_id": src.id,
            "url": src.url,
            "task_id": task.id,
            "status": task.status,
            **(task.payload.get("stats") or {}),
            "error": task.last_error,
        })
    return summary


def _fetch_one(db: Session, src: Source):
    """按源类型分发抓取器（provider 接口化：新源类型加分支即可）。"""
    if src.type == "web":
        return fetch_web_source(db, src)
    if src.type == "search":
        from ..search.pipeline import fetch_search_source

        return fetch_search_source(db, src)
    return fetch_source(db, src)


def _fetch_stats_dict(stats) -> dict:
    return {
        "feed_entries": stats.feed_entries,
        "inserted": stats.inserted,
        "dup_blocked": stats.dup_blocked,
        "rule_rejected": stats.rule_rejected,
        "failed": stats.failed,
        "archived": getattr(stats, "archived", 0),
        "guid_collisions": stats.guid_collisions,
        "not_modified": stats.not_modified,
        "sanitize_passed": stats.sanitize_passed,
        "sanitize_rejected": stats.sanitize_rejected,
        **(getattr(stats, "extra", {}) or {}),
    }


def _error_stats(error: str):
    """异常路径的最小抓取统计（无 stats 可用时）：按一次错误轮参与健康状态机。"""
    from types import SimpleNamespace

    return SimpleNamespace(error=error, feed_entries=0, inserted=0, not_modified=False,
                           rate_limited=False, retry_after=None, extra={})


def _update_source_health(db: Session, src: Source, stats) -> None:
    """采集后源健康状态更新（单一入口，替代仅记退避的旧计数）：

    - 失效三级判别：连续硬失效（404/403/410）→ hard_failed 停抓；连续 200 空内容
      （含 200+非 XML 挑战页，走空轮侧计数）→ suspect 低频探测；304/非空轮清零；
      源声明休息日（skipDays）期间的空轮不计入（豁免写进判据本体）。
    - 通用退避计数：网络/其他错误仅记连续失败（不标失效），成功清零。
    - 动态降频（D13）：429/Retry-After 命中档位+1 并记录 until（Retry-After 双形态
      解析，失败退档位缺省间隔）；降频期满后连续 2 轮正常逐级降档恢复。
    - 关键词边际降频（D20）：搜索源连续零新增轮计数，达阈值进入同构阶梯；
      有新增即清零解限（恢复事件另有 hot 批次更新/手工刷新/提示词升版三个入口）。
    """
    now = datetime.now(timezone.utc)
    extra = getattr(stats, "extra", {}) or {}
    error = stats.error
    http_status = extra.get("http_status")
    skip_day = bool(extra.get("skip_day"))
    not_modified = bool(stats.not_modified)
    entries = stats.feed_entries or 0
    inserted = stats.inserted or 0
    non_xml = bool(error) and error.startswith("non_xml_response")

    # --- 失效三级判别（RSS 空轮侧）+ 清零语义 ---
    if not_modified or (error is None and entries > 0):
        # 任何一轮非空或 not_modified：空轮/硬失效计数清零，suspect 探测恢复
        src.empty_rounds = 0
        src.hard_failures = 0
        if src.failure_level == "suspect":
            src.failure_level = "none"
            src.failure_since = None
    elif non_xml or (error is None and entries == 0 and src.type == "rss"):
        # 200 但内容空/条目归零/挑战页：空轮侧计数；源声明休息日豁免
        if not skip_day:
            src.empty_rounds = (src.empty_rounds or 0) + 1
            if (src.empty_rounds >= config.SUSPECT_EMPTY_ROUNDS
                    and src.failure_level == "none"):
                src.failure_level = "suspect"
                src.failure_since = now
                # 通知挂钧：疑似失效转换点（同源 24h 去重）
                from ..notify.triggers import notify_source_failure

                notify_source_failure(db, src, level="suspect")

    # --- 硬失效判别（404/403/410）---
    if error is not None and not non_xml:
        if http_status in (404, 403, 410):
            src.hard_failures = (src.hard_failures or 0) + 1
            src.last_error = error[:2000]
            if src.hard_failures >= config.HARD_FAIL_ROUNDS and src.failure_level != "hard_failed":
                src.failure_level = "hard_failed"
                src.failure_since = now
                # 通知挂钧：源失效状态转换点（SMTP 未配置时仅落日志，不报错）
                from ..notify.triggers import notify_source_failure

                notify_source_failure(db, src, level="hard_failed")
        else:
            src.hard_failures = 0  # 非硬失效错误打断连续硬失效序列
            src.last_error = error[:2000]

    # --- 动态降频（D13）---
    from ..ingest.rss import parse_retry_after
    from .skip_policy import rate_limit_minutes

    if getattr(stats, "rate_limited", False):
        # 限流信号：不计成功也不计失败退避，档位+1 并记录 until
        src.rate_level = (src.rate_level or 0) + 1
        src.rate_ok_rounds = 0
        seconds = parse_retry_after(getattr(stats, "retry_after", None), now=now)
        if seconds is not None:
            src.rate_limited_until = now + timedelta(seconds=seconds)
        else:
            src.rate_limited_until = now + timedelta(minutes=rate_limit_minutes(src.rate_level))
    elif src.rate_limited_until is not None and error is None:
        until = src.rate_limited_until if src.rate_limited_until.tzinfo else src.rate_limited_until.replace(tzinfo=timezone.utc)
        if now >= until:
            # 降频期满后的正常轮：连续 2 轮正常逐级降档（全 0 档解除）
            src.rate_ok_rounds = (src.rate_ok_rounds or 0) + 1
            if src.rate_ok_rounds >= 2:
                src.rate_level = max(0, (src.rate_level or 0) - 1)
                src.rate_ok_rounds = 0
                if src.rate_level == 0:
                    src.rate_limited_until = None
                else:
                    src.rate_limited_until = now + timedelta(
                        minutes=rate_limit_minutes(src.rate_level))

    # --- 通用退避计数（网络/其他错误；429 轮不参与）---
    if error is not None and not non_xml and not getattr(stats, "rate_limited", False):
        src.backoff_failures = (src.backoff_failures or 0) + 1
    elif (error is None and not getattr(stats, "rate_limited", False)
          and not (src.failure_level == "suspect" and entries == 0)):
        # 成功清零；suspect 探测仍空的轮次不算成功（探测节奏不被重置）
        src.backoff_failures = 0
        src.backoff_skips = 0

    # --- 关键词边际降频（D20，仅搜索源）---
    if src.type == "search" and not getattr(stats, "rate_limited", False):
        quota_blocked = bool(extra.get("quota_blocked"))
        if not quota_blocked and error is None:
            if inserted == 0:
                src.keyword_zero_rounds = (src.keyword_zero_rounds or 0) + 1
                if src.keyword_zero_rounds >= config.KEYWORD_EXHAUSTED_ROUNDS:
                    # 第 6 轮零新增进 1 档（30 分钟），此后每多一轮零新增升 1 档
                    src.keyword_rate_level = (src.keyword_zero_rounds
                                              - config.KEYWORD_EXHAUSTED_ROUNDS + 1)
                    src.keyword_limited_until = now + timedelta(
                        minutes=rate_limit_minutes(src.keyword_rate_level))
            else:
                # 有新增：零收益计数清零并解除限速（事实恢复）
                src.keyword_zero_rounds = 0
                src.keyword_rate_level = 0
                src.keyword_limited_until = None

    db.commit()


# ---------- 调度路径（能力①）：入队 PENDING → worker 执行，调度与执行分离 ----------


def round_busy(db: Session, kind: str) -> bool:
    """防重叠：同 kind 上一轮 RUNNING/PENDING 未清空时不置新轮。"""
    return (
        db.query(PipelineTask.id)
        .filter(PipelineTask.kind == kind, PipelineTask.status.in_(("RUNNING", "PENDING")))
        .first()
        is not None
    )


def enqueue_fetch_round(db: Session, *, triggered_by: str = "scheduler") -> PipelineTask | None:
    """把一轮抓取置为 PENDING 轮次任务 + 逐源 PENDING 任务。

    跳过判定统一走 skip_reason（单一优先级表：disabled > direction_expired >
    rate_limited > keyword_exhausted > hard_failed/suspect_probe > backoff >
    interval_not_due），跳过原因与探测窗口计数都在此推进。
    """
    from .skip_policy import skip_reason

    if round_busy(db, "fetch_round"):
        return None
    skipped: list[dict] = []
    round_task = _new_task(db, kind="fetch_round", payload={"triggered_by": triggered_by})
    now = datetime.now(timezone.utc)
    expire_due_temp_directions(db, now=now)
    directions = {d.id: d for d in db.query(Direction).all()}
    for src in _fetchable_sources(db):
        reason = skip_reason(src, directions.get(src.direction_id), now=now)
        if reason == "probe":
            # 退避/疑似失效状态的探测窗口：放行抓取并推进探测轮计数
            src.backoff_skips = (src.backoff_skips or 0) + 1
            db.commit()
            log.info("源 %s 处于 %s 状态，本轮放行探测",
                     src.id, src.failure_level or "backoff")
        elif reason == "interval_not_due":
            interval = (src.source_config or {}).get("interval_minutes")
            skipped.append({"source_id": src.id, "url": src.url,
                            "reason": f"interval_not_due:{interval}m"})
            continue
        elif reason in ("backoff", "suspect_probe"):
            # 状态内跳过轮：推进探测轮计数（探测节奏按每 N 轮一次维持）
            src.backoff_skips = (src.backoff_skips or 0) + 1
            db.commit()
            entry = {"source_id": src.id, "url": src.url, "reason": reason,
                     "skips": src.backoff_skips}
            if reason == "backoff":
                entry["consecutive_failures"] = src.backoff_failures
            skipped.append(entry)
            continue
        elif reason is not None:
            skipped.append({"source_id": src.id, "url": src.url, "reason": reason})
            continue
        _new_task(db, kind="fetch", payload={"source_id": src.id, "url": src.url,
                                             "round_task_id": round_task.id})
    round_task.payload = {**round_task.payload, "skipped_backoff": skipped}
    db.commit()
    return round_task


def process_fetch_round(db: Session, round_task: PipelineTask) -> dict:
    """执行轮次任务下的全部 PENDING fetch 任务（worker 路径，逐源认领）。"""
    if not _claim(db, round_task):
        return {"round_task_id": round_task.id, "status": round_task.status, "skipped": True}
    # SQLite JSON 路径查询兼容性差，轮内任务用 payload.round_task_id 在 Python 侧过滤
    source_tasks = [
        t for t in db.query(PipelineTask)
        .filter(PipelineTask.kind == "fetch", PipelineTask.status == "PENDING")
        .all()
        if (t.payload or {}).get("round_task_id") == round_task.id
    ]
    summary = {"round_task_id": round_task.id, "sources": []}
    any_failed = False
    for t in source_tasks:
        if not _claim(db, t):
            continue
        src = db.get(Source, t.payload["source_id"])
        if src is None:
            _finish(db, t, status="FAILED", error="source 不存在")
            any_failed = True
            continue
        try:
            stats = _fetch_one(db, src)
            status = "FAILED" if stats.error else "DONE"
            _finish(db, t, status=status, stats=_fetch_stats_dict(stats), error=stats.error)
            _update_source_health(db, src, stats)
            any_failed = any_failed or bool(stats.error)
        except Exception as e:  # noqa: BLE001
            db.rollback()  # P1-1：先回滚再落终态（动机见 fetch_round 同款注释）
            _finish(db, t, status="FAILED", error=f"{type(e).__name__}: {e}")
            _update_source_health(db, src, _error_stats(f"{type(e).__name__}: {e}"))
            any_failed = True
        summary["sources"].append({
            "source_id": src.id, "task_id": t.id, "status": t.status,
            **(t.payload.get("stats") or {}), "error": t.last_error,
        })
    _finish(db, round_task, status="FAILED" if any_failed else "DONE")
    summary["status"] = round_task.status
    # fetch 轮末顺带检查：采集面聚合哨兵（持续 2 轮超半数降级）与磁盘阈值
    try:
        from ..notify.triggers import check_collective_sentinel, check_disk_usage

        summary["sentinel"] = check_collective_sentinel(db)
        summary["disk"] = check_disk_usage(db)
    except Exception as e:  # noqa: BLE001  通知面异常绝不阻断采集轮收尾
        log.warning("fetch 轮末通知检查异常: %s", e)
    return summary


def _rescore_candidate_ids(db: Session, direction: Direction, scope: str) -> list[int]:
    """重打分候选条目 id（升序，批次切分稳定）。

    scope=all：已有 OK 打分行、但尚无「当前 prompt_version 的 OK 行」的条目——
    重打=新增行，旧分归档；已补齐当前版本的条目不再重复重打（分批续任务幂等）。
    scope=failed：仅落过 FAILED 行、尚无 OK 行的条目（失败补打）。
    无 OK 分的新条目不在此列——它们由常规 score_round 幂等补打。
    """
    from sqlalchemy import select

    from ..models import ScoreResult

    direction_id = direction.id
    has_ok = select(ScoreResult.item_id).where(
        ScoreResult.direction_id == direction_id, ScoreResult.status == "OK").scalar_subquery()
    has_current_ok = select(ScoreResult.item_id).where(
        ScoreResult.direction_id == direction_id, ScoreResult.status == "OK",
        ScoreResult.prompt_version == direction.prompt_version).scalar_subquery()
    # 经 Source 关联定位方向成员（item.direction_id 冗余列在 G1 前的历史行为空）
    q = db.query(Item.id).join(Source, Item.source_id == Source.id).filter(
        Source.direction_id == direction_id)
    if scope == "failed":
        has_failed = select(ScoreResult.item_id).where(
            ScoreResult.direction_id == direction_id,
            ScoreResult.status == "FAILED").scalar_subquery()
        q = q.filter(Item.id.in_(has_failed), ~Item.id.in_(has_ok))
    else:
        # 重打=新增行（已有 OK 行但缺当前版本行）；首导窗口外归档条目（无任何 OK 行）
        # 经重打分任务补打（全文已照存）
        from sqlalchemy import and_, or_

        q = q.filter(or_(
            and_(Item.id.in_(has_ok), ~Item.id.in_(has_current_ok)),
            and_(Item.fetch_status == "ARCHIVED", ~Item.id.in_(has_ok)),
        ))
    return [row[0] for row in q.order_by(Item.id).all()]


def process_rescore_tasks(db: Session) -> list[dict]:
    """消化全部 PENDING 的 rescore 任务（方向重打分，ADR-9 分批形态）。

    每任务单轮至多处理 SCORE_ROUND_MAX_ITEMS 条（复用打分突发上限），超出部分
    派生一个同 payload 的后续 PENDING 任务继续消化（fetch/score 轮次链自动带动，
    60 分钟僵死回收档与 score 同档）。重打分=新增 score_result 行，旧分归档不覆盖。
    """
    from ..scoring.service import score_item

    out: list[dict] = []
    tasks = db.query(PipelineTask).filter(PipelineTask.kind == "rescore",
                                          PipelineTask.status == "PENDING").all()
    for task in tasks:
        if not _claim(db, task):
            continue
        payload = task.payload or {}
        direction = db.get(Direction, payload.get("direction_id"))
        scope = payload.get("scope") or "all"
        if direction is None or direction.status == Direction.STATUS_DELETED:
            _finish(db, task, status="FAILED", error="rescore 方向不存在或已删除")
            out.append({"task_id": task.id, "status": task.status})
            continue
        candidate_ids = _rescore_candidate_ids(db, direction, scope)
        batch = candidate_ids[:config.SCORE_ROUND_MAX_ITEMS]
        scored = failed = 0
        for item_id in batch:
            item = db.get(Item, item_id)
            if item is None:
                continue
            try:
                sr = score_item(db, item, direction)
                scored += int(sr.status == "OK")
                failed += int(sr.status != "OK")
            except Exception as e:  # noqa: BLE001  单条异常不中断整批
                failed += 1
                log.warning("rescore 单条异常 item=%s: %s", item_id, e)
        remaining = len(candidate_ids) - len(batch)
        if remaining > 0:
            _new_task(db, kind="rescore", payload=dict(payload))
        _finish(db, task, status="DONE",
                stats={"rescored": scored, "call_failed": failed,
                       "remaining": remaining, "scope": scope})
        out.append({"task_id": task.id, "status": task.status,
                    "rescored": scored, "remaining": remaining})
    return out


def _route_candidates(db: Session, direction: Direction,
                      candidates: list[Item]) -> tuple[list[Item], dict]:
    """检索路由接线（路由器不是过滤器）：只改顺序不改候选集合。

    顺序即管线：向量补齐（失败容错，内部吞异常）→ 查询向量就绪检查 → 语义
    近重复标记（判重者剔除出打分候选）→ 命中/未命中分桶排序。嵌入整链任何
    异常=全量慢速（stats 落 embed_fallback），零静默丢弃。
    """
    from ..retrieval.embedder import ensure_item_vectors
    from ..retrieval.query import direction_query_vector, ensure_direction_query_vec
    from ..retrieval.router import mark_semantic_duplicates, partition_items
    from .budget import budget_exceeded

    # 预算闸②嵌入暂停：预算触发即跳过整条嵌入链，路由自动回退全量慢速
    if budget_exceeded(db):
        return candidates, {"routed_hits": 0, "routed_misses": len(candidates),
                            "embed_disabled": True, "budget_embed_paused": True}
    try:
        ensure_item_vectors(db, candidates)
        if not candidates:
            return candidates, {"routed_hits": 0, "routed_misses": 0,
                                "embed_disabled": True}
        query_ready = ensure_direction_query_vec(db, direction)
        model_version = config.MOARK_EMBED_MODEL
        if not query_ready or not model_version or model_version == "none":
            return candidates, {"routed_hits": 0, "routed_misses": len(candidates),
                                "embed_disabled": True}
        marked = mark_semantic_duplicates(db, direction, candidates,
                                          model_version=model_version)
        if marked:
            marked_ids = {i.id for i in marked}
            candidates = [i for i in candidates if i.id not in marked_ids]
        ordered, stats = partition_items(
            db, direction, candidates, query_vec=direction_query_vector(direction),
            model_version=model_version,
        )
        return ordered, stats
    except Exception as e:  # noqa: BLE001  检索层故障永不丢内容：回退全量慢速
        db.rollback()
        log.warning("检索路由异常，本轮回退全量慢速打分: %s", e)
        return candidates, {"routed_hits": 0, "routed_misses": len(candidates),
                            "embed_fallback": True}


def score_round(db: Session, *, triggered_by: str = "manual", direction_id: int | None = None) -> dict:
    """对全部启用方向打一轮分。

    幂等：只对 fetch_status=FETCHED 且尚无 OK 打分（status=OK）的条目调用 LLM——
    FAILED 的下轮自动续跑，OK 的绝不重复打分（每条内容只烧一次打分 LLM）。
    入口先消化 PENDING 的 rescore 任务（重打分与常规打分共用轮次链与突发上限）。
    打分前经检索路由排序：命中方向查询的条目本轮优先，未命中条目仍全量打分
    （仅顺序后移）；语义/URL 判重条目不进打分（duplicate_of 已指向 origin）。
    预算闸③打分转慢速：Token 日预算触发时轮上限降为 score_slow_round_max_items
    （继续低速不绝停，超出部分下轮幂等续跑）。
    """
    from ..models import ScoreResult
    from ..scoring.service import score_item
    from .budget import budget_exceeded, score_slow_cap

    process_rescore_tasks(db)
    q = db.query(Direction).filter(Direction.status == Direction.STATUS_ACTIVE)
    if direction_id is not None:
        q = q.filter(Direction.id == direction_id)
    directions = q.all()
    summary: dict[str, object] = {"triggered_by": triggered_by, "directions": []}
    budget_slow = budget_exceeded(db)
    if budget_slow:
        # 预算闸事件通知（每自然日至多一次，去重键带日期；未配置仅落日志）
        from ..pipeline.budget import tokens_used_today
        from ..siteconfig import get_config as _get_config
        from ..notify.triggers import notify_budget_exceeded

        notify_budget_exceeded(db, used_tokens=tokens_used_today(db),
                               budget=int(_get_config(db, "daily_token_budget") or 0))

    for d in directions:
        task = _new_task(db, kind="score", payload={"direction_id": d.id, "prompt_version": d.prompt_version})
        task.status = "RUNNING"
        task.attempts += 1
        db.commit()
        scored = failed = passed = parse_failed = 0
        try:
            candidates = (
                db.query(Item)
                .filter(
                    Item.source_id.in_(db.query(Source.id).filter_by(direction_id=d.id, enabled=True)),
                    Item.fetch_status == "FETCHED",
                    # 零信任过滤 REJECTED 的条目不进打分（全文仍留库可查）
                    Item.sanitize_status == "PASSED",
                    # 判重条目不进打分（URL 指纹/语义近重复，duplicate_of 指向 origin）
                    Item.duplicate_of.is_(None),
                )
                .outerjoin(ScoreResult, (ScoreResult.item_id == Item.id) & (ScoreResult.direction_id == d.id)
                           & (ScoreResult.status == "OK"))
                .filter(ScoreResult.id.is_(None))
                .all()
            )
            ordered, route_stats = _route_candidates(db, d, candidates)
            # 突发上限：单轮至多 SCORE_ROUND_MAX_ITEMS 条；预算触发时降为慢速上限
            round_cap = score_slow_cap(db) if budget_slow else config.SCORE_ROUND_MAX_ITEMS
            items = ordered[:round_cap]
            for item in items:
                try:
                    sr = score_item(db, item, d)
                except Exception as e:  # noqa: BLE001  单条异常不中断整轮
                    failed += 1
                    log.warning("score_item 异常 item=%s: %s", item.id, e)
                    continue
                if sr.status == "OK":
                    scored += 1
                    passed += int(sr.passed)
                elif sr.error and "JSONParseError" in sr.error:
                    parse_failed += 1
                else:
                    failed += 1
            _stats = {
                **route_stats,
                # candidates=本轮实际进入打分的条数（上限截断后）；
                # candidates_total=路由前的全量候选数（含超出上限留待下轮的部分）
                "candidates": len(items), "candidates_total": len(candidates),
                "budget_slow": budget_slow,
                "scored": scored, "passed": passed,
                "call_failed": failed, "parse_failed": parse_failed,
            }
            _status = "FAILED" if (failed + parse_failed) > 0 and scored == 0 else "DONE"
            _error = (f"{failed + parse_failed} 条打分未成功（含解析失败 {parse_failed}），下轮续跑"
                      if failed + parse_failed > 0 else None)
            _finish(db, task, status=_status, stats=_stats, error=_error)
        except Exception as e:  # noqa: BLE001
            db.rollback()  # P1-1：先回滚再落终态（动机见 fetch_round 同款注释）
            _finish(db, task, status="FAILED", error=f"{type(e).__name__}: {e}")
        summary["directions"].append({
            "direction_id": d.id, "name": d.name, "task_id": task.id, "status": task.status,
            **(task.payload.get("stats") or {}), "error": task.last_error,
        })
    return summary


def write_task(db: Session, author_id: int, *, triggered_by: str = "manual",
               budget_confirmed: bool = False, **run_kwargs) -> dict:
    """触发一次作者写作，状态经 pipeline_task 落库（run_kwargs 透传 batch_id 等）。

    预算闸④写作确认：Token 日预算触发且未携带站长确认标记时拒绝自动执行
    （任务落 DONE + budget_confirmation_required 标记，不产生任何 LLM 调用），
    携带 budget_confirmed=True 的手动触发照常执行。
    """
    from ..models import Author
    from ..authors.writer import run_write
    from .budget import budget_exceeded

    author = db.get(Author, author_id)
    if author is None:
        raise ValueError(f"author {author_id} 不存在")
    if budget_exceeded(db) and not budget_confirmed:
        task = _new_task(db, kind="write",
                         payload={"author_id": author_id, **run_kwargs})
        task.status = "RUNNING"
        task.attempts += 1
        db.commit()
        _finish(db, task, status="DONE",
                payload_extra={"executed": False, "budget_confirmation_required": True,
                               "note": "Token 日预算已触发，写作需站长确认后执行"})
        return {"task_id": task.id, "status": task.status,
                "budget_confirmation_required": True, "executed": False}
    task = _new_task(db, kind="write", payload={"author_id": author_id, **run_kwargs})
    task.status = "RUNNING"
    task.attempts += 1
    db.commit()
    try:
        run = run_write(db, author, triggered_by=triggered_by, **run_kwargs)
        _finish(db, task, status="DONE" if run.status == "OK" else "FAILED",
                payload_extra={"write_run_id": run.id, "decision": run.decision,
                               "article_id": run.article_id},
                error=run.error if run.status != "OK" else None)
    except Exception as e:  # noqa: BLE001
        db.rollback()  # P1-1：先回滚再落终态（动机见 fetch_round 同款注释）
        _finish(db, task, status="FAILED", error=f"{type(e).__name__}: {e}")
    return {"task_id": task.id, "status": task.status, "payload": task.payload,
            "last_error": task.last_error}
