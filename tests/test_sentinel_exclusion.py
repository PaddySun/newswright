"""哨兵分母出清与旧账修正测试（BE-3/AC-3）：is_stale_dead 边界、陈旧死源
出清后比例回落（哨兵+stats 两处同构）、rate_limited_until 过期旧账不再计入、
stale_days 可配。

设计依据见 docs/design-index.md「SM-4」（BE-3 增补）。
"""
from datetime import datetime, timedelta, timezone

from app.models import Direction, Source
from app.notify.triggers import check_collective_sentinel
from app.observability import pipeline_stats_payload
from app.pipeline.skip_policy import is_stale_dead
from app.siteconfig import DEFAULTS, set_config

NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)


def _dead(direction_id: int, *, since_days: float | None) -> Source:
    src = Source(direction_id=direction_id, url=f"https://stale.example/rss",
                 failure_level="hard_failed" if since_days is not None else "none")
    if since_days is not None:
        src.failure_since = NOW - timedelta(days=since_days)
    return src


# ---------- 纯函数 is_stale_dead 边界 ----------


def test_is_stale_dead_boundary_strictly_greater():
    """超 stale_days 才出清：31d 出清、恰 30d 与 29d 不出清（判据 > 严格）。"""
    assert is_stale_dead(_dead(1, since_days=31), now=NOW, stale_days=30) is True
    assert is_stale_dead(_dead(1, since_days=30), now=NOW, stale_days=30) is False
    assert is_stale_dead(_dead(1, since_days=29), now=NOW, stale_days=30) is False


def test_is_stale_dead_only_hard_failed_with_since():
    """suspect 永不出清（照进降级桶）；failure_since 缺失的历史死源保守不出清。"""
    suspect = Source(direction_id=1, url="u", failure_level="suspect")
    suspect.failure_since = NOW - timedelta(days=100)
    assert is_stale_dead(suspect, now=NOW, stale_days=30) is False
    no_since = Source(direction_id=1, url="u", failure_level="hard_failed")
    assert is_stale_dead(no_since, now=NOW, stale_days=30) is False


def test_stale_days_default_registered():
    """siteconfig.DEFAULTS 同步钉面：sentinel_exclude_stale_days 缺省 30。"""
    assert DEFAULTS["sentinel_exclude_stale_days"] == 30


# ---------- 聚合哨兵（triggers 侧） ----------


def _seed_sources(db, specs) -> Direction:
    """specs: [(failure_level, since_days|None, rate_until_delta|None)]。"""
    d = Direction(name="哨兵出清方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    for i, (level, since, rate_delta) in enumerate(specs):
        src = Source(direction_id=d.id, url=f"https://s{i}.example/rss",
                     failure_level=level)
        if since is not None:
            src.failure_since = NOW - timedelta(days=since)
        if rate_delta is not None:
            src.rate_limited_until = NOW + timedelta(hours=rate_delta)
        db.add(src)
    db.commit()
    return d


def test_collective_sentinel_excludes_stale_dead(db_session):
    """回归③：failure_since 31d 死源不进降级桶——两个死源（一陈旧一新鲜）
    出清后 1/3 未过半 → 哨兵回落 healthy（比例只涨不跌的漂移修复）。"""
    _seed_sources(db_session, [
        ("hard_failed", 31, None),   # 陈旧死源：出清
        ("hard_failed", 2, None),    # 新鲜死源：照进
        ("none", None, None),
    ])
    out = check_collective_sentinel(db_session, now=NOW)
    assert out["sent"] is False and out["reason"] == "healthy"


def test_collective_sentinel_counts_fresh_dead(db_session):
    """对照组：两个新鲜死源（2d/5d）2/3 超半数 → sustained_1（既有判定面不变）。"""
    _seed_sources(db_session, [
        ("hard_failed", 2, None),
        ("hard_failed", 5, None),
        ("none", None, None),
    ])
    out = check_collective_sentinel(db_session, now=NOW)
    assert out["sent"] is False and out["reason"] == "sustained_1"


def test_expired_rate_limit_not_counted_sentinel(db_session):
    """回归④（哨兵侧）：rate_limited_until 已过期的旧账不再计入降级桶
    （补 now 比较——过期即出桶）。"""
    _seed_sources(db_session, [("none", None, -1)])  # 1 小时前到期
    out = check_collective_sentinel(db_session, now=NOW)
    assert out["sent"] is False and out["reason"] == "healthy"


def test_active_rate_limit_still_counted_sentinel(db_session):
    """未到期 rate_limited_until 照进降级桶（now 比较只剔旧账，不吞现行降频）。"""
    _seed_sources(db_session, [("none", None, 1)])  # 1 小时后才到期
    out = check_collective_sentinel(db_session, now=NOW)
    assert out["reason"] == "sustained_1"  # 1/1 超半数


def test_stale_days_configurable(db_session):
    """stale_days 读 site_config：覆写 7 → 8d 死源出清、5d 死源照进。"""
    set_config(db_session, "sentinel_exclude_stale_days", 7)
    _seed_sources(db_session, [
        ("hard_failed", 8, None),   # 超 7d：出清
        ("hard_failed", 5, None),   # 未超：照进
    ])
    out = check_collective_sentinel(db_session, now=NOW)
    assert out["sent"] is False and out["reason"] == "healthy"


# ---------- 体检载荷（observability 侧，同构） ----------


def _seed_stats_sources(db, specs) -> None:
    d = Direction(name="体检出清方向", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    fresh = datetime.now(timezone.utc)
    for i, (level, since, rate_delta) in enumerate(specs):
        src = Source(direction_id=d.id, url=f"https://stat{i}.example/rss",
                     failure_level=level)
        if since is not None:
            src.failure_since = fresh - timedelta(days=since)
        if rate_delta is not None:
            src.rate_limited_until = fresh + timedelta(hours=rate_delta)
        db.add(src)
    db.commit()


def test_stats_degraded_excludes_stale_dead(db_session):
    """stats 载荷同构出清：31d 死源 degraded_sources_count 回落为 0（分母
    enabled 不变、源状态本体不变——后台仍可见 hard_failed）。"""
    _seed_stats_sources(db_session, [("hard_failed", 31, None)])
    body = pipeline_stats_payload(db_session)
    assert body["degraded_sources_count"] == 0
    assert body["total_enabled_sources"] == 1


def test_stats_degraded_counts_fresh_dead(db_session):
    """stats 载荷对照：新鲜死源（2d）照计入（既有 R7 钉面行为保持）。"""
    _seed_stats_sources(db_session, [("hard_failed", 2, None)])
    body = pipeline_stats_payload(db_session)
    assert body["degraded_sources_count"] == 1


def test_expired_rate_limit_not_counted_stats(db_session):
    """回归④（stats 侧）：过期 rate_limited_until 旧账不再计入
    degraded_sources_count。"""
    _seed_stats_sources(db_session, [("none", None, -1)])
    body = pipeline_stats_payload(db_session)
    assert body["degraded_sources_count"] == 0


def test_stats_active_rate_limit_still_counted(db_session):
    """stats 载荷对照：未到期 rate_limited_until 照计入。"""
    _seed_stats_sources(db_session, [("none", None, 1)])
    body = pipeline_stats_payload(db_session)
    assert body["degraded_sources_count"] == 1
