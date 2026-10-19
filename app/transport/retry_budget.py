"""进程级 retry budget（BE-4/TG-3）：同 caller 滑窗计数 + 三消费点。

源意（D9/R7）：防多层重试叠乘——打分轮 200 条全失败×每条重试 2=400 次
retry 对同一 LLM 供应商的锤击。三消费点（providers/_call、search/search、
hot/fetch_platform 的重试循环）在**决定重试前**调 spend("<caller>")；
False 则不再重试，把当前错误按不可重试处理（快速失败到 FAILED 下轮续跑，
防锤）。必须有消费方——只加计数不加消费就是第二个 mark_cooldown 死件。

阈值语义注记：熔断正是预算目的（故障期快速失败）；被拒的尝试也计入窗口
（持续压力维持熔断，压力停止后窗口滑出自然恢复）。
设计依据见 docs/design-index.md「TG-3」（BE-4 增补）。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable

from sqlalchemy.orm import Session

from ..siteconfig import get_config

log = logging.getLogger(__name__)

RETRY_BUDGET_WINDOW_S = 60.0
# 代码缺省（与 siteconfig.DEFAULTS 同值）：db=None/读不到配置时回退。
DEFAULT_RETRY_BUDGET_PER_MINUTE = 50

_spends: dict[str, deque[float]] = {}
_lock = threading.Lock()


def _reset_for_tests() -> None:
    """复位进程级预算窗（判例纪律：每测试文件 fixture 复位）。"""
    with _lock:
        _spends.clear()


def _limit_for(db: Session | None) -> int:
    limit = DEFAULT_RETRY_BUDGET_PER_MINUTE
    if db is not None:
        try:
            raw = get_config(db, "retry_budget_per_minute")
        except Exception:  # noqa: BLE001  桩 db（测试 _FakeDB）无 ORM 面——回退缺省
            raw = None
        if raw is not None:
            try:
                limit = max(int(raw), 1)
            except (TypeError, ValueError):
                log.warning("retry_budget_per_minute 非法值 %r，回退缺省 %d",
                            raw, DEFAULT_RETRY_BUDGET_PER_MINUTE)
    return limit


def spend(caller: str, *, db: Session | None = None,
          _now: Callable[[], float] = time.monotonic) -> bool:
    """判定并原子记录：窗口 RETRY_BUDGET_WINDOW_S 内同 caller 的本次 spend
    计入后是否仍 ≤ retry_budget_per_minute（site_config，缺省 50）。

    True=可继续（重试照旧）；False=预算耗尽——调用方必须按不可重试快速
    失败并 log.warning 一条「重试预算耗尽」。caller 名="llm"/"search"/"hot"。
    """
    limit = _limit_for(db)
    now = _now()
    with _lock:
        window = _spends.setdefault(caller, deque())
        window.append(now)
        horizon = now - RETRY_BUDGET_WINDOW_S
        while window and window[0] < horizon:
            window.popleft()
        return len(window) <= limit
