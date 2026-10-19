"""per-netloc 最小间隔节流（BE-4/TG-2）：预约制等待 + 单请求等待上限。

源意（D6）：RSS 补抓原文一轮同域连发 N 次现无任何域控——本项目最近似
morningdeck HN 被拉黑事故的形态。预约制（锁内领时间片）保证并发线程
（fetch/score/hot 多 job 并行是既有形态）按序排队不插队；等待超上限快速
失败（ThrottledError 继承 httpx.TransportError——被既有 except httpx.HTTPError
捕获面零改收编，enrich 失败保留摘要天然契合、下轮重试幂等）。

GET-only（与 SSRF hook 同依据）：POST 面全部是自有 API 域名，零误伤是
设计而非遗漏；netloc 取 request.url.host（小写域）。池化面（post_json/
get_json）不挂本钩子——JSON API 域全自有，挂上反会把热榜聚合域掐进单一
全局间隔。

设计依据见 docs/design-index.md「TG-2」（BE-4 增补）。
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import httpx
from sqlalchemy.orm import Session

from ..siteconfig import get_config

log = logging.getLogger(__name__)

# 代码缺省常量（与 siteconfig.DEFAULTS 同值）：db=None（工厂无会话）时回退。
DEFAULT_MIN_INTERVAL_S = 3.0
DEFAULT_MAX_WAIT_S = 30.0


class ThrottledError(httpx.TransportError):
    """节流快速失败：同域等待队列已超单请求等待上限。继承 httpx.TransportError
    ——既有 except httpx.HTTPError 捕获面零改收编（同域连发约 10 条内排队成功、
    其余快速失败留待下轮，自限不拉长轮周期）。"""


# 进程级预约表：netloc → 已预约的下一时间片（time.monotonic 时刻）。
_next_slot: dict[str, float] = {}
_lock = threading.Lock()


def _reset_for_tests() -> None:
    """复位进程级预约表（判例纪律：每测试文件 fixture 复位）。"""
    with _lock:
        _next_slot.clear()


def wait_for_slot(
    netloc: str,
    *,
    min_interval_s: float,
    max_wait_s: float,
    _clock: Callable[[], float] = time.monotonic,
    _sleep: Callable[[float], None] = time.sleep,
) -> float:
    """预约制等待同域时间片，返回实际等待秒数（测试注入 clock/sleep 零真 sleep）。

    锁内领号：target = max(前驱槽 + interval, now)（首访无前驱即取 now——
    首请求零等待；并发线程按领号顺序获得间隔递增的槽位，不插队）。需等待
    > max_wait_s 则抛 ThrottledError 且**不占槽**——快速失败者不消耗未来
    时间片，防同轮扇出把下一轮也锁死；否则锁外 sleep 至预约点。
    """
    if min_interval_s <= 0:
        return 0.0
    with _lock:
        now = _clock()
        prev = _next_slot.get(netloc)
        target = now if prev is None else max(prev + min_interval_s, now)
        wait = target - now
        if wait > max_wait_s:
            raise ThrottledError(
                f"节流快速失败：{netloc} 的等待队列已超单请求上限 {max_wait_s}s"
                f"（最小间隔 {min_interval_s}s；site_config netloc_min_interval_s/"
                f"netloc_throttle_domains/netloc_throttle_max_wait_s 可调）")
        _next_slot[netloc] = target
    if wait > 0:
        _sleep(wait)
    return wait


def _num_config(db: Session, key: str, default: float) -> float:
    raw = get_config(db, key)
    if raw is None:
        return default
    try:
        return max(float(raw), 0.0)
    except (TypeError, ValueError):
        log.warning("%s 非法值 %r，回退缺省 %s", key, raw, default)
        return default


def _min_interval_for(db: Session, netloc: str) -> float:
    """该 netloc 的最小间隔：netloc_throttle_domains per-netloc 覆盖 →
    netloc_min_interval_s 全局缺省（非法值 warn 回退，照 hub 判例）。"""
    overrides = get_config(db, "netloc_throttle_domains")
    if isinstance(overrides, dict):
        raw = overrides.get(netloc)
        if raw is not None:
            try:
                return max(float(raw), 0.0)
            except (TypeError, ValueError):
                log.warning("netloc_throttle_domains[%s] 非法值 %r，忽略覆盖回退全局",
                            netloc, raw)
    return _num_config(db, "netloc_min_interval_s", DEFAULT_MIN_INTERVAL_S)


def throttle_request(request: httpx.Request, *, db: Session | None = None) -> None:
    """采集 GET 面 per-netloc 节流 hook（GET-only；工厂经 functools.partial
    预绑定 db——读 site_config 三键，db=None 时用代码缺省常量）。"""
    if request.method != "GET":
        return
    netloc = request.url.host or ""
    if not netloc:
        return
    if db is None:
        interval, max_wait = DEFAULT_MIN_INTERVAL_S, DEFAULT_MAX_WAIT_S
    else:
        interval = _min_interval_for(db, netloc)
        max_wait = _num_config(db, "netloc_throttle_max_wait_s", DEFAULT_MAX_WAIT_S)
    wait_for_slot(netloc, min_interval_s=interval, max_wait_s=max_wait)
