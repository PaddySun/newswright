"""死刑源周探活测试（BE-3/AC-2）：探活窗口纯函数边界（进入满 7 天才首探、
尝试即记账冷却）、最老优先配额放行（入队时记账、worker 崩溃不重探）、探活
失败后冷却（防每轮探活退化）、skip_reason hard_failed 分支零改。

设计依据见 docs/design-index.md「SM-2」「SM-3」（BE-3 增补）。
"""
import types
from datetime import datetime, timedelta, timezone

import pytest

import app.config as config
from app.models import Direction, PipelineTask, Source
from app.pipeline.runner import _update_source_health, enqueue_fetch_round
from app.pipeline.skip_policy import hard_failed_probe_due, skip_reason

NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)


def _dead(direction_id: int, *, since_days: float, probed_days: float | None = None,
          sid: int = 0) -> Source:
    """未入库的最小死刑源形态（纯函数只读属性；enabled 显式置——未入库实例
    的 mapped_column default 不生效）。"""
    src = Source(direction_id=direction_id, url=f"https://probe{sid}.example/rss",
                 enabled=True, failure_level="hard_failed", hard_failures=5)
    src.failure_since = NOW - timedelta(days=since_days)
    if probed_days is not None:
        src.last_probe_at = NOW - timedelta(days=probed_days)
    return src


def _stats(**kw) -> types.SimpleNamespace:
    base = dict(error=None, feed_entries=0, inserted=0, not_modified=False,
                rate_limited=False, retry_after=None, extra={})
    base.update(kw)
    return types.SimpleNamespace(**base)


# ---------- 纯函数 hard_failed_probe_due 边界 ----------


def test_probe_due_requires_full_seven_days_since_entry():
    """进入死刑态满 7 天才首次探：6d 未满不探、恰 7d（≥）与 8d 皆可探。"""
    assert hard_failed_probe_due(_dead(1, since_days=6), now=NOW) is False
    assert hard_failed_probe_due(_dead(1, since_days=7), now=NOW) is True
    assert hard_failed_probe_due(_dead(1, since_days=8), now=NOW) is True


def test_probe_due_cools_down_seven_days_after_attempt():
    """尝试即记账（成败都算）：探活尝试后 7 天内不再 due，满 7 天重新 due
    ——failure_since 不挪作探活时钟（A4 语义）。"""
    assert hard_failed_probe_due(_dead(1, since_days=9, probed_days=3),
                                 now=NOW) is False
    assert hard_failed_probe_due(_dead(1, since_days=9, probed_days=7),
                                 now=NOW) is True
    assert hard_failed_probe_due(_dead(1, since_days=9, probed_days=8),
                                 now=NOW) is True


def test_probe_due_requires_hard_failed_with_since():
    """非 hard_failed 或 failure_since 缺失（历史行）：一律不 due（保守不探）。"""
    suspect = Source(direction_id=1, url="u", failure_level="suspect")
    suspect.failure_since = NOW - timedelta(days=90)
    assert hard_failed_probe_due(suspect, now=NOW) is False
    no_since = Source(direction_id=1, url="u", failure_level="hard_failed")
    assert hard_failed_probe_due(no_since, now=NOW) is False


def test_skip_reason_hard_failed_branch_unchanged():
    """探活窗口不在 skip_reason 内：due 死源仍返 "hard_failed"（配额放行在
    enqueue 层，纯函数不知配额；reason 值域零增）。"""
    src = _dead(1, since_days=9)
    assert hard_failed_probe_due(src, now=NOW) is True
    assert skip_reason(src, None, now=NOW) == "hard_failed"


def test_probe_constants_defaults():
    """常量归位钉面：探活周期 7 天、每轮配额 5（env 可覆写）。"""
    assert config.HARD_FAIL_PROBE_EVERY_DAYS == 7
    assert config.HARD_FAIL_PROBE_QUOTA == 5


# ---------- enqueue 配额放行（最老优先 + 入队即记账） ----------


@pytest.fixture()
def probe_env(db_session):
    d = Direction(name="探活配额方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    return d


def _add_dead(db, direction, *, since_days: float, url_suffix: str) -> Source:
    src = Source(direction_id=direction.id,
                 url=f"https://{url_suffix}.example/rss",
                 failure_level="hard_failed", hard_failures=5,
                 failure_since=datetime.now(timezone.utc) - timedelta(days=since_days))
    db.add(src)
    db.commit()
    return src


def _round_fetch_ids(db, round_task) -> set[int]:
    return {t.payload["source_id"] for t in db.query(PipelineTask)
            .filter_by(kind="fetch").all()
            if (t.payload or {}).get("round_task_id") == round_task.id}


def _settle_rounds(db):
    """防重叠解锁：既有轮次任务全部置终态（既有测试同姿势）。"""
    for t in db.query(PipelineTask).all():
        t.status = "DONE"
    db.commit()


def test_probe_quota_oldest_first(db_session, probe_env, monkeypatch):
    """配额最老优先：两个 due 死源+配额 1 → 老者探（入队 fetch+入队时记账），
    新者照旧 skipped（reason=hard_failed 不新增值）。"""
    monkeypatch.setattr(config, "HARD_FAIL_PROBE_QUOTA", 1)
    old = _add_dead(db_session, probe_env, since_days=40, url_suffix="older")
    new = _add_dead(db_session, probe_env, since_days=30, url_suffix="newer")
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    assert _round_fetch_ids(db_session, rt) == {old.id}
    old = db_session.merge(old)
    assert old.last_probe_at is not None  # 入队时即记账（worker 崩溃不重探）
    new = db_session.merge(new)
    assert new.last_probe_at is None  # 配额外 due 源不记账（下轮仍按序候补）
    entry = next(e for e in rt.payload["skipped_backoff"]
                 if e["source_id"] == new.id)
    assert entry["reason"] == "hard_failed"


def test_probe_records_at_enqueue_survives_worker_crash(db_session, probe_env):
    """入队即记账：探活任务置入后即便 worker 崩溃（状态机从未执行），
    下轮 enqueue 也不再探同一死源（冷却已起算）。"""
    src = _add_dead(db_session, probe_env, since_days=40, url_suffix="crashy")
    rt1 = enqueue_fetch_round(db_session, triggered_by="test")
    assert src.id in _round_fetch_ids(db_session, rt1)
    _settle_rounds(db_session)  # 模拟 worker 崩溃后遗留任务被回收，无状态机推进
    rt2 = enqueue_fetch_round(db_session, triggered_by="test")
    assert src.id not in _round_fetch_ids(db_session, rt2)
    entry = next(e for e in rt2.payload["skipped_backoff"]
                 if e["source_id"] == src.id)
    assert entry["reason"] == "hard_failed"


def test_probe_failure_cooldown_prevents_next_round(db_session, probe_env):
    """回归①：探活失败（404）后 last_probe_at 保留冷却 → 下轮不再探
    （防「每轮探活」退化——探活失败也记账）。"""
    src = _add_dead(db_session, probe_env, since_days=40, url_suffix="cooldown")
    rt1 = enqueue_fetch_round(db_session, triggered_by="test")
    assert src.id in _round_fetch_ids(db_session, rt1)
    # 模拟探活失败：404 轮经状态机（hard_failures+1、level 保持、时钟保留）
    _update_source_health(db_session, src,
                          _stats(error="HTTPStatusError: HTTP 404",
                                 extra={"http_status": 404}))
    src = db_session.merge(src)
    assert src.failure_level == "hard_failed"
    assert src.last_probe_at is not None
    _settle_rounds(db_session)
    rt2 = enqueue_fetch_round(db_session, triggered_by="test")
    assert src.id not in _round_fetch_ids(db_session, rt2)
    entry = next(e for e in rt2.payload["skipped_backoff"]
                 if e["source_id"] == src.id)
    assert entry["reason"] == "hard_failed"


def test_fresh_hard_failed_not_probed(db_session, probe_env):
    """进入死刑态未满 7 天：不进探活（照旧 skipped，时钟不动）。"""
    src = _add_dead(db_session, probe_env, since_days=2, url_suffix="fresh")
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    assert src.id not in _round_fetch_ids(db_session, rt)
    src = db_session.merge(src)
    assert src.last_probe_at is None
    entry = next(e for e in rt.payload["skipped_backoff"]
                 if e["source_id"] == src.id)
    assert entry["reason"] == "hard_failed"


def test_probe_recovery_clears_clock(db_session, probe_env):
    """探活成功（复活）：last_probe_at 一并清空（AC-1 复位路径联动）。"""
    src = _add_dead(db_session, probe_env, since_days=40, url_suffix="revive")
    src.last_probe_at = datetime.now(timezone.utc) - timedelta(days=8)
    db_session.commit()
    _update_source_health(db_session, src, _stats(feed_entries=5))
    src = db_session.merge(src)
    assert src.failure_level == "none" and src.last_probe_at is None
