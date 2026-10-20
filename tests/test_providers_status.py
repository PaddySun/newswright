"""BE-7/PG-4 /api/providers/status 状态端点（守卫，A13 同款先例）。

覆盖（任务书 §五必含用例）：
- 守卫 401（未登录拒——router 级会话守卫，/stats/pipeline 同款）；
- 聚合口径：chat 域候选链两名（moark/deepseek）——每家 cooldown_remaining
  （进程读）+ balance（读 balance_last_* 键，未探测=null）+ llm_24h
  {total, errors, error_rate, recent_error}（usage_log 按实例名聚合 24h 窗，
  provider 列存实例名——任务书 A6/AC-6 亲证口径）；
- recent_error 脱敏截断（sk- 形态打码、超长截断）。

admin 呈现留 UI2（旧 SPA 不加区块——端点先立入 UI2 契约面）。
"""
import pytest

from app.providers.resolve import mark_cooldown
from app.siteconfig import set_config
from app.transport.metering import record_usage


@pytest.fixture(autouse=True)
def clean_resolve():
    from app.providers import resolve as resolve_mod

    resolve_mod._reset_for_tests()
    yield resolve_mod
    resolve_mod._reset_for_tests()


def test_status_requires_session(api_client):
    """未登录 → 401（守卫面）。"""
    r = api_client.get("/api/providers/status")
    assert r.status_code == 401


def test_status_aggregates_cooldown_balance_and_usage(auth_client, db_session):
    """聚合口径：候选链两名，每家冷却/余额/24h 用量聚合（构造 usage_log 行）。"""
    record_usage(db_session, provider="moark", model="deepseek-v4.1-flash",
                 call_point="scoring", ok=True)
    record_usage(db_session, provider="moark", model="deepseek-v4.1-flash",
                 call_point="scoring", ok=True)
    record_usage(db_session, provider="moark", model="deepseek-v4.1-flash",
                 call_point="scoring", ok=False,
                 error="VendorFatalError: 账户余额不足（402）——请充值后重试: sk-abc")
    record_usage(db_session, provider="deepseek", model="deepseek-flash",
                 call_point="writing", ok=True)
    mark_cooldown("moark", seconds=600)
    set_config(db_session, "balance_last_deepseek",
               {"amount": 12.34, "currency": "CNY", "ok": True,
                "probed_at": "2026-10-20T00:00:00+00:00", "error": None})

    r = auth_client.get("/api/providers/status")
    assert r.status_code == 200, r.text
    providers = {p["name"]: p for p in r.json()["providers"]}
    assert list(providers) == ["moark", "deepseek"]  # 候选链序

    moark = providers["moark"]
    assert moark["cooldown_remaining"] > 0
    assert moark["balance"] is None  # 未探测=null
    assert moark["llm_24h"]["total"] == 3
    assert moark["llm_24h"]["errors"] == 1
    assert moark["llm_24h"]["error_rate"] == 0.3333
    recent = moark["llm_24h"]["recent_error"]
    assert recent is not None and "sk-abc" not in recent  # 脱敏
    assert "sk-***" in recent

    deepseek = providers["deepseek"]
    assert deepseek["cooldown_remaining"] == 0
    assert deepseek["balance"]["amount"] == 12.34
    assert deepseek["llm_24h"] == {
        "total": 1, "errors": 0, "error_rate": 0.0, "recent_error": None}


def test_status_recent_error_truncated(auth_client, db_session):
    """recent_error 超长截断（端点呈现口径，不搬全量错误原文）。"""
    record_usage(db_session, provider="moark", model="m", call_point="scoring",
                 ok=False, error="X" * 5000)
    r = auth_client.get("/api/providers/status")
    providers = {p["name"]: p for p in r.json()["providers"]}
    assert len(providers["moark"]["llm_24h"]["recent_error"]) <= 300
