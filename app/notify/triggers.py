"""通知触发接线：四类事件的触发点与去重键形态（SMTP 未配置时仅落日志）。

- 源失效（DT-1 状态机转换点）：hard_failed 与 suspect 各自通知，同源 24h 去重；
- Token 日预算触发（预算闸事件）：每自然日至多一次（去重键带日期）；
- 采集面聚合哨兵：超过一半启用源处于失效/降频状态持续 2 轮 → 整体降级通知
  （轮次计数持久化在 site_config，重启不丢）；
- 磁盘用量超阈值：24h 去重。
设计依据见 docs/design-index.md「AC-19.2」「AC-19.3」「AC-19.4」。
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..siteconfig import get_config
from . import default_notifier

log = logging.getLogger("newswright.notify")


def _dispatch(db: Session, *, switch_key: str, category: str, dedupe_key: str,
              subject: str, body: str) -> dict:
    """按触发开关分发：开关关闭或未配置 = 仅落日志（Notifier.send 自带语义）。"""
    if get_config(db, switch_key) is False:
        log.info("通知触发开关关闭，事件仅落日志: %s %s", category, dedupe_key)
        return {"sent": False, "reason": "switch_off"}
    notifier = default_notifier(db)
    if notifier is None:
        log.info("通知事件仅落日志（无已注册通道）: %s %s %s",
                 category, dedupe_key, subject)
        return {"sent": False, "reason": "not_configured"}
    return notifier.send(subject, body, category=category, dedupe_key=dedupe_key)


def notify_source_failure(db: Session, source, *, level: str) -> dict:
    """源状态转换通知：failure_level ∈ {hard_failed, suspect} 时触发。"""
    if level not in ("hard_failed", "suspect"):
        return {"sent": False, "reason": "not_a_failure_transition"}
    category = "source_hard_fail" if level == "hard_failed" else "source_suspect"
    label = ("来源已硬失效（连续多轮 404/403/410，已停止抓取）"
             if level == "hard_failed"
             else "来源疑似失效（连续空轮，转低频探测）")
    subject = f"[newswright] 来源{ '硬失效' if level == 'hard_failed' else '疑似失效' }: {source.url[:80]}"
    return _dispatch(
        db, switch_key="notify_on_source_failure", category=category,
        dedupe_key=f"source-{source.id}", subject=subject,
        body=f"{label}\n来源 id={source.id} url={source.url}\n"
             f"最近错误: {source.last_error or '-'}\n"
             f"时间: {datetime.now(timezone.utc).isoformat()}")


def notify_budget_exceeded(db: Session, *, used_tokens: int, budget: int) -> dict:
    """Token 日预算触发通知：每自然日至多一次（去重键带日期；自然日取站点时区）。"""
    from ..timeline import local_date_key, site_zone

    day = local_date_key(site_zone(db))
    return _dispatch(
        db, switch_key="notify_on_token_budget", category="token_budget",
        dedupe_key=f"daily-{day}",
        subject=f"[newswright] Token 日预算已触发（{day}）",
        body=f"当日消耗 {used_tokens} tokens，已达预算 {budget}。\n"
             f"降级秩序：探索层暂停 → 嵌入暂停 → 打分慢速 → 写作需站长确认。")


def notify_usage_reconcile_deviation(db: Session, *, month: str, ledger_units: int,
                                     platform_units: int,
                                     deviation_pct: float) -> dict:
    """月度计费对账偏差告警（>10% 触发时由对账端点调用）：同月 24h 去重。"""
    return _dispatch(
        db, switch_key="notify_on_reconcile", category="reconcile",
        dedupe_key=f"reconcile-{month}",
        subject=f"[newswright] 计费对账偏差超阈（{month}：{deviation_pct}%）",
        body=f"{month} 平台账单 {platform_units} units vs 账本汇总 {ledger_units} units，"
             f"偏差 {deviation_pct}%（阈值 10%）。\n账本是唯一可信源，请核对平台"
             f"计费口径（Key 有效性/计费单位定义）。\n"
             f"时间: {datetime.now(timezone.utc).isoformat()}")


def check_collective_sentinel(db: Session, *, threshold_ratio: float = 0.5,
                              sustained_rounds: int = 2) -> dict:
    """采集面聚合哨兵（fetch 轮末检查）：超过一半启用源处于 suspect/hard_failed
    或降频状态持续 2 轮 → 整体降级通知。轮次计数持久化在 site_config。"""
    from ..models import Source

    enabled = db.query(Source).filter(Source.enabled.is_(True)).all()
    if not enabled:
        return {"sent": False, "reason": "no_sources"}
    degraded = [s for s in enabled
                if s.failure_level in ("suspect", "hard_failed")
                or s.rate_limited_until is not None]
    key = "collective_sentinel_rounds"
    if len(degraded) > len(enabled) * threshold_ratio:
        count = int(get_config(db, key) or 0) + 1
        from ..siteconfig import set_config

        set_config(db, key, count)
        if count < sustained_rounds:
            return {"sent": False, "reason": f"sustained_{count}"}
        return _dispatch(
            db, switch_key="notify_on_collective", category="collective_degradation",
            dedupe_key="collective",
            subject="[newswright] 采集面整体降级",
            body=f"启用源 {len(enabled)} 个中 {len(degraded)} 个处于失效/降频状态，"
                 f"已持续 {count} 轮（超过一半）。\n"
                 f"时间: {datetime.now(timezone.utc).isoformat()}")
    from ..siteconfig import set_config

    if get_config(db, key):
        set_config(db, key, 0)  # 状态恢复：连续计数清零
    return {"sent": False, "reason": "healthy"}


def check_disk_usage(db: Session) -> dict:
    """磁盘用量阈值检查（fetch 轮末顺带）：用量 > site_config 阈值（默认 80%）触发。"""
    from .. import db as appdb

    path = appdb.engine.url.database or "."
    usage = shutil.disk_usage(Path(path).anchor or path)
    used_percent = round((usage.total - usage.free) / usage.total * 100, 1)
    raw_threshold = get_config(db, "disk_usage_warn_percent")
    threshold = float(80 if raw_threshold is None else raw_threshold)
    if used_percent <= threshold:
        return {"sent": False, "reason": "below_threshold", "used_percent": used_percent}
    out = _dispatch(
        db, switch_key="notify_on_disk", category="disk_usage", dedupe_key="disk",
        subject=f"[newswright] 磁盘用量超阈值（{used_percent}%）",
        body=f"磁盘用量 {used_percent}%，超过阈值 {threshold}%。\n"
             f"剩余 {usage.free // (1024 * 1024)} MB。")
    out["used_percent"] = used_percent
    return out
