"""月度计费对账窗口测试：_month_range 的月首/跨年/右端边界契约。

覆盖口径（ADR-8 月度计费对账 + 技术书 §3 /api/settings/usage/reconcile）：
- 窗口起点 = 当月 1 日零点（「当月起」语义：月首日不是 2 日）；
- 全部 12 个月合法（01 与 12 月不得被格式校验误拒），12 月跨年闭端 = 次年 1 月 1 日；
- 13 月拒绝（格式校验域覆盖 len==2 的越界月份，不得崩溃成 500）；
- 窗口右端 = 次月 1 日（不跳月、不含次月 1 日全天）。
设计依据见 docs/design-index.md「ADR-8」。
"""
from datetime import datetime

import pytest

from app.api.routes import _month_range


def test_month_range_starts_at_first_day_zero_hour():
    """窗口起点 = 当月 1 日 00:00（月首日语义；值比较不含 tz 标签——渲染同串）。"""
    start, _ = _month_range("2026-09")
    assert start.replace(tzinfo=None) == datetime(2026, 9, 1)


def test_month_range_january_valid():
    """01 月是合法月份（mon==1 不得被误拒）。"""
    assert _month_range("2026-01") is not None


@pytest.mark.xfail(reason="生产缺陷（C3-3 呈统筹）：12 月分支 year+1 对字符串 year 做 int 拼接 "
                   "抛 TypeError——12 月对账请求 500。缺陷修复后本测试应转 XPASS 提醒移除标记",
                   strict=True)
def test_month_range_december_valid_and_spans_year():
    """12 月合法且闭端跨年：end = 次年 1 月 1 日（值比较不含 tz 标签）。"""
    rng = _month_range("2026-12")
    assert rng is not None
    start, end = rng
    assert start.replace(tzinfo=None) == datetime(2026, 12, 1)
    assert end.replace(tzinfo=None) == datetime(2027, 1, 1)


def test_month_range_thirteenth_month_rejected():
    """13 月拒绝（越界月份回 None → 400，不崩溃）。"""
    assert _month_range("2026-13") is None


def test_month_range_end_is_next_month_first_day():
    """右端 = 次月 1 日 00:00（不跳月、不是次月 2 日；值比较不含 tz 标签）。"""
    _, end = _month_range("2026-10")
    assert end.replace(tzinfo=None) == datetime(2026, 11, 1)
