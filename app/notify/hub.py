"""通知调度中枢（BE-2）：队列 + 账户/类别双闸 + 缓冲上限 + 类别注册表 + 键治理。

全部通知消费方（六个告警触发器、测试邮件端点）一律经 enqueue 入队，由 flush
统一投递——SMTP 账户级最小发送硬间隔与类型级可调间隔在此统管（R2）。

形态钉死（任务书 doc/BE/BE-2-任务书.md；条款见 docs/design-index.md「NC-1」~「NC-3」）：
- 入队五关：注册表未知→unknown_category（WARN，防拼写错静默丢）/通道未配置→
  not_configured 仅落日志/去重预检（持久化时间戳+在队同键）→deduped/digest 族
  全局开关关拒收→digest_disabled/过关入队 {"queued": True}；
- flush 按入队序扫描：账户硬间隔（ACCOUNT_HARD_INTERVAL_S=60 代码常量，「硬」
  不可配）或类别最小间隔（site_config notify_category_intervals 覆盖，缺省取
  注册表 default_min_interval_s=0=仅账户闸）未到→留队冷却缓存；双闸皆过→锁外
  投递，成功才落去重时间戳（A1 语义保持）+更新进程内锚点；失败 WARN 丢弃不重试
  （告警类有下轮触发兜底，与「失败不落时间戳允许事件重触发」同源）；
- 每账户缓冲上限 ACCOUNT_QUEUE_CAP=10：溢出按丢弃序挤出（digest 族→priority
  数值大者→同级丢最新入队者），逐条 WARN+dropped_total 按 category 计数；
- 队列进程内、重启即丢——**明示为接受语义**（告警类有下轮触发兜底，不持久化）；
  锚点同为进程内（重启即清，下次投递重新起算）。

并发纪律：队列/锚点/计数持 threading.Lock（fetch/score/hot/backup 多 job 并行是
既有形态）；投递（SMTP 网络往返）在锁外。账户=通道名（当前唯一通道 smtp，即
单一 SMTP 账户；多通道时按注册表名自然分列）。
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import SiteConfig
from ..siteconfig import get_config
from . import default_notifier

log = logging.getLogger("newswright.notify")

# 账户硬间隔（秒）：同一 SMTP 账户最小发送硬间隔——代码常量，「硬」不可配（R2）
ACCOUNT_HARD_INTERVAL_S = 60
# 每账户队列上限（封）：超出按丢弃序挤出（R2 缓冲上限）
ACCOUNT_QUEUE_CAP = 10
# 去重键惰性清理节流（秒）：距上次清理 ≤1h 的 flush 不重扫
KEY_CLEANUP_INTERVAL_S = 3600
# 去重键过期宽限（小时）：最后发送时间早于「窗口+24h」才删（窗口内的键是活抑制）
KEY_GRACE_HOURS = 24

# 类别注册表（AC-4）：测试与实现共用防漂移；BE-7 新触发器直接用 hub.enqueue。
# 条目字段：family（alert|digest）/priority（丢弃序用，数值大者先丢）/
# default_min_interval_s（类别闸缺省间隔，0=仅账户硬间隔）。
# digest 族本批零条目（D5：邮件订阅不进本期范围，仅全局开关与拒收分支预留）。
CATEGORY_REGISTRY: dict[str, dict] = {
    # 六类现有告警（category 字面量与 app/notify/triggers.py 实串一致）
    "source_hard_fail": {"family": "alert", "priority": 1,
                         "default_min_interval_s": 0},
    "source_suspect": {"family": "alert", "priority": 1,
                       "default_min_interval_s": 0},
    "token_budget": {"family": "alert", "priority": 1,
                     "default_min_interval_s": 0},
    "collective_degradation": {"family": "alert", "priority": 1,
                               "default_min_interval_s": 0},
    "disk_usage": {"family": "alert", "priority": 1,
                   "default_min_interval_s": 0},
    "reconcile": {"family": "alert", "priority": 2,
                  "default_min_interval_s": 0},
    # hard_failed→none 复活通知（BE-3/SM-1）：与失效同开关族，低紧迫档
    "source_recovered": {"family": "alert", "priority": 2,
                         "default_min_interval_s": 0},
    # 测试邮件专用（POST /settings/notify/test；唯一时间戳键不参与抑制）
    "notify_test": {"family": "alert", "priority": 2,
                    "default_min_interval_s": 0},
    # 服务商治理三触发器（BE-7 已接线）
    "provider_switched": {"family": "alert", "priority": 1,
                          "default_min_interval_s": 0},
    "balance_low": {"family": "alert", "priority": 1,
                    "default_min_interval_s": 0},
    "llm_error_rate_high": {"family": "alert", "priority": 1,
                            "default_min_interval_s": 0},
}


@dataclass
class _Msg:
    account: str
    category: str
    dedupe_key: str
    subject: str
    body: str
    seq: int  # 入队序（丢弃序「同级丢最新」的比较位）


# ---- 进程内状态（全部随 _lock；重启即丢=接受语义，见模块 docstring） ----
_lock = threading.Lock()
_queue: list[_Msg] = []            # 全账户按入队序混排（每账户配额在入队时校验）
_seq_counter = 0
_account_last_delivered: dict[str, datetime] = {}
_category_last_delivered: dict[str, datetime] = {}
_delivered_total = 0
_dropped_total: dict[str, int] = {}
_deduped_total = 0
_last_key_cleanup: datetime | None = None


def _reset_for_tests() -> None:
    """清空中枢进程级状态（测试复位位；生产不调用——队列/锚点随进程存活）。"""
    global _seq_counter, _delivered_total, _deduped_total, _last_key_cleanup
    with _lock:
        _queue.clear()
        _account_last_delivered.clear()
        _category_last_delivered.clear()
        _dropped_total.clear()
        _seq_counter = 0
        _delivered_total = 0
        _deduped_total = 0
        _last_key_cleanup = None


def snapshot() -> dict:
    """进程内计数器快照（观测挂靠：pipeline stats 的 notify_* 两键源）。"""
    with _lock:
        return {
            "queue_depth": len(_queue),
            "delivered_total": _delivered_total,
            "dropped_total": dict(_dropped_total),
            "deduped_total": _deduped_total,
        }


def _drop_rank(msg: _Msg) -> tuple[bool, int, int]:
    """丢弃序比较键（max 者先丢）：digest 族 → priority 数值大者 → 最新入队者。"""
    entry = CATEGORY_REGISTRY.get(msg.category) or {}
    return (entry.get("family") == "digest", int(entry.get("priority", 0)),
            msg.seq)


def _enqueue_with_cap(msg: _Msg) -> None:
    """入队并执行溢出挤出：该账户超上限时按丢弃序逐条挤出（含新入者自身——
    同级时最新者即新入者，天然实现「丢新留旧」）；逐条 WARN+计数。"""
    account_msgs = [m for m in _queue if m.account == msg.account]
    _queue.append(msg)
    overflow = len(account_msgs) + 1 - ACCOUNT_QUEUE_CAP
    if overflow <= 0:
        return
    victims = sorted((m for m in _queue if m.account == msg.account),
                     key=_drop_rank, reverse=True)[:overflow]
    for victim in victims:
        _queue.remove(victim)
        _dropped_total[victim.category] = _dropped_total.get(victim.category, 0) + 1
        log.warning("通知队列溢出丢弃（账户 %s 达上限 %d）: category=%s key=%s "
                    "原因=丢弃序挤出", victim.account, ACCOUNT_QUEUE_CAP,
                    victim.category, victim.dedupe_key)


def enqueue(db: Session, subject: str, body: str, *, category: str,
            dedupe_key: str, now: datetime | None = None) -> dict:
    """入队入口（六触发器与测试邮件端点的统一咽喉）：五关判定见模块 docstring。"""
    global _seq_counter, _deduped_total
    now = now or datetime.now(timezone.utc)
    entry = CATEGORY_REGISTRY.get(category)
    if entry is None:
        log.warning("通知入队拒绝：未知类别 %r（防拼写错静默丢）: key=%s "
                    "subject=%s", category, dedupe_key, subject)
        return {"queued": False, "reason": "unknown_category"}
    notifier = default_notifier(db)
    if notifier is None or not notifier.configured():
        log.info("通知事件仅落日志（通道未配置）: category=%s key=%s subject=%s",
                 category, dedupe_key, subject)
        return {"queued": False, "reason": "not_configured"}
    if notifier._recently_sent(category, dedupe_key, now=now):
        log.info("通知去重命中（%s/%s，窗口内不重发）", category, dedupe_key)
        with _lock:
            _deduped_total += 1
        return {"queued": False, "reason": "deduped"}
    if entry["family"] == "digest" and not get_config(db, "notify_digest_enabled"):
        log.info("digest 族通知拒收（全局开关关）: category=%s key=%s",
                 category, dedupe_key)
        return {"queued": False, "reason": "digest_disabled"}
    with _lock:
        if any(m.category == category and m.dedupe_key == dedupe_key
               for m in _queue):
            _deduped_total += 1
            log.info("通知去重命中（%s/%s，已在队列）", category, dedupe_key)
            return {"queued": False, "reason": "deduped"}
        _seq_counter += 1
        _enqueue_with_cap(_Msg(account=notifier.name, category=category,
                               dedupe_key=dedupe_key, subject=subject,
                               body=body, seq=_seq_counter))
    return {"queued": True}


def _category_min_interval_s(db: Session, category: str) -> int:
    """类别最小间隔（秒）：site_config notify_category_intervals 覆盖 →
    注册表 default_min_interval_s 兜底（缺省 0=仅账户硬间隔）。"""
    overrides = get_config(db, "notify_category_intervals")
    if isinstance(overrides, dict):
        raw = overrides.get(category)
        if raw is not None:
            try:
                return max(int(raw), 0)
            except (TypeError, ValueError):
                log.warning("notify_category_intervals[%s] 非法值 %r，回退缺省",
                            category, raw)
    entry = CATEGORY_REGISTRY.get(category) or {}
    return max(int(entry.get("default_min_interval_s", 0)), 0)


def _next_deliverable_index(db: Session, now: datetime) -> int | None:
    """按入队序找首条双闸皆过的消息下标（持锁扫描；site_config 读取为快查，
    临界区可接受）。账户闸在前（更粗），类别闸在后。"""
    for i, msg in enumerate(_queue):
        anchor_a = _account_last_delivered.get(msg.account)
        if anchor_a is not None and \
                (now - anchor_a).total_seconds() < ACCOUNT_HARD_INTERVAL_S:
            continue
        interval_c = _category_min_interval_s(db, msg.category)
        if interval_c > 0:
            anchor_c = _category_last_delivered.get(msg.category)
            if anchor_c is not None and \
                    (now - anchor_c).total_seconds() < interval_c:
                continue
        return i
    return None


def flush(db: Session, *, now: datetime | None = None) -> dict:
    """投递一轮：按入队序扫描，双闸未到留队（冷却缓存），过闸者锁外投递。

    返回 {"delivered": ["category/key", ...], "deliver_failed": [...], "kept": n}。
    投递失败 WARN 并丢弃该消息（不重试）；去重时间戳仅投递成功才落。
    """
    global _delivered_total
    now = now or datetime.now(timezone.utc)
    notifier = default_notifier(db)
    _maybe_cleanup_dedupe_keys(db, now)
    delivered: list[str] = []
    failed: list[str] = []
    if notifier is None or not notifier.configured():
        with _lock:
            kept = len(_queue)
        return {"delivered": delivered, "deliver_failed": failed, "kept": kept}
    while True:
        with _lock:
            idx = _next_deliverable_index(db, now)
            if idx is None:
                break
            msg = _queue.pop(idx)
        try:
            notifier._deliver(msg.subject, msg.body)  # 锁外投递（网络往返）
        except Exception as e:  # noqa: BLE001  投递失败 WARN 丢弃不重试（下轮触发兜底）
            log.warning("通知投递失败（账户 %s）: %s: %s", msg.account,
                        type(e).__name__, e)
            with _lock:
                _dropped_total[msg.category] = \
                    _dropped_total.get(msg.category, 0) + 1
            failed.append(f"{msg.category}/{msg.dedupe_key}")
            continue
        # 成功才落去重时间戳（入队即落会在 flush 前重启时既丢消息又留窗口抑制）
        notifier._record_sent(msg.category, msg.dedupe_key, now=now)
        with _lock:
            _account_last_delivered[msg.account] = now
            _category_last_delivered[msg.category] = now
            _delivered_total += 1
        delivered.append(f"{msg.category}/{msg.dedupe_key}")
    with _lock:
        kept = len(_queue)
    return {"delivered": delivered, "deliver_failed": failed, "kept": kept}


def _maybe_cleanup_dedupe_keys(db: Session, now: datetime) -> None:
    """去重键惰性清理（缝隙 d）：距上次清理 >1h 才扫，删「最后发送时间早于
    窗口+24h 宽限」的 notify_last_sent_% 键（site_config 行数小，全扫可接受）。"""
    global _last_key_cleanup
    with _lock:
        if _last_key_cleanup is not None and \
                (now - _last_key_cleanup).total_seconds() <= KEY_CLEANUP_INTERVAL_S:
            return
        _last_key_cleanup = now
    window_h = 24.0
    raw_window = get_config(db, "notify_dedup_window_hours")
    if raw_window is not None:
        try:
            window_h = max(float(raw_window), 0.0)
        except (TypeError, ValueError):
            window_h = 24.0
    cutoff = now - timedelta(hours=window_h + KEY_GRACE_HOURS)
    removed = 0
    rows = db.query(SiteConfig).filter(
        SiteConfig.key.like("notify_last_sent_%")).all()
    for row in rows:
        try:
            last = datetime.fromisoformat(str(row.value))
        except (TypeError, ValueError):
            continue  # 坏值不清不炸（留给下次清理）
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last < cutoff:
            db.delete(row)
            removed += 1
    if removed:
        db.commit()
        log.info("通知去重键惰性清理：删除 %d 行（窗口 %gh+宽限 %dh 外）",
                 removed, window_h, KEY_GRACE_HOURS)
