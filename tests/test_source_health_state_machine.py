"""来源健康状态机边界测试：失效三级判别的计数推进/清零、动态降频档位阶梯
与恢复节奏、限流轮与退避计数的隔离、探测节奏保持、异常轮不误清零。

直接以最小抓取统计驱动 _update_source_health 单一入口，钉死各判定域的
边界行为。设计依据见 docs/design-index.md「DT-1」「AC-04.2」「AC-04.3」
「AC-04.4」「AC-05.5」「D13」「AC-20.3」「D20」。
"""
import types
from datetime import datetime, timedelta, timezone

import pytest

import app.pipeline.runner as runner_mod
from app.models import Direction, Source
from app.pipeline.runner import _update_source_health, fetch_round


def _stats(**kw) -> types.SimpleNamespace:
    """最小抓取统计（形态对齐采集器产出的 SourceFetchStats 消费面）。"""
    base = dict(error=None, feed_entries=0, inserted=0, not_modified=False,
                rate_limited=False, retry_after=None, extra={})
    base.update(kw)
    return types.SimpleNamespace(**base)


@pytest.fixture()
def rss_source(db_session):
    d = Direction(name="健康状态机方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://feeds.example/hsm.xml", type="rss")
    db_session.add(src)
    db_session.commit()
    return src


@pytest.fixture()
def search_source(db_session):
    d = Direction(name="健康状态机搜索方向", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="search://fakeprov/健康词", type="search",
                 source_config={"keyword": "健康词", "provider": "fakeprov"})
    db_session.add(src)
    db_session.commit()
    return src


def _hard_error(status: int) -> types.SimpleNamespace:
    return _stats(error=f"HTTPStatusError: HTTP {status}", extra={"http_status": status})


def test_success_round_zeroes_failure_counters(db_session, rss_source):
    """任一非空成功轮：连续硬失效与空轮计数一并清零（不只 failure_level 复位）。"""
    src = rss_source
    src.hard_failures = 2
    src.empty_rounds = 2
    db_session.commit()
    _update_source_health(db_session, src, _stats(feed_entries=5))
    src = db_session.merge(src)
    assert src.hard_failures == 0 and src.empty_rounds == 0


def test_network_error_round_not_counted_as_empty(db_session, rss_source):
    """网络/其他错误轮：只进退避计数，不进空轮侧计数、不标疑似失效。"""
    src = rss_source
    src.empty_rounds = 2
    db_session.commit()
    _update_source_health(db_session, src, _stats(error="ReadTimeout: boom"))
    src = db_session.merge(src)
    assert src.failure_level == "none"
    assert src.empty_rounds == 2 and src.backoff_failures == 1


def test_search_zero_yield_rounds_not_in_suspect_domain(db_session, search_source):
    """搜索源连续零收益空轮：不进失效三级判别（那是 RSS 空轮判别域），
    零收益归关键词边际降频管，failure_level 保持 none。"""
    src = search_source
    stats = _stats(inserted=0)
    for _ in range(3):
        _update_source_health(db_session, src, stats)
    src = db_session.merge(src)
    assert src.failure_level == "none"


def test_hard_failed_not_downgraded_by_empty_rounds(db_session, rss_source):
    """硬失效源再遇空轮：failure_level 保持 hard_failed（不得静默降级为
    suspect——状态机里 hard 是人工处理终态）。"""
    src = rss_source
    src.failure_level = "hard_failed"
    src.empty_rounds = 3
    db_session.commit()
    _update_source_health(db_session, src, _stats())
    src = db_session.merge(src)
    assert src.failure_level == "hard_failed"


@pytest.mark.parametrize("status", [404, 410])
def test_hard_fail_status_list(db_session, rss_source, status):
    """连续 404/410 各 3 轮均判硬失效（状态名单钉死 404/403/410）。"""
    src = rss_source
    for _ in range(3):
        _update_source_health(db_session, src, _hard_error(status))
    src = db_session.merge(src)
    assert src.failure_level == "hard_failed"


def test_single_hard_error_below_threshold_stays_none(db_session, rss_source):
    """仅 1 轮 403：不标硬失效（阈值=连续 ≥3 轮）。"""
    src = rss_source
    _update_source_health(db_session, src, _hard_error(403))
    src = db_session.merge(src)
    assert src.failure_level == "none"


def test_non_hard_error_interrupts_hard_streak(db_session, rss_source):
    """非硬失效错误打断连续硬失效序列：403、超时、403、403 四轮后
    仍不得判硬失效（序列要求连续）。"""
    src = rss_source
    for stats in (_hard_error(403), _stats(error="ReadTimeout: x"),
                  _hard_error(403), _hard_error(403)):
        _update_source_health(db_session, src, stats)
        src = db_session.merge(src)
        assert src.failure_level == "none"


def test_429_rounds_escalate_level(db_session, rss_source):
    """连续两轮 429：档位逐轮 +1（间隔倍增的档位推进面）。"""
    src = rss_source
    for _ in range(2):
        _update_source_health(db_session, src, _stats(rate_limited=True))
    src = db_session.merge(src)
    assert src.rate_level == 2


def test_new_limit_resets_ok_counter_and_full_cycle(db_session, rss_source):
    """限流轮把正常轮计数清零：期满后须连续 2 轮正常才降档；解除后再次
    限流，计数从零重新起算（不得残留）。"""
    src = rss_source
    now = datetime.now(timezone.utc)
    # 周期一：429 进 1 档 → 期满 → 1 轮正常尚不降档 → 第 2 轮降档解除
    src.rate_level = 0
    src.rate_ok_rounds = 0
    src.rate_limited_until = None
    db_session.commit()
    _update_source_health(db_session, src, _stats(rate_limited=True))
    src = db_session.merge(src)
    assert src.rate_level == 1 and src.rate_ok_rounds == 0
    src.rate_limited_until = now - timedelta(minutes=1)
    db_session.commit()
    _update_source_health(db_session, src, _stats(feed_entries=3))
    src = db_session.merge(src)
    assert src.rate_level == 1 and src.rate_ok_rounds == 1  # 第 1 轮正常：尚不降档
    _update_source_health(db_session, src, _stats(feed_entries=3))
    src = db_session.merge(src)
    assert src.rate_level == 0 and src.rate_limited_until is None
    # 周期二：再次 429 后仅 1 轮正常不得降档
    _update_source_health(db_session, src, _stats(rate_limited=True))
    src = db_session.merge(src)
    assert src.rate_level == 1 and src.rate_ok_rounds == 0
    src.rate_limited_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    _update_source_health(db_session, src, _stats(feed_entries=3))
    src = db_session.merge(src)
    assert src.rate_level == 1 and src.rate_ok_rounds == 1


def test_429_without_retry_after_sets_future_until(db_session, rss_source):
    """429 无 Retry-After：按当前档位记录未来限流期限（期间调度跳过）。"""
    src = rss_source
    before = datetime.now(timezone.utc)
    _update_source_health(db_session, src, _stats(rate_limited=True))
    src = db_session.merge(src)
    assert src.rate_limited_until is not None
    until = src.rate_limited_until if src.rate_limited_until.tzinfo else src.rate_limited_until.replace(tzinfo=timezone.utc)
    assert until > before


def test_429_ladder_interval_scales_with_level(db_session, rss_source):
    """1 档源再遇 429：限流期限按升档后档位取 60 分钟（倍增阶梯）。"""
    src = rss_source
    src.rate_level = 1
    db_session.commit()
    before = datetime.now(timezone.utc)
    _update_source_health(db_session, src, _stats(rate_limited=True))
    src = db_session.merge(src)
    assert src.rate_level == 2
    until = src.rate_limited_until if src.rate_limited_until.tzinfo else src.rate_limited_until.replace(tzinfo=timezone.utc)
    delta = until - before
    assert timedelta(minutes=59) <= delta <= timedelta(minutes=61)


def test_naive_rate_limited_until_recovery(db_session, rss_source):
    """库里取回的 naive 限流期限（SQLite 去 tz）：恢复判定按 UTC 归一，
    期满后正常轮计入恢复计数，不得崩溃。"""
    src = rss_source
    src.rate_level = 1
    src.rate_ok_rounds = 0
    # 模拟 SQLite 取回形态：naive 且墙钟为 UTC（本地时钟 UTC+8，不可混用）
    src.rate_limited_until = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    db_session.commit()
    _update_source_health(db_session, src, _stats(feed_entries=3))
    src = db_session.merge(src)
    assert src.rate_ok_rounds == 1 and src.rate_level == 1


def test_recovery_counts_round_at_limit_boundary(db_session, rss_source, monkeypatch):
    """限流期限到点即解：期限恰等当前时刻的正常轮计入恢复计数
    （限流期语义是 now < until）。"""
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)

    src = rss_source
    src.rate_level = 1
    src.rate_ok_rounds = 0
    src.rate_limited_until = _Frozen.now()
    db_session.commit()
    monkeypatch.setattr(runner_mod, "datetime", _Frozen)
    _update_source_health(db_session, src, _stats(feed_entries=3))
    src = db_session.merge(src)
    assert src.rate_ok_rounds == 1


def test_recovery_steps_down_one_level_with_ladder(db_session, rss_source):
    """2 档源期满恢复：连续 2 轮正常只降 1 档（逐级），限流期限按降后
    档位续期（30 分钟），不得直接解除或崩落。"""
    src = rss_source
    src.rate_level = 2
    src.rate_ok_rounds = 0
    src.rate_limited_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    _update_source_health(db_session, src, _stats(feed_entries=3))
    src = db_session.merge(src)
    assert src.rate_level == 2 and src.rate_ok_rounds == 1
    _update_source_health(db_session, src, _stats(feed_entries=3))
    src = db_session.merge(src)
    assert src.rate_level == 1 and src.rate_ok_rounds == 0
    assert src.rate_limited_until is not None
    until = src.rate_limited_until if src.rate_limited_until.tzinfo else src.rate_limited_until.replace(tzinfo=timezone.utc)
    delta = until - datetime.now(timezone.utc)
    assert timedelta(minutes=29) <= delta <= timedelta(minutes=31)


def test_rate_limited_round_preserves_backoff_counters(db_session, rss_source):
    """429 轮既不计成功也不计失败：退避失败计数与探测轮计数原样保持。"""
    src = rss_source
    src.backoff_failures = 2
    src.backoff_skips = 1
    db_session.commit()
    _update_source_health(db_session, src, _stats(rate_limited=True))
    src = db_session.merge(src)
    assert src.backoff_failures == 2 and src.backoff_skips == 1


def test_probe_recovery_clears_counters(db_session, rss_source):
    """疑似失效源探测轮拿到非空内容：恢复 none 并清零退避计数
    （恢复正常轮询）。"""
    src = rss_source
    src.failure_level = "suspect"
    src.backoff_failures = 3
    src.backoff_skips = 1
    src.empty_rounds = 3
    db_session.commit()
    _update_source_health(db_session, src, _stats(feed_entries=5))
    src = db_session.merge(src)
    assert src.failure_level == "none"
    assert src.backoff_failures == 0 and src.backoff_skips == 0


def test_non_probe_empty_round_clears_backoff(db_session, rss_source):
    """普通源（非探测态）遇 200 空内容轮：该轮无 error 属成功响应，
    退避计数清零；空轮侧另行计数。"""
    src = rss_source
    src.backoff_failures = 3
    db_session.commit()
    _update_source_health(db_session, src, _stats())
    src = db_session.merge(src)
    assert src.backoff_failures == 0
    assert src.empty_rounds == 1  # 空轮侧照常推进


def test_probe_empty_round_preserves_probe_rhythm(db_session, rss_source):
    """疑似失效源探测轮仍空：不算成功——退避与探测轮计数保持，
    探测节奏不被重置。"""
    src = rss_source
    src.failure_level = "suspect"
    src.backoff_failures = 3
    src.backoff_skips = 2
    db_session.commit()
    _update_source_health(db_session, src, _stats())
    src = db_session.merge(src)
    assert src.failure_level == "suspect"
    assert src.backoff_failures == 3 and src.backoff_skips == 2


def test_exception_round_preserves_suspect_state(db_session, rss_source, monkeypatch):
    """抓取异常轮：不误判成功——疑似失效状态与空轮计数保持，
    任务落 FAILED。"""
    src = rss_source
    src.failure_level = "suspect"
    src.empty_rounds = 2
    db_session.commit()

    def _boom(db, s):
        raise ValueError("模拟抓取崩溃")

    monkeypatch.setattr(runner_mod, "_fetch_one", _boom)
    summary = fetch_round(db_session, triggered_by="test")
    src = db_session.merge(src)
    assert src.failure_level == "suspect" and src.empty_rounds == 2
    entry = summary["sources"][0]
    assert entry["status"] == "FAILED" and entry["error"]
