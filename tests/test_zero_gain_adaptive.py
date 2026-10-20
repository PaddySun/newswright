"""RSS/web 源零收益自适应测试（BE-6/AC-3，R3.8）：健康但连续无新增 → 拉长
抓取间隔（读时放大，不动 source_config 用户值）。

划界（BE-3 定案第三面，注释同款写进实现）：
- 零收益（本批 HG-3）：error is None and not not_modified and inserted == 0
  ——健康源（rss/web）内容无新增；not_modified（etag 协商健康低频站）、
  error/rate_limited（BE-3 失败域/D13 限流域）轮不计数不放大；
- 失败（BE-3/SM-x）：suspect/hard_failed 阶梯管「抓取失败/空内容」；
- 搜索零收益（D20）：keyword_zero_rounds 只对 type=search，恢复事件不同
  （hot 批次更新/手工刷新/提示词升版），与 RSS/web 内容零收益互不侵扰。

读时放大（HG-3）：skip_reason interval 分支 effective = interval_minutes ×
2^zero_gain_level（level 封顶 ZERO_GAIN_MAX_LEVEL=4=×16）；reason 展示
"interval_not_due:{effective}m" 自然反映放大值；无 interval 配置的源不受
影响（本就不进该分支）。
设计依据见 docs/design-index.md「HG-3」。
"""
import types
from datetime import datetime, timedelta, timezone

from app.models import Direction, Source
from app.pipeline.runner import _update_source_health, enqueue_fetch_round
from app.pipeline.skip_policy import skip_reason

NOW = datetime.now(timezone.utc)


def _stats(**kw) -> types.SimpleNamespace:
    """最小抓取统计（形态对齐采集器产出的 SourceFetchStats 消费面）。"""
    base = dict(error=None, feed_entries=0, inserted=0, not_modified=False,
                rate_limited=False, retry_after=None, extra={})
    base.update(kw)
    return types.SimpleNamespace(**base)


_seq = iter(range(1000))


def _mk_source(db, *, type_: str = "rss", interval_minutes=None, **kw) -> Source:
    n = next(_seq)
    d = Direction(name=f"零收益方向-{type_}-{n}", prompt="p", threshold=60)
    db.add(d)
    db.commit()
    src = Source(direction_id=d.id, url=f"https://zg-{type_}-{n}.example/feed",
                 type=type_, enabled=True, **kw)
    if interval_minutes is not None:
        src.source_config = {"interval_minutes": interval_minutes}
    db.add(src)
    db.commit()
    return src


# ---------- 计数与升档（_update_source_health 新段） ----------

def test_zero_gain_round_counts(db_session):
    """健康零收益轮（error None/非 304/inserted 0）→ zero_gain_rounds +1。"""
    src = _mk_source(db_session, zero_gain_rounds=0)
    _update_source_health(db_session, src, _stats(feed_entries=5, inserted=0))
    assert src.zero_gain_rounds == 1 and src.zero_gain_level == 0


def test_six_zero_rounds_level_up_and_recount(db_session):
    """rounds 达阈值 6 → level+1 且 rounds 归零重计（此后每 6 轮再升一档）。"""
    src = _mk_source(db_session, zero_gain_rounds=5)
    _update_source_health(db_session, src, _stats(feed_entries=5, inserted=0))
    assert src.zero_gain_rounds == 0 and src.zero_gain_level == 1


def test_gain_clears_both_counters(db_session):
    """有收益轮（inserted > 0）→ rounds/level 双清零。"""
    src = _mk_source(db_session, zero_gain_rounds=3, zero_gain_level=2)
    _update_source_health(db_session, src, _stats(feed_entries=5, inserted=2))
    assert src.zero_gain_rounds == 0 and src.zero_gain_level == 0


def test_not_modified_round_not_counted(db_session):
    """304 协商轮不计数（健康低频站 etag 形态剔出）。"""
    src = _mk_source(db_session, zero_gain_rounds=2)
    _update_source_health(db_session, src, _stats(not_modified=True))
    assert src.zero_gain_rounds == 2 and src.zero_gain_level == 0


def test_error_round_not_counted(db_session):
    """失败轮不计数（BE-3 失败域——零收益≠失败）。"""
    src = _mk_source(db_session, zero_gain_rounds=2)
    _update_source_health(db_session, src,
                          _stats(error="ConnectError: refused", inserted=0))
    assert src.zero_gain_rounds == 2 and src.zero_gain_level == 0


def test_rate_limited_round_not_counted(db_session):
    """429 限流轮不计数（D13 域自管档位）。"""
    src = _mk_source(db_session, zero_gain_rounds=2)
    _update_source_health(db_session, src,
                          _stats(rate_limited=True, retry_after="60"))
    assert src.zero_gain_rounds == 2 and src.zero_gain_level == 0


def test_level_capped_at_max(db_session):
    """level 封顶 ZERO_GAIN_MAX_LEVEL=4（×16），到达后不再升档。"""
    src = _mk_source(db_session, zero_gain_rounds=5, zero_gain_level=4)
    _update_source_health(db_session, src, _stats(feed_entries=5, inserted=0))
    assert src.zero_gain_rounds == 0 and src.zero_gain_level == 4


def test_rss_and_web_channels_same_criterion(db_session):
    """两通道判据同轨：rss 与 web 源的健康零收益轮同样计数（判据面
    error/not_modified/inserted 双通道通吃，无 type 分叉）。"""
    rss = _mk_source(db_session, type_="rss", zero_gain_rounds=1)
    web = _mk_source(db_session, type_="web", zero_gain_rounds=1)
    _update_source_health(db_session, rss, _stats(feed_entries=5, inserted=0))
    _update_source_health(db_session, web, _stats(feed_entries=5, inserted=0))
    assert rss.zero_gain_rounds == 2 and web.zero_gain_rounds == 2


def test_search_source_not_in_zero_gain_domain(db_session):
    """搜索源零收益归 D20 域（keyword_zero_rounds），不进本段计数
    （划界：搜索零收益≠RSS/web 内容零收益）。"""
    src = _mk_source(db_session, type_="search", zero_gain_rounds=0)
    _update_source_health(db_session, src, _stats(inserted=0))
    assert src.zero_gain_rounds == 0


# ---------- 读时放大（skip_policy interval 分支 + 入队展示） ----------

def test_level_one_doubles_interval(db_session):
    """level=1 → interval 放大 ×2：base 30m 源抓后 45min 仍 not due。"""
    src = _mk_source(db_session, interval_minutes=30, zero_gain_level=1,
                     last_fetched_at=NOW - timedelta(minutes=45))
    assert skip_reason(src, None, now=NOW) == "interval_not_due"
    # level 0 时 45min > 30m 本应 due——放大生效的对照组
    src0 = _mk_source(db_session, interval_minutes=30, zero_gain_level=0,
                      last_fetched_at=NOW - timedelta(minutes=45))
    assert skip_reason(src0, None, now=NOW) is None


def test_interval_due_within_amplified_window(db_session):
    """放大后到期照常放行：base 30m × 2^1 = 60m，抓后 61min → due（None）。"""
    src = _mk_source(db_session, interval_minutes=30, zero_gain_level=1,
                     last_fetched_at=NOW - timedelta(minutes=61))
    assert skip_reason(src, None, now=NOW) is None


def test_level_four_sixteen_x_cap(db_session):
    """level=4 封顶 ×16：base 30m → 480m；抓后 8h（480m）整点已过、
    7h 未到——上下沿双向断言。"""
    src = _mk_source(db_session, interval_minutes=30, zero_gain_level=4,
                     last_fetched_at=NOW - timedelta(minutes=420))
    assert skip_reason(src, None, now=NOW) == "interval_not_due"
    src_due = _mk_source(db_session, interval_minutes=30, zero_gain_level=9,
                         last_fetched_at=NOW - timedelta(minutes=481))
    assert skip_reason(src_due, None, now=NOW) is None  # level>4 按 4 计


def test_source_config_value_untouched(db_session):
    """读时放大不动 source_config 用户值：interval_minutes 落库值保持 30。"""
    src = _mk_source(db_session, interval_minutes=30, zero_gain_level=3)
    skip_reason(src, None, now=NOW)
    assert src.source_config["interval_minutes"] == 30


def test_no_interval_source_unaffected(db_session):
    """无 interval 配置的源零影响（本就不进该分支）：level 再高也放行。"""
    src = _mk_source(db_session, zero_gain_level=3,
                     last_fetched_at=NOW - timedelta(minutes=1))
    assert skip_reason(src, None, now=NOW) is None


def test_enqueue_display_shows_effective_minutes(db_session):
    """入队展示自然反映放大值：level=2 的 30m 源 → reason
    "interval_not_due:120m"（既有格式，值为 effective）。"""
    src = _mk_source(db_session, interval_minutes=30, zero_gain_level=2,
                     last_fetched_at=NOW - timedelta(minutes=10))
    round_task = enqueue_fetch_round(db_session, triggered_by="test")
    skipped = round_task.payload["skipped_backoff"]
    entry = next(s for s in skipped if s["source_id"] == src.id)
    assert entry["reason"] == "interval_not_due:120m"
