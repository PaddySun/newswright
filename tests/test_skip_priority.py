"""调度跳过原因优先级表测试：多条件同时命中时按优先级取第一个。

优先级（单一判定函数，调度入队与统计展示共用）：disabled > direction_expired >
rate_limited > keyword_exhausted > hard_failed/suspect_probe > backoff >
interval_not_due；"probe" 表示处于退避/疑似状态但本轮是探测窗口（放行抓取）。
设计依据见 docs/design-index.md「DT-6」「AC-20.3」。
"""
from datetime import datetime, timedelta, timezone

from app.models import Direction, Source
from app.pipeline.skip_policy import skip_reason

NOW = datetime.now(timezone.utc)


def _src(**kw) -> Source:
    defaults = dict(direction_id=1, url="https://ex/s", type="rss", enabled=True)
    defaults.update(kw)
    return Source(**defaults)


def _dir(status: str = "active") -> Direction:
    d = Direction(name=f"方向-{status}", prompt="p", threshold=60)
    d.status = status
    return d


def test_priority_disabled_first():
    """停用源无论叠加多少其他条件，一律 reason=disabled。"""
    src = _src(enabled=False, failure_level="hard_failed",
               rate_limited_until=NOW + timedelta(minutes=30))
    assert skip_reason(src, _dir(), now=NOW) == "disabled"


def test_priority_direction_expired_before_rate_limit():
    """方向已过期（temp TTL 到期）优先于限流跳过。"""
    src = _src(rate_limited_until=NOW + timedelta(minutes=30))
    assert skip_reason(src, _dir("expired"), now=NOW) == "direction_expired"


def test_priority_rate_limited_before_keyword_and_failure():
    """限流期内优先于关键词零收益与失效状态。"""
    src = _src(rate_limited_until=NOW + timedelta(minutes=30),
               keyword_limited_until=NOW + timedelta(minutes=30),
               failure_level="hard_failed")
    assert skip_reason(src, _dir(), now=NOW) == "rate_limited"


def test_priority_keyword_exhausted_before_failure_state():
    """关键词零收益限速优先于失效状态。"""
    src = _src(keyword_limited_until=NOW + timedelta(minutes=30),
               failure_level="hard_failed")
    assert skip_reason(src, _dir(), now=NOW) == "keyword_exhausted"


def test_priority_hard_failed_before_backoff():
    """硬失效（停抓不重试）优先于通用退避——硬失效无探测窗口。"""
    src = _src(failure_level="hard_failed", backoff_failures=10)
    assert skip_reason(src, _dir(), now=NOW) == "hard_failed"


def test_priority_suspect_probe_window():
    """疑似失效：探测窗口轮放行（probe），其余轮跳过（suspect_probe）。"""
    src = _src(failure_level="suspect", backoff_skips=0)
    assert skip_reason(src, _dir(), now=NOW) == "probe"  # 窗口轮
    src2 = _src(failure_level="suspect", backoff_skips=1)
    assert skip_reason(src2, _dir(), now=NOW) == "suspect_probe"


def test_priority_backoff_and_probe_window():
    """通用退避：达阈值跳过；探测窗口轮放行（probe）。"""
    src = _src(backoff_failures=3, backoff_skips=1)
    assert skip_reason(src, _dir(), now=NOW) == "backoff"
    src2 = _src(backoff_failures=3, backoff_skips=0)
    assert skip_reason(src2, _dir(), now=NOW) == "probe"


def test_priority_interval_not_due_last():
    """源级间隔未到期是最低优先级：仅当无其他条件命中时才生效。"""
    src = _src(source_config={"interval_minutes": 60},
               last_fetched_at=NOW - timedelta(minutes=10))
    assert skip_reason(src, _dir(), now=NOW) == "interval_not_due"
    # 与退避叠加时间隔不生效（退避优先；skips=1 非探测窗口）
    src2 = _src(source_config={"interval_minutes": 60},
                last_fetched_at=NOW - timedelta(minutes=10),
                backoff_failures=5, backoff_skips=1)
    assert skip_reason(src2, _dir(), now=NOW) == "backoff"


def test_normal_source_executes():
    """全部条件未命中 → None（正常执行）。"""
    src = _src()
    assert skip_reason(src, _dir(), now=NOW) is None


def test_score_runonce_entry(auth_client):
    """score 独立 run-once 入口回归：单独触发打分轮（不经 fetch 链）。"""
    # 既有端点路径不加 /api 前缀（前缀统一属后续契约里程碑）
    r = auth_client.post("/scheduler/run-once/score")
    assert r.status_code == 200
    assert "score" in r.json()


def test_rate_limited_boundary_inclusive_expiry():
    """限流期限到点即解：until 恰等于当前时刻时不再按 rate_limited 跳过
    （限流期语义是 now < until）。"""
    src = _src(rate_limited_until=NOW)
    assert skip_reason(src, _dir(), now=NOW) is None


def test_keyword_limited_boundary_inclusive_expiry():
    """关键词限速期限到点即解：until 恰等于当前时刻时不再按
    keyword_exhausted 跳过（与限流期同一 until 期间语义）。"""
    src = _src(keyword_limited_until=NOW)
    assert skip_reason(src, _dir(), now=NOW) is None


def test_naive_rate_limited_until_compared_as_utc():
    """库里取回的 naive 限流期限（SQLite 去 tz）按 UTC 归一参与比较：
    未到期的 naive until 照常判 rate_limited，不因时区形态崩溃。"""
    naive_future = (NOW + timedelta(minutes=30)).replace(tzinfo=None)
    src = _src(rate_limited_until=naive_future)
    assert skip_reason(src, _dir(), now=NOW) == "rate_limited"
