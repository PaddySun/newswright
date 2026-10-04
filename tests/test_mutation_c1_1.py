"""C1-1 变异分诊批次 2 补强测试（providers.base 158 条 C 类 + T1 三条 D 转 C）。

断言全部来自设计书 v1.5 条款（ADR-8 计量/重试/脱敏纪律、AC-01.2b/01.4b/ADR-5⑤b
整点与无对端口径、技术书 §4.1 usage_log 账本、§4.2 外部调用显式超时、R5 JSON 解析链）。
命名 test_<function>_<mutant编号>_<断言点>；风格与 tests/test_mutation_t1.py 一致。
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import app.auth as auth_mod
import app.config as cfg
import app.providers.base as base_mod
from app.api.deps import LoginRateLimiter, get_client_ip
from app.auth import issue_session
from app.models import User, UsageLog
from app.providers.base import (
    HTTPProvider,
    JSONParseError,
    ProviderError,
    parse_strict_json,
    record_usage,
)


# ---------- T1 三条 D 转 C（设计书 v1.5 拍板口径） ----------


def test_get_client_ip_mutant_15_no_client_scope_returns_unknown(db_session):
    """ADR-5⑤b：ASGI scope 无对端信息时返回固定哨兵 "unknown"，不拒绝请求。"""
    from starlette.requests import Request

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    assert request.client is None  # Given：scope 无对端信息
    assert get_client_ip(request, db_session) == "unknown"  # Then：哨兵而非崩溃


def test_allow_mutant_10_cooldown_releases_at_exact_boundary():
    """AC-01.2b：冷却到点即解——now == locked_until 整点必须放行（计数同步清零）。"""
    base = datetime.now(timezone.utc)
    clock = {"t": base}
    lrl = LoginRateLimiter(now=lambda: clock["t"])
    for _ in range(5):
        lrl.record_failure("ip")
    assert lrl.allow("ip") is False  # 冷却期内拒绝
    clock["t"] = base + timedelta(minutes=LoginRateLimiter.COOLDOWN_MINUTES)  # 整点
    assert lrl.allow("ip") is True  # 到点即解
    lrl.record_failure("ip")  # 计数已清零：一次新失败不得再锁
    assert lrl.allow("ip") is True


def test_get_valid_session_mutant_12_expired_at_exact_boundary(db_session, monkeypatch):
    """AC-01.4b：会话到期即失效——expires_at == now 整点一律 None（401）。"""
    user = User(username="admin", password_hash="x")
    db_session.add(user)
    db_session.commit()
    t0 = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(auth_mod, "_now", lambda: t0)
    sess = issue_session(db_session, user, duration_days=7)
    monkeypatch.setattr(auth_mod, "_now", lambda: t0 + timedelta(days=7))  # 恰在 expires_at
    assert auth_mod.get_valid_session(db_session, sess.id) is None


# ---------- _scrub 脱敏（ADR-8 报错脱敏 + 产品书 §安全「日志脱敏（sk-***）」） ----------


def test_scrub_mutant_1_7_8_9_10_key_masked_in_ledger(db_session):
    """账本 error 字段必须脱敏：sk- 前缀 → sk-***，且原文不得残留。"""
    record_usage(db_session, provider="p", model="m", call_point="ut",
                 error="sk-abc123 boom")
    row = db_session.query(UsageLog).one()
    assert row.error == "sk-***abc123 boom"  # 掩码格式 sk-*** 为设计书钉定
    assert "sk-abc123" not in (row.error or "")


def test_record_usage_mutant_4_5_default_zero_columns(db_session):
    """技术书 §4.1 usage_log：未计量列缺省 0（缓存命中/思维链 token 不得虚记）。"""
    record_usage(db_session, provider="p", model="m", call_point="ut")
    row = db_session.query(UsageLog).one()
    assert row.cache_hit_tokens == 0 and row.reasoning_tokens == 0


# ---------- _call：成功账本 / 失败账本 / 重试退避（ADR-8 统一纪律） ----------


class _Dummy(HTTPProvider):
    name = "dummy"

    def __init__(self, db):
        super().__init__(db, base_url="https://example.com", api_key="k")

    def _post(self, payload):  # pragma: no cover - 各测试以实例属性覆写
        return {}, {}


def _patch_clock(monkeypatch, step=0.25):
    """注入假时钟：每次 monotonic 前进 step 秒 → 每次 latency 恰为 250ms。"""
    t = {"v": 100.0}
    monkeypatch.setattr(base_mod.time, "monotonic", lambda: t.__setitem__("v", t["v"] + step) or t["v"])
    sleeps: list = []
    monkeypatch.setattr(base_mod.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


def test_call_success_ledger_full_row_and_body(db_session, monkeypatch):
    """ADR-8：每次调用落一条 usage_log（provider/model/call_point/token 四元组/
    latency/ok/ref 全列如实落账）+ 返回响应体。"""
    _patch_clock(monkeypatch)
    d = _Dummy(db_session)
    meter = {"prompt_tokens": 11, "completion_tokens": 22, "billing_units": 3,
             "cache_hit_tokens": 4, "reasoning_tokens": 5,
             "finish_reason": "stop", "item_count": 9}
    d._post = lambda payload: ({"ok": 1}, meter)  # type: ignore[method-assign]
    body = d._call({"model": "m-1"}, call_point="ut", ref_type="item", ref_id=7)
    assert body == {"ok": 1}
    row = db_session.query(UsageLog).one()
    assert row.provider == "dummy" and row.model == "m-1" and row.call_point == "ut"
    assert row.prompt_tokens == 11 and row.completion_tokens == 22
    assert row.billing_units == 3 and row.cache_hit_tokens == 4 and row.reasoning_tokens == 5
    assert row.finish_reason == "stop" and row.item_count == 9
    assert row.latency_ms == 250 and row.ok is True
    assert row.ref_type == "item" and row.ref_id == 7


def test_call_fatal_error_no_retry_and_ledger(db_session, monkeypatch):
    """ADR-8 + 模块口径：不可重试错误（ProviderError.retryable=False）不重试；
    失败也落账——ok=False、error 含原因、未计量列缺省 0（账本真实性）。"""
    sleeps = _patch_clock(monkeypatch)
    d = _Dummy(db_session)
    calls: list = []

    def boom(payload):
        calls.append(payload)
        raise ProviderError("boom")

    d._post = boom  # type: ignore[method-assign]
    with pytest.raises(ProviderError):
        d._call({"model": "m-1"}, call_point="ut", ref_type="item", ref_id=7)
    assert len(calls) == 1  # 不可重试：不烧日志
    assert sleeps == []  # 未发生重试退避
    row = db_session.query(UsageLog).one()
    assert row.ok is False and "boom" in row.error
    assert row.prompt_tokens == 0 and row.completion_tokens == 0
    assert row.billing_units == 0 and row.cache_hit_tokens == 0 and row.reasoning_tokens == 0
    assert row.latency_ms == 250 and row.model == "m-1" and row.call_point == "ut"
    assert row.ref_type == "item" and row.ref_id == 7


def test_call_retry_exhaustion_backoff_1s_2s(db_session, monkeypatch):
    """ADR-8 + 模块纪律：网络类失败重试最多 2 次（指数退避 1s/2s），耗尽抛
    ProviderError；每次尝试各落一条失败账。"""
    sleeps = _patch_clock(monkeypatch)
    d = _Dummy(db_session)
    calls: list = []

    def net_down(payload):
        calls.append(payload)
        raise httpx.ConnectError("net down")

    d._post = net_down  # type: ignore[method-assign]
    with pytest.raises(ProviderError):
        d._call({"model": "m-1"}, call_point="ut", ref_type="item", ref_id=7)
    assert len(calls) == 3  # 初次 + 重试 2 次
    assert sleeps == [1, 2]  # 指数退避 2**attempt：1s, 2s
    rows = db_session.query(UsageLog).all()
    assert len(rows) == 3 and all(r.ok is False for r in rows)
    assert all(r.latency_ms == 250 for r in rows)
    assert all("net down" in r.error for r in rows)


def test_call_retryable_providererror_retried(db_session, monkeypatch):
    """ADR-8：retryable ProviderError（如 _post_json 429/5xx 语义）必须走重试。"""
    _patch_clock(monkeypatch)
    d = _Dummy(db_session)
    calls: list = []

    def limited(payload):
        calls.append(payload)
        e = ProviderError("HTTP 429: slow down")
        e.retryable = True  # type: ignore[attr-defined]
        raise e

    d._post = limited  # type: ignore[method-assign]
    with pytest.raises(ProviderError):
        d._call({"model": "m-1"}, call_point="ut")
    assert len(calls) == 3


def test_http_provider_init_mutant_16_timeout_always_set(db_session, monkeypatch):
    """技术书 §4.2：外部调用一律显式超时（httpx timeout 全量必填）——timeout 不得为 None。"""
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kw):
            captured.update(kw)
            raise RuntimeError("stop")

    monkeypatch.setattr(base_mod.httpx, "Client", FakeClient)
    d = _Dummy(db_session)
    with pytest.raises(RuntimeError):
        d._post_json("/v1/x", {})
    assert captured.get("timeout") is not None


# ---------- _meter_from_openai_usage（ADR-8 计量 + 对账纪律：账本数字须真实） ----------


def test_meter_mutant_11_12_14_15_16_17_19_20_21_basic_usage():
    """官方 usage 基本解析：prompt/completion 如实、billing_units 恒 0、
    未提供的 cache/reasoning 细节缺省 0。"""
    meter = HTTPProvider._meter_from_openai_usage(
        {"prompt_tokens": 100, "completion_tokens": 50})
    assert meter["prompt_tokens"] == 100
    assert meter["completion_tokens"] == 50
    assert meter["billing_units"] == 0
    assert meter["cache_hit_tokens"] == 0 and meter["reasoning_tokens"] == 0


def test_meter_mutant_10_18_37_49_empty_usage_all_zero():
    """usage 缺失/为空时全部计量列为 0（账本不得虚增）。"""
    meter = HTTPProvider._meter_from_openai_usage({})
    assert meter == {"prompt_tokens": 0, "completion_tokens": 0, "billing_units": 0,
                     "cache_hit_tokens": 0, "reasoning_tokens": 0}
    assert HTTPProvider._meter_from_openai_usage(None) == meter


def test_meter_mutant_30_32_33_34_35_36_details_fallback():
    """官方 usage 细节回退链：无 prompt_cache_hit_tokens 时读
    prompt_tokens_details.cached_tokens（cache_hit 计量落账口径）。"""
    meter = HTTPProvider._meter_from_openai_usage({
        "prompt_tokens": 100, "completion_tokens": 5,
        "prompt_tokens_details": {"cached_tokens": 32}})
    assert meter["cache_hit_tokens"] == 32
    assert meter["reasoning_tokens"] == 0


# ---------- parse_strict_json（R5 JSON 解析链：strict 层须兼容围栏与前后杂文） ----------


def test_parse_strict_json_mutant_14_17_22_29_nested_and_prose():
    """strict 层核心契约：嵌套 JSON 对象（花括号切片 = 第一个 { 到最后一个 }）
    与紧跟 } 的前后杂文均须解析成功。"""
    assert parse_strict_json('前言 {"a": {"b": 2}} 后记') == {"a": {"b": 2}}
    assert parse_strict_json('{"a": 1}以上。') == {"a": 1}  # } 后紧跟杂文
    with pytest.raises(JSONParseError):
        parse_strict_json("完全没有花括号的输出")


# ---------- F1⑩ 残余复核补测：计量包装对请求体的透传契约 ----------

def test_call_passes_constructed_payload_to_post(db_session):
    """_call 的重试/计量包装必须把调用方构造的请求体原样透传给 _post（HTTP body
    一致性：包装层增删改字段都会让线上请求与计量归因失真）。"""
    d = _Dummy(db_session)
    seen: list = []

    def post(payload):
        seen.append(payload)
        return {"ok": 1}, {"prompt_tokens": 1, "completion_tokens": 1, "billing_units": 0}

    d._post = post  # type: ignore[method-assign]
    payload = {"model": "m-1", "messages": [{"role": "user", "content": "hi"}]}
    d._call(payload, call_point="ut", ref_type="item", ref_id=1)
    assert seen == [payload]
