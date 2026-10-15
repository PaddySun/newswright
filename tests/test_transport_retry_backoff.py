"""传输层退避协商测试（transport.http.retry_delay_ms / parse_retry_after）。

背景（外部服务治理批）：重试退避统一走传输脊协商——服务端 Retry-After 优先
（双形态解析、夹逼 [0, 60s) 开区间），否则随机化指数退避（2**attempt ×
uniform(0.5, 1.5)——确定性退避的同步踩踏形态治理）。RNG 断言纪律：只断言
区间与分布形态，禁止依赖具体随机序列（项目既有判例）。
设计依据见 docs/design-index.md「TR-3」「TR-4」。
"""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from app.transport.errors import ProviderError, TransportError
from app.transport.http import parse_retry_after, retry_delay_ms


def _plain_error_without_retry_after() -> Exception:
    """模拟无 Retry-After 信息的传输错误（httpx 网络异常/朴素 ProviderError）。"""
    try:
        raise httpx.ConnectError("net down")
    except httpx.ConnectError as e:
        return e


# ---------- 随机化指数退避（AC-T2） ----------

def test_retry_delay_ms_exponential_jitter_intervals():
    """无 Retry-After 时随机化指数退避：attempt 0/1/2 的延迟全部落在
    [0.5×2^a, 1.5×2^a] 毫秒区间（采样断言区间，不断言具体序列）。"""
    err = _plain_error_without_retry_after()
    for attempt, lo, hi in ((0, 500, 1500), (1, 1000, 3000), (2, 2000, 6000)):
        for _ in range(50):
            ms = retry_delay_ms(err, attempt)
            assert lo <= ms <= hi, f"attempt={attempt} 延迟 {ms}ms 越界 [{lo},{hi}]"


def test_retry_delay_ms_jitter_covers_both_sides_of_base():
    """分布形态：抖动因子覆盖基值两侧——采样中既有低于 2^a 秒的样本也有
    高于的样本（区间非退化、非单侧截断）。"""
    err = _plain_error_without_retry_after()
    samples = [retry_delay_ms(err, 0) for _ in range(200)]
    assert min(samples) < 1000 < max(samples)
    assert max(samples) - min(samples) > 200  # 展幅充分（全区间均匀形态）


def test_retry_delay_ms_base_grows_exponentially_with_attempt():
    """指数形态：attempt 递增时延迟区间基值翻倍（区间上界随 attempt 成 2 的幂）。"""
    err = _plain_error_without_retry_after()
    a0 = [retry_delay_ms(err, 0) for _ in range(60)]
    a2 = [retry_delay_ms(err, 2) for _ in range(60)]
    assert min(a2) > max(a0)  # attempt=2 的最小延迟也高于 attempt=0 的最大延迟


def test_retry_delay_ms_plain_provider_error_uses_exponential_path():
    """无 retry_after 属性的朴素 ProviderError 同样走指数退避路径
    （getattr 缺省 None——域包装错误不携带协商信息时不出错）。"""
    samples = [retry_delay_ms(ProviderError("boom"), 1) for _ in range(20)]
    assert all(1000 <= ms <= 3000 for ms in samples)


# ---------- Retry-After 协商优先（AC-T3 的脊内侧） ----------

def test_retry_delay_ms_retry_after_takes_priority_over_jitter():
    """服务端 Retry-After 优先：携带 retry_after 的错误退避=服务端值
    （确定性采纳，不随机化）。"""
    err = TransportError("HTTP 429: slow", status=429, retry_after=7.5)
    for _ in range(10):
        assert retry_delay_ms(err, 0) == 7500


def test_retry_delay_ms_retry_after_clamped_into_half_open_interval():
    """采纳区间夹逼 [0, 60s)：超大服务端值夹到上界内（59_999ms）、
    负/零值钳到下界 0（开区间上界=不无限等待）。"""
    huge = TransportError("HTTP 429", status=429, retry_after=600.0)
    assert retry_delay_ms(huge, 0) == 59_999
    tiny = TransportError("HTTP 429", status=429, retry_after=0.0)
    assert retry_delay_ms(tiny, 0) == 0
    negative = TransportError("HTTP 429", status=429, retry_after=-3.0)
    assert retry_delay_ms(negative, 0) == 0


def test_retry_delay_ms_retry_after_boundary_just_under_cap():
    """夹逼边界保真：59.999s 服务端值原样采纳（不误夹）。"""
    err = TransportError("HTTP 429", status=429, retry_after=59.999)
    assert retry_delay_ms(err, 0) == 59_999


# ---------- parse_retry_after 双形态解析（自 ingest/rss.py 等价上提，AC-T3） ----------

_NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_retry_after_delta_seconds_form():
    """delta-seconds 形态：纯数字串解析为秒数。"""
    assert parse_retry_after("120", now=_NOW) == 120.0
    assert parse_retry_after(" 0 ", now=_NOW) == 0.0


def test_parse_retry_after_http_date_form():
    """HTTP-date 形态：解析为「距今秒数」（时区保真——带偏移的日期串）。"""
    future = _NOW + timedelta(seconds=300)
    seconds = parse_retry_after(
        format_datetime(future.astimezone(timezone(timedelta(hours=2))), usegmt=False),
        now=_NOW)
    assert seconds is not None and abs(seconds - 300) < 5


def test_parse_retry_after_http_date_past_clamps_zero():
    """过去的 HTTP-date 钳为 0（负等待无意义）。"""
    past = _NOW - timedelta(hours=1)
    assert parse_retry_after(format_datetime(past, usegmt=True), now=_NOW) == 0.0


def test_parse_retry_after_invalid_and_empty_return_none():
    """非法/空值返回 None（调用方退回自有缺省间隔）。"""
    assert parse_retry_after(None, now=_NOW) is None
    assert parse_retry_after("", now=_NOW) is None
    assert parse_retry_after("   ", now=_NOW) is None
    assert parse_retry_after("soon", now=_NOW) is None


def test_parse_retry_after_equivalent_via_rss_reexport():
    """ingest/rss.py 侧 re-export 等价：rss 既有调用方拿到的就是传输脊本体
    （行为等价迁移护航——pipeline runner 的降频协商零改动）。"""
    from app.ingest.rss import parse_retry_after as rss_parse

    assert rss_parse is parse_retry_after
    assert rss_parse("90", now=_NOW) == 90.0


# ---------- 域重试循环采纳协商结果（providers / embedding 模板方法） ----------

class _FakeDB:
    """计量落账桩：record_usage 只需 add/commit 存在。"""

    def add(self, obj):
        pass

    def commit(self):
        pass


def test_llm_provider_call_honors_server_retry_after(monkeypatch):
    """LLM 域 _call 循环采纳服务端 Retry-After：429+Retry-After=7.5s 的传输
    错误，两次退避恰为服务端值（确定性采纳，不抖动）。"""
    from app.providers.base import HTTPProvider

    class _RetryAfterProbe(HTTPProvider):
        name = "probe"

        def _post(self, payload):
            raise TransportError("HTTP 429: slow", status=429, retry_after=7.5)

    sleeps: list = []
    monkeypatch.setattr(__import__("time"), "sleep", sleeps.append)
    probe = _RetryAfterProbe(_FakeDB(), base_url="https://api.test", api_key="k")  # type: ignore[arg-type]
    with pytest.raises(ProviderError):
        probe._call({"model": "m"}, call_point="ut")
    assert sleeps == [7.5, 7.5]  # 429 可重试：3 次尝试间两次退避均为服务端值


def test_llm_provider_call_retry_after_clamped_in_domain_loop(monkeypatch):
    """域循环内的夹逼同样生效：服务端 Retry-After 超大（600s）时退避夹到
    59.999s（[0, 60s) 开区间——不无限等待）。"""
    from app.providers.base import HTTPProvider

    class _HugeRetryAfter(HTTPProvider):
        name = "probe"

        def _post(self, payload):
            raise TransportError("HTTP 429: slow", status=429, retry_after=600.0)

    sleeps: list = []
    monkeypatch.setattr(__import__("time"), "sleep", sleeps.append)
    probe = _HugeRetryAfter(_FakeDB(), base_url="https://api.test", api_key="k")  # type: ignore[arg-type]
    with pytest.raises(ProviderError):
        probe._call({"model": "m"}, call_point="ut")
    assert len(sleeps) == 2
    assert all(s == 59.999 for s in sleeps)
