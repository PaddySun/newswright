"""通知能力插件层（能力插件化首批实现之一）：Notifier 接口 + 注册表 + SMTP 子类。

纪律（与 provider 注册表同构）：抽象 + 子类 + 注册一行；接口默认无副作用——
未配置 = 记录事件不报错；凭据不回显、不落日志；发送失败 WARN 不抛。
设计依据见 docs/design-index.md「ADR-10」。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from ..siteconfig import get_config, set_config

log = logging.getLogger("newswright.notify")

_registry: dict[str, type["Notifier"]] = {}

# 去重窗口（小时）：同一 category+dedupe_key 在窗口内不重发
DEDUP_WINDOW_HOURS = 24


def register(name: str, cls: type["Notifier"]) -> None:
    _registry[name] = cls


def available() -> list[str]:
    return sorted(_registry)


def get_notifier(name: str, db: Session) -> "Notifier | None":
    cls = _registry.get(name)
    return cls(db) if cls else None


def default_notifier(db: Session) -> "Notifier | None":
    """默认通知通道（未注册任何实现时返回 None——事件仅落日志）。"""
    if not _registry:
        return None
    return get_notifier(sorted(_registry)[0], db)


class Notifier(ABC):
    """通知通道接口：send 契约含 24h 去重判定（持久化到 site_config，重启不丢）。"""

    name = "base"

    def __init__(self, db: Session) -> None:
        self.db = db

    @abstractmethod
    def configured(self) -> bool:
        """通道是否已配置（未配置时事件仅落日志，不报错）。"""

    @abstractmethod
    def _deliver(self, subject: str, body: str) -> None:
        """真实投递（失败抛异常由 send 统一捕获转 WARN）。"""

    def _dedupe_key_name(self, category: str, dedupe_key: str) -> str:
        # site_config 键形态：notify_last_sent_<category>_<dedupe_key>
        # ——持久化承载 24h 去重，进程重启/新会话不丢（无人值守要求）
        return f"notify_last_sent_{category}_{dedupe_key}"

    def _recently_sent(self, category: str, dedupe_key: str,
                       *, now) -> bool:
        from datetime import datetime, timedelta

        raw = get_config(self.db, self._dedupe_key_name(category, dedupe_key))
        if not raw:
            return False
        try:
            last = datetime.fromisoformat(str(raw))
        except ValueError:
            return False
        if last.tzinfo is None:
            from datetime import timezone

            last = last.replace(tzinfo=timezone.utc)
        return now - last < timedelta(hours=DEDUP_WINDOW_HOURS)

    def _record_sent(self, category: str, dedupe_key: str, *, now) -> None:
        set_config(self.db, self._dedupe_key_name(category, dedupe_key),
                   now.isoformat())

    def send(self, subject: str, body: str, *, category: str,
             dedupe_key: str) -> dict:
        """发送入口：去重判定 → 投递 → 成功落去重时间戳（失败不落、允许重试）。"""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        if not self.configured():
            log.info("通知事件仅落日志（通道 %s 未配置）: category=%s key=%s subject=%s",
                     self.name, category, dedupe_key, subject)
            return {"sent": False, "reason": "not_configured"}
        if self._recently_sent(category, dedupe_key, now=now):
            log.info("通知去重命中（%s/%s，24h 窗口内不重发）", category, dedupe_key)
            return {"sent": False, "reason": "deduped"}
        try:
            self._deliver(subject, body)
        except Exception as e:  # noqa: BLE001  发送失败 WARN 不抛（不阻断任何轮）
            # 报错脱敏：只记类型与异常摘要，绝不携带通道配置值
            log.warning("通知投递失败（通道 %s）: %s: %s", self.name,
                        type(e).__name__, e)
            return {"sent": False, "reason": "deliver_failed"}
        self._record_sent(category, dedupe_key, now=now)
        log.info("通知已发送（通道 %s）: category=%s key=%s subject=%s",
                 self.name, category, dedupe_key, subject)
        return {"sent": True}
