"""robots.txt 分级遵守测试（BE-5/RG-1/RG-2/RG-3）：假 fetcher/假时钟——
零真 DNS 零出网零真 sleep（判例：出网一律 monkeypatch 模块内 _fetch_robots
或 transport.http 工厂为 MockTransport——真工厂+域名 host 形态须经 SSRF hook
真 DNS 解析，BE-4 新发现②判例必载）。

覆盖口径（设计依据见 docs/design-index.md「RG-1」..「RG-3」，BE-5 增补）：
- 分级语义：2xx 规则生效（Disallow 拒/Allow 过/UA token 匹配特定组）、
  404 放行、5xx fail-closed、网络错 fail-closed、DNS 不可得（NXDOMAIN 形态）
  放行——任务书定案：404/NXDOMAIN 放行，5xx 与网络/解析异常 fail-closed；
- 缓存：成功 TTL 过期重取、失败短 TTL 后恢复重试（注入时钟）、缓存命中
  零二次抓取（计数桩）、重定向落地规则注记（缓存键=请求 origin）；
- crawl_delay_cached 纯缓存读取零网络 + throttle._min_interval_for 三分量
  max（RG-3：delay 最大时同域第二请求等待变长——注入时钟）；
- enrich 挂点（RG-2）：Disallow 放弃富化保留原文/robots 不可得同形放弃/
  允许则照常富化。

stdlib 语义注记（CPython 3.13 robotparser）：can_fetch/crawl_delay 均为
「文件序首匹配组生效」——特定 User-agent 组存在时 * 组不叠加（非 RFC 9309
最特定组语义）；本模块两 API 同用 stdlib 同一语义，不做二次解读。

进程态判例：robots 与 throttle 双模块 _reset_for_tests fixture 复位。
"""
import socket
from urllib import robotparser

import httpx
import pytest

import app.ingest.web as web_mod
import app.transport.robots as robots_mod
import app.transport.throttle as throttle_mod
from app.ingest.web import enrich_entry_text
from app.siteconfig import set_config
from app.transport.robots import allowed, crawl_delay_cached, denial_reason
from app.transport.throttle import wait_for_slot


@pytest.fixture(autouse=True)
def _reset_process_state():
    """进程态复位判例（robots 缓存+节流预约表双模块）。"""
    robots_mod._reset_for_tests()
    throttle_mod._reset_for_tests()
    yield
    robots_mod._reset_for_tests()
    throttle_mod._reset_for_tests()


class FakeClock:
    """注入时钟：callable 形态（_now/_clock）+ sleep 记账不真睡。"""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t
        self.slept = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept += s

    def advance(self, s: float) -> None:
        self.t += s


# ---------- 假 fetcher 两形态：直接替换 _fetch_robots / 工厂换 MockTransport ----------


def _parser_from(body: str) -> robotparser.RobotFileParser:
    p = robotparser.RobotFileParser()
    p.parse(body.splitlines())
    return p


def _allow_all() -> robotparser.RobotFileParser:
    p = robotparser.RobotFileParser()
    p.allow_all = True
    return p


def _patch_http_factory(monkeypatch, handler):
    """把 transport.http.http_client 换成 MockTransport 工厂——经真实
    _fetch_robots 走分级归一（零真 DNS：MockTransport 不触发 SSRF 解析）。"""

    def factory(db=None, *, timeout=60.0, follow_redirects=True, **kw):
        return httpx.Client(transport=httpx.MockTransport(handler),
                            follow_redirects=follow_redirects)

    monkeypatch.setattr("app.transport.http.http_client", factory)


def _seed_cache(origin: str, body: str | None, *, fail: bool = False,
                delay: float | None = None) -> None:
    if fail:
        robots_mod._cache[origin] = (robots_mod._now(), None, None)
    else:
        robots_mod._cache[origin] = (robots_mod._now(), _parser_from(body or ""), delay)


RULES_WILDCARD = "User-agent: *\nDisallow: /private\nCrawl-delay: 7"
RULES_SPECIFIC = "User-agent: newswright\nDisallow: /nw-only\nCrawl-delay: 12"

# ---------- 分级语义（真 _fetch_robots + MockTransport） ----------


def test_2xx_disallow_denied(db_session, monkeypatch):
    _patch_http_factory(
        monkeypatch, lambda r: httpx.Response(200, text=RULES_WILDCARD))
    assert allowed("https://x.example/private", db=db_session) is False


def test_2xx_allowed_path_passes(db_session, monkeypatch):
    _patch_http_factory(
        monkeypatch, lambda r: httpx.Response(200, text=RULES_WILDCARD))
    assert allowed("https://x.example/ok", db=db_session) is True


def test_2xx_ua_token_matches_specific_group(db_session, monkeypatch):
    """UA token=产品名 newswright：仅对 newswright 组立的规对我们生效
    （token 传错则不匹配该组→放行——判别式）。"""
    _patch_http_factory(
        monkeypatch, lambda r: httpx.Response(200, text=RULES_SPECIFIC))
    assert allowed("https://x.example/nw-only", db=db_session) is False
    assert allowed("https://x.example/ok", db=db_session) is True


def test_2xx_crawl_delay_recorded_for_token_group(db_session, monkeypatch):
    _patch_http_factory(
        monkeypatch, lambda r: httpx.Response(200, text=RULES_SPECIFIC))
    allowed("https://cd.example/a", db=db_session)
    assert crawl_delay_cached("cd.example") == pytest.approx(12.0)


def test_404_allows_all(db_session, monkeypatch):
    _patch_http_factory(monkeypatch, lambda r: httpx.Response(404))
    assert allowed("https://nf.example/private", db=db_session) is True
    assert crawl_delay_cached("nf.example") is None


def test_5xx_fail_closed(db_session, monkeypatch):
    _patch_http_factory(monkeypatch, lambda r: httpx.Response(503))
    assert allowed("https://err.example/anything", db=db_session) is False


def test_non_404_client_error_fail_closed(db_session, monkeypatch):
    """401/403 照 RFC 9309 语义=完全拒绝（其余非 2xx/404 一律 fail-closed）。"""
    _patch_http_factory(monkeypatch, lambda r: httpx.Response(403))
    assert allowed("https://auth.example/x", db=db_session) is False


def test_network_error_fail_closed(db_session, monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    _patch_http_factory(monkeypatch, handler)
    assert allowed("https://down.example/x", db=db_session) is False


def test_dns_unreachable_allows(db_session, monkeypatch):
    """NXDOMAIN 形态（DNS 解析不可得，gaierror 链）→ 放行（任务书定案：
    404/NXDOMAIN 放行——域名无政策可违，且随后主抓同样解析失败）。"""
    def handler(request):
        raise httpx.ConnectError("connect failed") from socket.gaierror(
            -2, "Name or service not known")

    _patch_http_factory(monkeypatch, handler)
    assert allowed("https://gone.example/x", db=db_session) is True


def test_redirect_uses_landing_rules_cached_under_request_origin(
        db_session, monkeypatch):
    """重定向落地规则注记：follow_redirects 后按最终响应判（落地规则生效），
    缓存键=请求 origin（跨域重定向以落地规则为准——任务书定形，不递归查落地域）。"""
    def handler(request):
        if request.url.host == "a.example":
            return httpx.Response(
                301, headers={"Location": "https://landing.example/robots.txt"})
        return httpx.Response(200, text="User-agent: *\nDisallow: /\n")

    _patch_http_factory(monkeypatch, handler)
    assert allowed("https://a.example/page", db=db_session) is False
    assert "https://a.example" in robots_mod._cache
    assert "https://landing.example" not in robots_mod._cache


# ---------- 缓存：TTL/命中/恢复（替换 _fetch_robots + 注入时钟） ----------


def test_cache_hit_no_second_fetch(db_session, monkeypatch):
    calls: list[str] = []

    def fake_fetch(origin, *, db=None):
        calls.append(origin)
        return _parser_from(RULES_WILDCARD), 7.0

    monkeypatch.setattr(robots_mod, "_fetch_robots", fake_fetch)
    clock = FakeClock()
    monkeypatch.setattr(robots_mod, "_now", clock)
    assert allowed("https://ttl.example/private/a", db=db_session) is False
    assert allowed("https://ttl.example/private/b", db=db_session) is False
    assert allowed("https://ttl.example/ok", db=db_session) is True
    assert calls == ["https://ttl.example"]  # 命中缓存零二次抓取


def test_success_ttl_expiry_refetches(db_session, monkeypatch):
    calls: list[str] = []

    def fake_fetch(origin, *, db=None):
        calls.append(origin)
        return _parser_from(RULES_WILDCARD), 7.0

    monkeypatch.setattr(robots_mod, "_fetch_robots", fake_fetch)
    clock = FakeClock()
    monkeypatch.setattr(robots_mod, "_now", clock)
    allowed("https://ttl.example/a", db=db_session)
    clock.advance(robots_mod.ROBOTS_CACHE_TTL_S + 1)  # 成功 TTL 3600 过期
    allowed("https://ttl.example/b", db=db_session)
    assert len(calls) == 2


def test_fail_short_ttl_then_recovers(db_session, monkeypatch):
    """失败短 TTL 300s 后重试：fail-closed 缓存过期后恢复重取，服务恢复即放行。"""
    outcomes = [None, (_parser_from(RULES_WILDCARD), 7.0)]

    def fake_fetch(origin, *, db=None):
        out = outcomes.pop(0)
        return out if out is not None else (None, None)

    monkeypatch.setattr(robots_mod, "_fetch_robots", fake_fetch)
    clock = FakeClock()
    monkeypatch.setattr(robots_mod, "_now", clock)
    assert allowed("https://flaky.example/x", db=db_session) is False  # 5xx 轮
    assert allowed("https://flaky.example/y", db=db_session) is False  # 短 TTL 内仍 fail
    clock.advance(robots_mod.ROBOTS_FAIL_TTL_S + 1)
    assert allowed("https://flaky.example/z", db=db_session) is True  # 重取后恢复


def test_crawl_delay_cached_pure_read_zero_fetch(db_session, monkeypatch):
    """crawl_delay_cached 纯缓存读取零网络：未抓过 None；fetcher 桩被触碰即红。"""
    def boom(origin, *, db=None):
        raise AssertionError("crawl_delay_cached 不得触发网络抓取")

    monkeypatch.setattr(robots_mod, "_fetch_robots", boom)
    assert crawl_delay_cached("never.example") is None
    _seed_cache("https://cd.example", RULES_WILDCARD, delay=9.0)
    assert crawl_delay_cached("cd.example") == pytest.approx(9.0)


# ---------- RG-2：enrich 挂点（Disallow/不可得放弃富化；允许照常） ----------


class _PageFactory:
    """页面抓取工厂桩：记录 GET；robots 已裁决的放弃路径不得触达。"""

    def __init__(self) -> None:
        self.gets: list[str] = []

    def __call__(self, db=None, *, timeout=60.0, follow_redirects=True, **kw):
        outer = self

        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get(self, url):
                outer.gets.append(url)
                return httpx.Response(200, text="<html>full</html>",
                                      request=httpx.Request("GET", url))

        return _Client()


def test_enrich_disallow_keeps_summary(db_session, monkeypatch):
    _seed_cache("https://blocked.example", "User-agent: *\nDisallow: /\n")
    factory = _PageFactory()
    monkeypatch.setattr(web_mod, "http_client", factory)
    monkeypatch.setattr(web_mod, "extract_page_markdown", lambda html: "更长全文" * 10)
    out = enrich_entry_text("https://blocked.example/a", "短摘要",
                            page_url="https://list.example/", db=db_session)
    assert out == "短摘要"  # 放弃富化保留摘要（与失败保留语义同形）
    assert factory.gets == []  # 页面抓取未发起
    assert denial_reason("https://blocked.example/a") == "Disallow"


def test_enrich_robots_unreachable_same_shape(db_session, monkeypatch):
    """robots 不可得（fail-closed）同形放弃：不致命、保留摘要。"""
    _seed_cache("https://gone.example", None, fail=True)
    factory = _PageFactory()
    monkeypatch.setattr(web_mod, "http_client", factory)
    monkeypatch.setattr(web_mod, "extract_page_markdown", lambda html: "更长全文" * 10)
    out = enrich_entry_text("https://gone.example/a", "短摘要",
                            page_url="https://list.example/", db=db_session)
    assert out == "短摘要"
    assert factory.gets == []
    assert denial_reason("https://gone.example/a") == "robots 不可得"


def test_enrich_allowed_proceeds(db_session, monkeypatch):
    _seed_cache("https://ok.example", "User-agent: *\nDisallow: /private\n")
    factory = _PageFactory()
    long_text = "富化后的完整正文，长度超过短摘要。" * 8
    monkeypatch.setattr(web_mod, "http_client", factory)
    monkeypatch.setattr(web_mod, "extract_page_markdown", lambda html: long_text)
    out = enrich_entry_text("https://ok.example/article", "短摘要",
                            page_url="https://list.example/", db=db_session)
    assert out == long_text
    assert factory.gets == ["https://ok.example/article"]  # 照常富化


# ---------- RG-3：Crawl-delay 请求层兑现（三分量 max） ----------


def test_min_interval_three_components_delay_wins(db_session):
    set_config(db_session, "netloc_min_interval_s", 3)
    _seed_cache("https://cd.example", RULES_WILDCARD, delay=12.0)
    assert throttle_mod._min_interval_for(db_session, "cd.example") \
        == pytest.approx(12.0)


def test_min_interval_override_beats_smaller_delay(db_session):
    set_config(db_session, "netloc_min_interval_s", 1)
    set_config(db_session, "netloc_throttle_domains", {"cd.example": 8})
    _seed_cache("https://cd.example", RULES_WILDCARD, delay=3.0)
    assert throttle_mod._min_interval_for(db_session, "cd.example") \
        == pytest.approx(8.0)


def test_min_interval_no_robots_cache_unchanged(db_session):
    """robots 未抓过=无第三分量，行为与两分量时代一致（零影响判据）。"""
    set_config(db_session, "netloc_min_interval_s", 3)
    assert throttle_mod._min_interval_for(db_session, "fresh.example") \
        == pytest.approx(3.0)


def test_crawl_delay_makes_second_request_wait_longer(db_session):
    """三分量 max 的行为兑现：Crawl-delay 12 > 缺省 3 时，同域第二请求等待
    12s（注入时钟零真 sleep——请求层已保证实际发送间隔 ≥ Crawl-delay）。"""
    set_config(db_session, "netloc_min_interval_s", 3)
    _seed_cache("https://slow.example", RULES_WILDCARD, delay=12.0)
    interval = throttle_mod._min_interval_for(db_session, "slow.example")
    clock = FakeClock()
    kwargs = dict(min_interval_s=interval, max_wait_s=30.0,
                  _clock=clock, _sleep=clock.sleep)
    assert wait_for_slot("slow.example", **kwargs) == 0.0  # 首访零等待
    assert wait_for_slot("slow.example", **kwargs) == pytest.approx(12.0)
    assert clock.slept == pytest.approx(12.0)
