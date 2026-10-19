"""per-netloc 最小间隔节流测试（BE-4/AC-2）：预约制等待（注入时钟零真
sleep）、超 max_wait 快速失败（ThrottledError 被 httpx.HTTPError 收编、
快速失败不占槽）、跨域独立、per-netloc 覆盖、并发预约不插队、hook
GET-only 与工厂接线、_reset_for_tests 判例。

设计依据见 docs/design-index.md「TG-2」（BE-4 增补）。
"""
import threading

import httpx
import pytest

import app.transport.throttle as throttle_mod
from app.siteconfig import DEFAULTS, set_config
from app.transport.http import http_client
from app.transport.throttle import ThrottledError, throttle_request, wait_for_slot


@pytest.fixture(autouse=True)
def _reset_throttle_table():
    """进程级节流表复位判例（每测试文件 fixture 复位）。"""
    throttle_mod._reset_for_tests()
    yield
    throttle_mod._reset_for_tests()


class StaticClock:
    """注入时钟：sleep 只记账不推进（模拟同轮扇出瞬间到达）；monotonic 恒定。"""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t
        self.total_sleep = 0.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.total_sleep += s

    def advance(self, s: float) -> None:
        self.t += s


# ---------- 预约制等待核心语义 ----------


def test_first_visit_zero_wait():
    """首访零等待（无前驱即取当前时刻为首槽——每个新域名首次请求不受罚）。"""
    c = StaticClock()
    w = wait_for_slot("a.example", min_interval_s=3.0, max_wait_s=30.0,
                      _clock=c.monotonic, _sleep=c.sleep)
    assert w == 0.0
    assert c.total_sleep == 0.0


def test_second_same_domain_request_waits_interval():
    """同域第二请求等待最小间隔（D6：RSS 补抓原文同域连发的域控）。"""
    c = StaticClock()
    wait_for_slot("a.example", min_interval_s=3.0, max_wait_s=30.0,
                  _clock=c.monotonic, _sleep=c.sleep)
    w = wait_for_slot("a.example", min_interval_s=3.0, max_wait_s=30.0,
                      _clock=c.monotonic, _sleep=c.sleep)
    assert w == pytest.approx(3.0)
    assert c.total_sleep == pytest.approx(3.0)


def test_cross_domain_slots_independent():
    """跨域独立：a.example 的预约不阻塞 b.example（不同站点互不相干）。"""
    c = StaticClock()
    wait_for_slot("a.example", min_interval_s=3.0, max_wait_s=30.0,
                  _clock=c.monotonic, _sleep=c.sleep)
    w = wait_for_slot("b.example", min_interval_s=3.0, max_wait_s=30.0,
                  _clock=c.monotonic, _sleep=c.sleep)
    assert w == 0.0


def test_queue_recovery_after_clock_advances():
    """时钟越过队列尾部后新请求零等待（预约制槽位按时刻而非计数消耗）。"""
    c = StaticClock()
    for _ in range(3):
        wait_for_slot("a.example", min_interval_s=3.0, max_wait_s=30.0,
                      _clock=c.monotonic, _sleep=c.sleep)
    c.advance(30.0)  # 越过全部已预约槽位
    w = wait_for_slot("a.example", min_interval_s=3.0, max_wait_s=30.0,
                      _clock=c.monotonic, _sleep=c.sleep)
    assert w == 0.0


# ---------- 快速失败上限 ----------


def test_exceed_max_wait_raises_throttled_error_without_slot():
    """排队等待超 max_wait 抛 ThrottledError 且**不占槽**（快速失败者不消耗
    未来时间片——否则同轮扇出会把下一轮也锁死）。"""
    c = StaticClock()
    kwargs = dict(min_interval_s=3.0, max_wait_s=30.0,
                  _clock=c.monotonic, _sleep=c.sleep)
    waits = [wait_for_slot("fan.example", **kwargs) for _ in range(11)]
    # 11 个请求：首访 0s + 排队 3/6/.../30s（恰达上限不抛，严格大于才抛）
    assert waits == pytest.approx([0.0] + [3.0 * i for i in range(1, 11)])
    with pytest.raises(ThrottledError) as ei:
        wait_for_slot("fan.example", **kwargs)
    assert "fan.example" in str(ei.value)
    assert "netloc_throttle_max_wait_s" in str(ei.value)
    # 被拒请求不占槽：再次尝试仍按原队尾判定（等待 33s 而非更长）
    with pytest.raises(ThrottledError):
        wait_for_slot("fan.example", **kwargs)
    # 队尾不被污染的恢复证据：时钟越过原队尾（t=1000+30=1030，next=1033）后放行
    c.advance(33.0)
    assert wait_for_slot("fan.example", **kwargs) == 0.0


def test_throttled_error_collected_by_httpx_capture_face():
    """继承 httpx.TransportError——既有 except httpx.HTTPError 捕获面零改收编
    （enrich 失败保留摘要天然契合、下轮重试幂等）。"""
    assert issubclass(ThrottledError, httpx.TransportError)
    try:
        raise ThrottledError("x")
    except httpx.HTTPError:
        pass


def test_zero_interval_no_op():
    """间隔 ≤0 完全跳过（配置 0=对该维度关闭节流，不写表不等待）。"""
    c = StaticClock()
    for _ in range(5):
        assert wait_for_slot("x.example", min_interval_s=0.0, max_wait_s=30.0,
                             _clock=c.monotonic, _sleep=c.sleep) == 0.0
    assert c.total_sleep == 0.0


# ---------- 并发预约不插队 ----------


def test_concurrent_reservations_form_ordered_slots():
    """并发线程按领号顺序排队不插队：4 线程同域领到 4 个间隔递增的时间片
    （注入时钟/sleep 仅记账不推进，零真 sleep——时钟冻结下等待值只由领号
    顺序决定，任何交错都得同一阶梯）。"""
    class SyncClock:
        def __init__(self) -> None:
            self.t = 2000.0
            self._lk = threading.Lock()

        def monotonic(self) -> float:
            with self._lk:
                return self.t

        def sleep(self, s: float) -> None:
            pass  # 仅记账位：不推进假时钟（推进则等待值退化为常数）

    clock = SyncClock()
    got: list[float] = []
    barrier = threading.Barrier(4)

    def worker() -> None:
        barrier.wait()  # 尽量同时冲锁
        got.append(wait_for_slot("same.example", min_interval_s=0.05, max_wait_s=30.0,
                                 _clock=clock.monotonic, _sleep=clock.sleep))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(got) == pytest.approx([0.0, 0.05, 0.10, 0.15])


# ---------- hook：GET-only 与配置解析 ----------


def _get(url: str) -> httpx.Request:
    return httpx.Request("GET", url)


def test_hook_get_only_post_face_untouched(monkeypatch):
    """hook 对非 GET 一律放行（腾讯 POST 面零误伤——GET-only 设计依据 A3）。"""
    called = []
    monkeypatch.setattr(throttle_mod, "wait_for_slot",
                        lambda netloc, **kw: called.append(netloc) or 0.0)
    throttle_request(httpx.Request("POST", "http://api.example/v1/x", json={}))
    assert called == []


def test_hook_reads_three_config_keys(db_session, monkeypatch):
    """配置三键解析：per-netloc 覆盖 dict > 全局 netloc_min_interval_s；
    max_wait 独立键；hook 把解析值传入 wait_for_slot。"""
    captured = {}

    def fake_wait(netloc, *, min_interval_s, max_wait_s):
        captured["netloc"], captured["interval"], captured["max_wait"] = (
            netloc, min_interval_s, max_wait_s)
        return 0.0

    monkeypatch.setattr(throttle_mod, "wait_for_slot", fake_wait)
    set_config(db_session, "netloc_min_interval_s", 1)
    set_config(db_session, "netloc_throttle_domains", {"slow.example": 5})
    set_config(db_session, "netloc_throttle_max_wait_s", 9)

    throttle_request(_get("https://plain.example/feed"), db=db_session)
    assert captured == {"netloc": "plain.example", "interval": 1.0, "max_wait": 9.0}

    throttle_request(_get("https://slow.example/feed"), db=db_session)
    assert captured["interval"] == 5.0  # per-netloc 覆盖生效


def test_hook_db_none_uses_code_defaults(monkeypatch):
    """db=None（工厂无会话）回退代码缺省常量（与 DEFAULTS 同值）。"""
    captured = {}

    def fake_wait(netloc, *, min_interval_s, max_wait_s):
        captured["interval"], captured["max_wait"] = min_interval_s, max_wait_s
        return 0.0

    monkeypatch.setattr(throttle_mod, "wait_for_slot", fake_wait)
    throttle_request(_get("https://any.example/x"))
    assert captured["interval"] == throttle_mod.DEFAULT_MIN_INTERVAL_S
    assert captured["max_wait"] == throttle_mod.DEFAULT_MAX_WAIT_S
    assert DEFAULTS["netloc_min_interval_s"] == throttle_mod.DEFAULT_MIN_INTERVAL_S
    assert DEFAULTS["netloc_throttle_max_wait_s"] == throttle_mod.DEFAULT_MAX_WAIT_S
    assert DEFAULTS["netloc_throttle_domains"] == {}


def test_hook_bad_override_value_falls_back(db_session, monkeypatch):
    """非法覆盖值回退全局缺省（warn 不炸——照 notify_category_intervals 判例）。"""
    captured = {}

    def fake_wait(netloc, *, min_interval_s, max_wait_s):
        captured["interval"] = min_interval_s
        return 0.0

    monkeypatch.setattr(throttle_mod, "wait_for_slot", fake_wait)
    set_config(db_session, "netloc_min_interval_s", 2)
    set_config(db_session, "netloc_throttle_domains", {"weird.example": "fast"})
    throttle_request(_get("https://weird.example/x"), db=db_session)
    assert captured["interval"] == 2.0


# ---------- 工厂接线 ----------


def test_factory_attaches_both_hooks(db_session):
    """工厂 event_hooks 同时挂 SSRF+节流双 hook（partial 预绑定 db）。"""
    from app.transport.ssrf import refuse_private_destination
    client = http_client(db_session)
    try:
        hooks = client.event_hooks["request"]
        funcs = [getattr(h, "func", None) for h in hooks]
        assert refuse_private_destination in funcs
        assert throttle_request in funcs
        assert funcs.index(refuse_private_destination) < funcs.index(throttle_request)
    finally:
        client.close()


def test_factory_request_path_with_throttle_disabled(db_session):
    """工厂全路径冒烟：全局间隔配 0 时连续两次 GET 畅通（hook 不破坏请求路径，
    MockTransport 零出网；host 用公网 IP 字面量——SSRF 直判零 DNS）。"""
    set_config(db_session, "netloc_min_interval_s", 0)
    client = http_client(
        db_session, transport=httpx.MockTransport(lambda r: httpx.Response(200, text="ok")))
    try:
        assert client.get("https://93.184.216.34/a").status_code == 200
        assert client.get("https://93.184.216.34/b").status_code == 200
    finally:
        client.close()
