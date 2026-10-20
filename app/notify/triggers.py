"""通知触发接线：四类事件的触发点与去重键形态（SMTP 未配置时仅落日志）。

- 源失效（DT-1 状态机转换点）：hard_failed 与 suspect 各自通知，同源 24h 去重；
  hard_failed→none 复活（BE-3/SM-1）：与失效共开关共去重键，suspect 恢复不通知；
- Token 日预算触发（预算闸事件）：每自然日至多一次（去重键带日期）；
- 采集面聚合哨兵：超过一半启用源处于失效/降频状态持续 2 轮 → 整体降级通知
  （轮次计数持久化在 site_config，重启不丢）；
- 磁盘用量超阈值：24h 去重；
- 服务商治理三触发器（BE-7）：供应商冷却切换（providers.base._call 边沿
  触发）/余额不足（探测模块调用）/LLM 24h 错误率（score 轮末评估宿主，
  样本 ≥10 防小分母）——24h 去重。
设计依据见 docs/design-index.md「AC-19.2」「AC-19.3」「AC-19.4」「PV-2」~「PV-4」。
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..siteconfig import get_config
from . import hub

log = logging.getLogger("newswright.notify")


def _dispatch(db: Session, *, switch_key: str, category: str, dedupe_key: str,
              subject: str, body: str) -> dict:
    """按触发开关分发（六类告警的唯一咽喉）：开关关闭 = 仅落日志；过闸消息经
    调度中枢入队（BE-2 起邮件发送由 hub 统管：双闸/缓冲上限/去重落账见
    app/notify/hub.py；返回 {"queued": ...}，实际投递由 flush 执行）。"""
    if get_config(db, switch_key) is False:
        log.info("通知触发开关关闭，事件仅落日志: %s %s", category, dedupe_key)
        return {"sent": False, "reason": "switch_off"}
    return hub.enqueue(db, subject, body, category=category,
                       dedupe_key=dedupe_key)


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


def notify_source_recovered(db: Session, source) -> dict:
    """hard_failed→none 复活通知（BE-3/SM-1）：抓取成功复位死刑态时触发。
    与源失效共一开关（notify_on_source_failure，源健康族失效/复活同开关，
    不新增配置键）与同去重键 source-{id}（24h 窗口内先失效后复活不双发）；
    suspect→none 降频探测恢复不通知（非事件）。"""
    return _dispatch(
        db, switch_key="notify_on_source_failure", category="source_recovered",
        dedupe_key=f"source-{source.id}",
        subject=f"[newswright] 来源已复活: {source.url[:80]}",
        body=f"来源已复活恢复采集\n来源 id={source.id} url={source.url}\n"
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
                              sustained_rounds: int = 2,
                              now: datetime | None = None) -> dict:
    """采集面聚合哨兵（fetch 轮末检查）：超过一半启用源处于 suspect/hard_failed
    或降频状态持续 2 轮 → 整体降级通知。轮次计数持久化在 site_config。

    降级分子出清（BE-3/SM-4）：hard_failed 超 sentinel_exclude_stale_days
    （缺省 30 天）视为陈旧不再计入；rate_limited_until 过期旧账不计入
    （now 比较）——分母（enabled）与源状态本体不动。"""
    from ..models import Source
    from ..pipeline.skip_policy import _aware, is_stale_dead

    now = now or datetime.now(timezone.utc)
    stale_days = int(get_config(db, "sentinel_exclude_stale_days") or 30)
    enabled = db.query(Source).filter(Source.enabled.is_(True)).all()
    if not enabled:
        return {"sent": False, "reason": "no_sources"}
    degraded = [s for s in enabled
                if s.failure_level == "suspect"
                or (s.failure_level == "hard_failed"
                    and not is_stale_dead(s, now=now, stale_days=stale_days))
                or (s.rate_limited_until is not None
                    and _aware(s.rate_limited_until) > now)]
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


# ---------- 服务商治理三触发器（BE-7，注册表骨架位的消费方） ----------


def notify_provider_switched(db: Session, *, name: str, status: int | None,
                             ttl_seconds: float) -> dict:
    """供应商冷却切换通知（PV-2，providers.base._call 边沿触发——仅「未冷却
    →冷却」转换时调一次）：body 含供应商名/致命状态码/冷却 TTL 分钟数/
    候选链次位去向；dedupe=f"provider-{name}"（24h 去重兜底，防冷却抖动
    重发与打分轮逐条失败灌爆）。"""
    minutes = int(ttl_seconds // 60) if ttl_seconds else 0
    return _dispatch(
        db, switch_key="notify_on_provider_switch", category="provider_switched",
        dedupe_key=f"provider-{name}",
        subject=f"[newswright] LLM 供应商已冷却切换: {name}",
        body=f"供应商 {name} 遭供应商级致命（HTTP {status}），进入冷却 {minutes} 分钟，"
             f"chat 域后续请求走候选链次位。\n"
             f"时间: {datetime.now(timezone.utc).isoformat()}")


def notify_balance_low(db: Session, *, name: str, amount: float,
                       threshold: float) -> dict:
    """余额不足告警（BE-7 余额探测调用）：amount < 阈值（缺省 ¥5）时发。
    dedupe=f"balance-{name}"——24h 去重天然日频（探测宿主为每日轮）。"""
    return _dispatch(
        db, switch_key="notify_on_balance_low", category="balance_low",
        dedupe_key=f"balance-{name}",
        subject=f"[newswright] 供应商余额不足: {name}",
        body=f"供应商 {name} 余额 {amount} 元，低于告警阈值 {threshold} 元。\n"
             f"冷却切换只兜住 402 时刻，请尽快充值（余额耗尽前主动发现）。\n"
             f"时间: {datetime.now(timezone.utc).isoformat()}")


def _llm_attempts_24h(db: Session, *, now: datetime) -> int:
    """24h 滚动窗 LLM 调用总量（错误率触发器的防小分母判据；口径与
    observability._llm_error_rate_24h 的分母一致——usage_log 全行计数）。"""
    from sqlalchemy import func

    from ..models import UsageLog

    since = now - timedelta(hours=24)
    return int(db.query(func.count(UsageLog.id)).filter(
        UsageLog.created_at >= since).scalar() or 0)


def check_llm_error_rate(db: Session, *, now: datetime | None = None) -> dict:
    """LLM 24h 错误率触发器（score 轮末评估宿主——哨兵/磁盘同款姿势，纯聚合
    指标无自然事件点）：样本 ≥10（防小分母）且错误率 ≥ site_config
    llm_error_rate_warn（缺省 0.5）→ 告警（dedupe="llm-error-rate" 24h 去重）。
    全候选冷却的静默路径（scoring「无可用 LLM 提供方」FAILED 终态）由本
    触发器补提醒。"""
    from ..observability import _llm_error_rate_24h

    now = now or datetime.now(timezone.utc)
    rate = _llm_error_rate_24h(db, now)
    total = _llm_attempts_24h(db, now=now)
    raw_threshold = get_config(db, "llm_error_rate_warn")
    threshold = float(0.5 if raw_threshold is None else raw_threshold)
    if total < 10:
        return {"sent": False, "reason": "insufficient_samples",
                "total": total, "error_rate": rate}
    if rate < threshold:
        return {"sent": False, "reason": "below_threshold",
                "total": total, "error_rate": rate}
    out = _dispatch(
        db, switch_key="notify_on_llm_error_rate", category="llm_error_rate_high",
        dedupe_key="llm-error-rate",
        subject=f"[newswright] LLM 24h 错误率超阈（{rate:.0%}）",
        body=f"近 24h LLM 调用 {total} 次，错误率 {rate:.1%}（阈值 {threshold:.0%}）。\n"
             f"候选链全冷却或供应商持续故障会以 FAILED 终态推高错误率，"
             f"请查 /api/providers/status。\n"
             f"时间: {datetime.now(timezone.utc).isoformat()}")
    out.update({"total": total, "error_rate": rate})
    return out
