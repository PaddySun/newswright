"""通知调度中枢测试（BE-2）：队列+双闸+缓冲上限与优先级丢弃+类别注册表+去重键治理。

覆盖口径（设计依据见 docs/design-index.md「NC-1」~「NC-5」）：
- 入队五关：注册表未知→unknown_category（WARN）/通道未配置→not_configured 仅落日志/
  去重预检（持久化时间戳+在队同键）→deduped/digest 族全局开关关拒收；
- flush 双闸：账户硬间隔 ACCOUNT_HARD_INTERVAL_S=60（代码常量「硬」不可配）+
  类别最小间隔（site_config notify_category_intervals 覆盖，缺省注册表 0=仅账户闸）；
- 投递语义：按入队序、失败 WARN 丢弃不重试、时间戳仅投递成功才落；
- 缓冲上限 ACCOUNT_QUEUE_CAP=10 与丢弃序（digest 族→priority 数值大者→同级丢新留旧）；
- 键治理：去重窗口可配（缝隙 c）+notify_last_sent_% 惰性清理（缝隙 d）；
- 接受语义：队列进程内、重启即丢（文档性测试钉死，防未来误加持久化）。

时间纪律：全部经注入 now（T0 基准），禁真等；SMTP 打桩 _deliver 面（smtplib.SMTP_SSL）。
"""
import logging
from datetime import datetime, timedelta, timezone

import pytest

from app.notify import hub
from app.siteconfig import get_config, set_config

T0 = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)


class FakeSMTP:
    """smtplib.SMTP_SSL 打桩：记录调用，可注入连接失败。"""

    fail = False
    calls: list[dict] = []

    def __init__(self, host, port, timeout=None):
        FakeSMTP.calls.append({"host": host, "port": port})
        if FakeSMTP.fail:
            raise ConnectionRefusedError("[Errno 111] Connection refused")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        pass

    def sendmail(self, from_addr, to_addrs, msg):
        FakeSMTP.calls[-1]["msg"] = msg


@pytest.fixture(autouse=True)
def _hub_state_reset():
    """中枢进程级状态（队列/锚点/计数/清理节流）每测试复位，防跨文件泄漏。"""
    hub._reset_for_tests()
    yield
    hub._reset_for_tests()


@pytest.fixture()
def smtp_stub(monkeypatch):
    FakeSMTP.calls = []
    FakeSMTP.fail = False
    monkeypatch.setattr("app.notify.smtp.smtplib.SMTP_SSL", FakeSMTP)
    return FakeSMTP


@pytest.fixture()
def smtp_ready(db_session):
    set_config(db_session, "smtp_host", "smtp.example.com")
    set_config(db_session, "smtp_port", 465)
    set_config(db_session, "smtp_from", "bot@example.com")
    set_config(db_session, "smtp_to", ["me@example.com"])


# ---------- AC-4：类别注册表（十一条目）与硬常量 ----------


def test_registry_eleven_entries_and_hard_constants():
    assert hub.ACCOUNT_HARD_INTERVAL_S == 60  # 「硬」=代码常量，不做 site_config
    assert hub.ACCOUNT_QUEUE_CAP == 10
    expected = {
        "source_hard_fail": ("alert", 1, 0),
        "source_suspect": ("alert", 1, 0),
        "token_budget": ("alert", 1, 0),
        "collective_degradation": ("alert", 1, 0),
        "disk_usage": ("alert", 1, 0),
        "reconcile": ("alert", 2, 0),
        "source_recovered": ("alert", 2, 0),   # BE-3 复活通知（低紧迫档）
        "notify_test": ("alert", 2, 0),
        "provider_switched": ("alert", 1, 0),      # 骨架位（BE-7 接线）
        "balance_low": ("alert", 1, 0),            # 骨架位
        "llm_error_rate_high": ("alert", 1, 0),    # 骨架位
    }
    assert set(hub.CATEGORY_REGISTRY) == set(expected)
    for cat, (family, priority, interval) in expected.items():
        assert hub.CATEGORY_REGISTRY[cat] == {
            "family": family, "priority": priority,
            "default_min_interval_s": interval}, cat
    # digest 族本批零条目（D5 接口预留）
    assert all(e["family"] == "alert" for e in hub.CATEGORY_REGISTRY.values())


# ---------- AC-1：入队五关 ----------


def test_enqueue_unknown_category_rejected(db_session, smtp_ready, smtp_stub,
                                            caplog):
    """未知类别→unknown_category + WARN（防拼写错静默丢）。"""
    with caplog.at_level(logging.WARNING, logger="newswright.notify"):
        out = hub.enqueue(db_session, "s", "b", category="sourse_hard_fail",
                          dedupe_key="k", now=T0)
    assert out == {"queued": False, "reason": "unknown_category"}
    assert any("未知类别" in r.message for r in caplog.records)
    assert smtp_stub.calls == []


def test_enqueue_unconfigured_logs_only(db_session, smtp_stub, caplog):
    """通道未配置→not_configured 仅落日志（与现行语义同）。"""
    with caplog.at_level(logging.INFO, logger="newswright.notify"):
        out = hub.enqueue(db_session, "s", "b", category="disk_usage",
                          dedupe_key="k", now=T0)
    assert out == {"queued": False, "reason": "not_configured"}
    assert smtp_stub.calls == []
    assert any("未配置" in r.message for r in caplog.records)


def test_enqueue_dedupe_precheck_persisted_timestamp(db_session, smtp_ready,
                                                     smtp_stub):
    """去重预检①：持久化时间戳窗口内→deduped（不重复入队）。"""
    set_config(db_session, "notify_last_sent_disk_usage_disk",
               (T0 - timedelta(hours=1)).isoformat())
    out = hub.enqueue(db_session, "s", "b", category="disk_usage",
                      dedupe_key="disk", now=T0)
    assert out == {"queued": False, "reason": "deduped"}
    assert hub.snapshot()["deduped_total"] == 1
    assert smtp_stub.calls == []


def test_enqueue_dedupe_precheck_inflight_same_key(db_session, smtp_ready,
                                                   smtp_stub):
    """去重预检②：在队同键（尚未投递、时间戳未落）→deduped。"""
    assert hub.enqueue(db_session, "s1", "b", category="disk_usage",
                       dedupe_key="disk", now=T0) == {"queued": True}
    out = hub.enqueue(db_session, "s2", "b", category="disk_usage",
                      dedupe_key="disk", now=T0 + timedelta(seconds=1))
    assert out == {"queued": False, "reason": "deduped"}
    assert hub.snapshot()["queue_depth"] == 1
    assert hub.snapshot()["deduped_total"] == 1


def test_enqueue_dedupe_expired_timestamp_allows(db_session, smtp_ready,
                                                 smtp_stub):
    """窗口外时间戳放行（窗口边界见 AC-3 用例）。"""
    set_config(db_session, "notify_last_sent_disk_usage_disk",
               (T0 - timedelta(hours=25)).isoformat())
    out = hub.enqueue(db_session, "s", "b", category="disk_usage",
                      dedupe_key="disk", now=T0)
    assert out == {"queued": True}


def test_enqueue_digest_family_rejected_when_disabled(db_session, smtp_ready,
                                                       smtp_stub, monkeypatch):
    """digest 族在全局开关关时拒收（本期无消费方，D5 接口预留）。"""
    monkeypatch.setitem(hub.CATEGORY_REGISTRY, "digest_probe",
                        {"family": "digest", "priority": 1,
                         "default_min_interval_s": 0})
    out = hub.enqueue(db_session, "s", "b", category="digest_probe",
                      dedupe_key="d", now=T0)
    assert out == {"queued": False, "reason": "digest_disabled"}
    assert hub.snapshot()["queue_depth"] == 0
    set_config(db_session, "notify_digest_enabled", True)
    out2 = hub.enqueue(db_session, "s", "b", category="digest_probe",
                       dedupe_key="d", now=T0)
    assert out2 == {"queued": True}  # 开关开→收（本批无消费方）


def test_enqueue_queued_true_when_all_gates_pass(db_session, smtp_ready,
                                                 smtp_stub):
    out = hub.enqueue(db_session, "标题", "正文", category="token_budget",
                      dedupe_key="d1", now=T0)
    assert out == {"queued": True}
    assert hub.snapshot()["queue_depth"] == 1


# ---------- AC-1：flush 投递语义（按入队序/成功才落时间戳/失败丢弃） ----------


def test_flush_delivers_and_records_timestamp(db_session, smtp_ready,
                                              smtp_stub):
    hub.enqueue(db_session, "s1", "b1", category="token_budget",
                dedupe_key="d1", now=T0)
    out = hub.flush(db_session, now=T0)
    assert out["delivered"] == ["token_budget/d1"]
    assert out["deliver_failed"] == []
    assert out["kept"] == 0
    assert len(smtp_stub.calls) == 1
    # 时间戳仅投递成功才落（A1 语义保持）
    assert get_config(db_session, "notify_last_sent_token_budget_d1")
    assert hub.snapshot()["delivered_total"] == 1


def test_flush_deliver_failure_drops_without_timestamp(db_session, smtp_ready,
                                                       smtp_stub, caplog):
    """投递失败 WARN 并丢弃（不重试——告警类有下轮触发兜底）；不落时间戳。"""
    hub.enqueue(db_session, "s", "b", category="token_budget",
                dedupe_key="d1", now=T0)
    smtp_stub.fail = True
    with caplog.at_level(logging.WARNING, logger="newswright.notify"):
        out = hub.flush(db_session, now=T0)
    assert out["deliver_failed"] == ["token_budget/d1"]
    assert out["kept"] == 0
    assert get_config(db_session, "notify_last_sent_token_budget_d1") is None
    assert hub.snapshot()["dropped_total"] == {"token_budget": 1}
    assert any("投递失败" in r.message for r in caplog.records)


def test_flush_preserves_enqueue_order(db_session, smtp_ready, smtp_stub):
    """按入队序扫描：一轮 flush 同账户首封先出（硬间隔锚点即时更新拦住后继）。"""
    hub.enqueue(db_session, "s1", "b", category="disk_usage",
                dedupe_key="a", now=T0)
    hub.enqueue(db_session, "s2", "b", category="disk_usage",
                dedupe_key="b", now=T0 + timedelta(seconds=1))
    out = hub.flush(db_session, now=T0 + timedelta(seconds=2))
    assert out["delivered"] == ["disk_usage/a"]
    assert out["kept"] == 1
    out2 = hub.flush(db_session, now=T0 + timedelta(seconds=62))
    assert out2["delivered"] == ["disk_usage/b"]
    assert len(smtp_stub.calls) == 2


def test_flush_unconfigured_keeps_queue(db_session, smtp_ready, smtp_stub):
    """入队后配置被清空：flush 不投递不丢弃（等配置恢复后由后续 flush 投递）。"""
    hub.enqueue(db_session, "s", "b", category="disk_usage", dedupe_key="d",
                now=T0)
    set_config(db_session, "smtp_host", "")
    out = hub.flush(db_session, now=T0)
    assert out["delivered"] == [] and out["kept"] == 1
    assert smtp_stub.calls == []


# ---------- AC-1：双闸判定 ----------


def test_account_hard_interval_gate(db_session, smtp_ready, smtp_stub):
    """账户硬间隔 60s：未到→留队冷却缓存；到→投递（R2 最小发送硬间隔）。"""
    hub.enqueue(db_session, "s1", "b", category="token_budget",
                dedupe_key="d1", now=T0)
    assert hub.flush(db_session, now=T0)["delivered"] == ["token_budget/d1"]
    hub.enqueue(db_session, "s2", "b", category="disk_usage",
                dedupe_key="d2", now=T0 + timedelta(seconds=30))
    out = hub.flush(db_session, now=T0 + timedelta(seconds=30))
    assert out["delivered"] == [] and out["kept"] == 1  # 30s < 60s → 冷却
    assert len(smtp_stub.calls) == 1
    out2 = hub.flush(db_session, now=T0 + timedelta(seconds=61))
    assert out2["delivered"] == ["disk_usage/d2"]
    assert len(smtp_stub.calls) == 2


def test_category_interval_from_site_config(db_session, smtp_ready, smtp_stub):
    """类别最小间隔：site_config 覆盖（token_budget=3600s）→类别闸独立拦。"""
    set_config(db_session, "notify_category_intervals", {"token_budget": 3600})
    hub.enqueue(db_session, "s1", "b", category="token_budget",
                dedupe_key="d1", now=T0)
    assert hub.flush(db_session, now=T0)["delivered"] == ["token_budget/d1"]
    # 账户硬间隔已过（61s）但类别间隔 3600s 未到 → 留队
    hub.enqueue(db_session, "s2", "b", category="token_budget",
                dedupe_key="d2", now=T0 + timedelta(seconds=61))
    out = hub.flush(db_session, now=T0 + timedelta(seconds=61))
    assert out["delivered"] == [] and out["kept"] == 1
    out2 = hub.flush(db_session, now=T0 + timedelta(seconds=3661))
    assert out2["delivered"] == ["token_budget/d2"]


def test_category_default_interval_zero_only_account_gate(db_session,
                                                          smtp_ready,
                                                          smtp_stub):
    """缺省 0=仅账户硬间隔（行为最接近现状）：类别闸不拦。"""
    hub.enqueue(db_session, "s1", "b", category="token_budget",
                dedupe_key="d1", now=T0)
    assert hub.flush(db_session, now=T0)["delivered"] == ["token_budget/d1"]
    hub.enqueue(db_session, "s2", "b", category="token_budget",
                dedupe_key="d2", now=T0 + timedelta(seconds=61))
    out = hub.flush(db_session, now=T0 + timedelta(seconds=61))
    assert out["delivered"] == ["token_budget/d2"]


# ---------- AC-2：缓冲上限与丢弃序 ----------


def test_cap_evicts_same_priority_newest(db_session, smtp_ready, smtp_stub,
                                         caplog):
    """同级丢新留旧：第 11 封同 priority 挤出最新入队者；逐条 WARN+计数。"""
    for i in range(10):
        assert hub.enqueue(db_session, f"s{i}", "b",
                           category="source_hard_fail",
                           dedupe_key=f"k{i}", now=T0) == {"queued": True}
    assert hub.snapshot()["queue_depth"] == 10
    with caplog.at_level(logging.WARNING, logger="newswright.notify"):
        out = hub.enqueue(db_session, "s-new", "b", category="source_hard_fail",
                          dedupe_key="k-new", now=T0)
    assert out == {"queued": True}
    snap = hub.snapshot()
    assert snap["queue_depth"] == 10  # 上限不变
    assert snap["dropped_total"] == {"source_hard_fail": 1}
    assert any("队列" in r.message and "source_hard_fail" in r.message
               for r in caplog.records)
    # 被挤出的是 k-new（丢新留旧）：远期逐轮 flush 出 k0..k9、无 k-new
    t = T0
    keys: list[str] = []
    for _ in range(10):
        t += timedelta(seconds=61)
        keys += hub.flush(db_session, now=t)["delivered"]
    assert "source_hard_fail/k-new" not in keys
    assert keys == [f"source_hard_fail/k{i}" for i in range(10)]


def test_cap_evicts_higher_priority_number_first(db_session, smtp_ready,
                                                 smtp_stub):
    """priority 数值大者先挤出（reconcile=2 让位于 source_hard_fail=1）。"""
    hub.enqueue(db_session, "r", "b", category="reconcile",
                dedupe_key="r1", now=T0)
    for i in range(9):
        hub.enqueue(db_session, f"s{i}", "b", category="source_hard_fail",
                    dedupe_key=f"k{i}", now=T0)
    # 第 11 封（alert/priority=1）入队 → reconcile（priority=2）被挤出
    hub.enqueue(db_session, "s10", "b", category="source_hard_fail",
                dedupe_key="k10", now=T0)
    snap = hub.snapshot()
    assert snap["queue_depth"] == 10
    assert snap["dropped_total"] == {"reconcile": 1}
    t = T0
    keys: list[str] = []
    for _ in range(10):
        t += timedelta(seconds=61)
        keys += hub.flush(db_session, now=t)["delivered"]
    assert "reconcile/r1" not in keys
    assert len(keys) == 10


def test_cap_evicts_digest_family_before_alert(db_session, smtp_ready,
                                               smtp_stub, monkeypatch):
    """丢弃序最先：digest 族先于一切 alert（即便 priority 更低）。"""
    monkeypatch.setitem(hub.CATEGORY_REGISTRY, "digest_probe",
                        {"family": "digest", "priority": 0,
                         "default_min_interval_s": 0})
    set_config(db_session, "notify_digest_enabled", True)
    hub.enqueue(db_session, "d", "b", category="digest_probe",
                dedupe_key="d1", now=T0)
    for i in range(10):
        hub.enqueue(db_session, f"s{i}", "b", category="source_hard_fail",
                    dedupe_key=f"k{i}", now=T0)
    snap = hub.snapshot()
    assert snap["queue_depth"] == 10
    assert snap["dropped_total"] == {"digest_probe": 1}


# ---------- AC-2：snapshot 计数 ----------


def test_snapshot_counters_shape(db_session, smtp_ready, smtp_stub):
    hub.enqueue(db_session, "s1", "b", category="token_budget",
                dedupe_key="d1", now=T0)
    hub.flush(db_session, now=T0)
    hub.enqueue(db_session, "s2", "b", category="disk_usage",
                dedupe_key="d2", now=T0 + timedelta(seconds=5))
    hub.enqueue(db_session, "s3", "b", category="token_budget",
                dedupe_key="d1", now=T0 + timedelta(seconds=6))  # deduped（时间戳已落）
    assert hub.snapshot() == {"queue_depth": 1, "delivered_total": 1,
                              "dropped_total": {}, "deduped_total": 1}


# ---------- AC-3：去重窗口可配（缝隙 c）+ 键惰性清理（缝隙 d） ----------


def test_recently_sent_reads_configured_window(db_session, smtp_ready,
                                               smtp_stub):
    """_recently_sent 改读 site_config notify_dedup_window_hours（缺省 24）。"""
    from app.notify import get_notifier

    notifier = get_notifier("smtp", db_session)
    set_config(db_session, "notify_last_sent_disk_usage_k",
               (T0 - timedelta(hours=3)).isoformat())
    assert notifier._recently_sent("disk_usage", "k", now=T0) is True  # 3h<24h 缺省
    set_config(db_session, "notify_dedup_window_hours", 2)
    assert notifier._recently_sent("disk_usage", "k", now=T0) is False  # 3h>2h 配置
    set_config(db_session, "notify_dedup_window_hours", 4)
    assert notifier._recently_sent("disk_usage", "k", now=T0) is True   # 3h<4h 配置
    set_config(db_session, "notify_dedup_window_hours", 1)
    set_config(db_session, "notify_last_sent_disk_usage_k",
               (T0 - timedelta(hours=25)).isoformat())
    assert notifier._recently_sent("disk_usage", "k", now=T0) is False  # 25h>1h


def test_hub_dedupe_respects_configured_window(db_session, smtp_ready,
                                               smtp_stub):
    """hub 预检同样吃配置窗口：2h 窗口下 3h 前时间戳放行入队。"""
    set_config(db_session, "notify_dedup_window_hours", 2)
    set_config(db_session, "notify_last_sent_disk_usage_disk",
               (T0 - timedelta(hours=3)).isoformat())
    out = hub.enqueue(db_session, "s", "b", category="disk_usage",
                      dedupe_key="disk", now=T0)
    assert out == {"queued": True}


def test_dedupe_key_lazy_cleanup(db_session, smtp_ready, smtp_stub):
    """flush 时清理「早于 窗口+24h 宽限」的 notify_last_sent_% 键（全扫可接受）。"""
    over = (T0 - timedelta(hours=100)).isoformat()
    set_config(db_session, "notify_last_sent_disk_usage_old-1", over)
    set_config(db_session, "notify_last_sent_disk_usage_old-2", over)
    set_config(db_session, "notify_last_sent_disk_usage_fresh",
               (T0 - timedelta(hours=1)).isoformat())
    set_config(db_session, "notify_last_sent_disk_usage_garbage", "not-a-time")
    hub.flush(db_session, now=T0)
    assert get_config(db_session, "notify_last_sent_disk_usage_old-1") is None
    assert get_config(db_session, "notify_last_sent_disk_usage_old-2") is None
    assert get_config(db_session, "notify_last_sent_disk_usage_fresh") is not None
    # 坏值键不炸不清（防御面：留给下次清理再试）
    assert get_config(db_session, "notify_last_sent_disk_usage_garbage") \
        == "not-a-time"


def test_dedupe_key_cleanup_uses_configured_window_plus_grace(db_session,
                                                              smtp_ready,
                                                              smtp_stub):
    """清理口径=窗口+24h 宽限：窗口 2h → 26h 为界。"""
    set_config(db_session, "notify_dedup_window_hours", 2)
    set_config(db_session, "notify_last_sent_disk_usage_o",
               (T0 - timedelta(hours=27)).isoformat())  # > 2+24 → 删
    set_config(db_session, "notify_last_sent_disk_usage_n",
               (T0 - timedelta(hours=25)).isoformat())  # < 2+24 → 留
    hub.flush(db_session, now=T0)
    assert get_config(db_session, "notify_last_sent_disk_usage_o") is None
    assert get_config(db_session, "notify_last_sent_disk_usage_n") is not None


def test_dedupe_key_cleanup_throttled_hourly(db_session, smtp_ready,
                                             smtp_stub):
    """清理节流 >1h：间隔内再 flush 不重扫。"""
    hub.flush(db_session, now=T0)  # 首次清理
    set_config(db_session, "notify_last_sent_disk_usage_after",
               (T0 - timedelta(hours=100)).isoformat())
    hub.flush(db_session, now=T0 + timedelta(minutes=30))
    assert get_config(db_session, "notify_last_sent_disk_usage_after") \
        is not None  # 30min 内不重扫
    hub.flush(db_session, now=T0 + timedelta(minutes=61))
    assert get_config(db_session, "notify_last_sent_disk_usage_after") is None


# ---------- 接受语义：队列进程内、重启即丢 ----------


def test_queue_is_in_memory_restart_loses_accepted(db_session, smtp_ready,
                                                   smtp_stub):
    """文档性测试：重启丢队=接受语义（告警类有下轮触发兜底）——防未来误加
    持久化而不自知。"""
    for i in range(3):
        hub.enqueue(db_session, f"s{i}", "b", category="disk_usage",
                    dedupe_key=f"k{i}", now=T0)
    assert hub.snapshot()["queue_depth"] == 3
    hub._reset_for_tests()  # 模拟进程重启（模块级状态归零）
    assert hub.snapshot() == {"queue_depth": 0, "delivered_total": 0,
                              "dropped_total": {}, "deduped_total": 0}
    assert hub.flush(db_session, now=T0)["delivered"] == []
    assert smtp_stub.calls == []


# ---------- AC-5(e)：测试邮件端点经中枢 ----------


def test_notify_test_endpoint_via_hub_reason_forms(auth_client, db_session,
                                                   smtp_stub):
    """POST /settings/notify/test 经中枢同步试发：sent true / account_interval /
    deliver_failed 三态；未配置仍 502 SMTP_UNREACHABLE。"""
    r0 = auth_client.post("/api/settings/notify/test")
    assert r0.status_code == 502
    assert r0.json()["code"] == "SMTP_UNREACHABLE"
    set_config(db_session, "smtp_host", "smtp.example.com")
    set_config(db_session, "smtp_port", 465)
    set_config(db_session, "smtp_from", "bot@example.com")
    set_config(db_session, "smtp_to", ["me@example.com"])
    r1 = auth_client.post("/api/settings/notify/test")
    assert r1.status_code == 200
    assert r1.json() == {"sent": True}
    assert len(smtp_stub.calls) == 1
    # 账户硬间隔内再发 → account_interval（不真等 60s）
    r2 = auth_client.post("/api/settings/notify/test")
    assert r2.json() == {"sent": False, "reason": "account_interval"}
    assert len(smtp_stub.calls) == 1
    # 投递失败 → deliver_failed（清锚点模拟新进程，禁真等）
    hub._reset_for_tests()
    smtp_stub.fail = True
    r3 = auth_client.post("/api/settings/notify/test")
    assert r3.json() == {"sent": False, "reason": "deliver_failed"}


# ---------- AC-5(b)：notify_on_reconcile 进 PUT/GET ----------


def test_reconcile_switch_roundtrip(auth_client, db_session):
    r = auth_client.put("/api/settings/notify", json={
        "notify_on_reconcile": False})
    assert r.status_code == 200
    assert "notify_on_reconcile" in r.json()["changed_keys"]
    body = auth_client.get("/api/settings/notify").json()
    assert body["notify_on_reconcile"] is False


# ---------- triggers 改道集成（A3 咽喉单点） ----------


def test_dispatch_routes_through_hub(db_session, smtp_ready, smtp_stub):
    from app.notify.triggers import check_disk_usage

    set_config(db_session, "disk_usage_warn_percent", 0)
    out = check_disk_usage(db_session)
    assert out["queued"] is True and out["used_percent"] > 0
    assert smtp_stub.calls == []  # 入队不投递（经 flush）
    assert hub.flush(db_session)["delivered"] == ["disk_usage/disk"]


# ---------- flush job 挂载（A5 同款）与观测挂靠（A8） ----------


def test_notify_flush_job_registered():
    import app.scheduler as sched

    sched._register_jobs()
    try:
        jobs = {j.id: j for j in sched.scheduler.get_jobs()}
        job = jobs["notify_flush"]
        assert job.args[0] is sched._tick_notify_flush
        assert job.trigger.interval == timedelta(seconds=15)
        assert job.max_instances == 1
        assert job.coalesce is True
        # 「不启动即跑」=注册不传 next_run_time（对照 fetch_score_round 显式传
        # 启动即跑；未 start 的 scheduler 上二者均不可直接读回，以注册面为准）
    finally:
        sched.scheduler.remove_all_jobs()


def test_tick_notify_flush_delivers(db_session, smtp_ready, smtp_stub):
    """_tick_notify_flush 自带会话调 hub.flush（不真启动调度器）。"""
    import app.scheduler as sched

    hub.enqueue(db_session, "s", "b", category="token_budget",
                dedupe_key="d1", now=T0)
    sched._tick_notify_flush()
    assert len(smtp_stub.calls) == 1


def test_pipeline_stats_contains_notify_keys(auth_client, db_session,
                                             smtp_ready, smtp_stub):
    """pipeline stats 增 notify_queue_depth / notify_dropped_total（进程计数）。"""
    hub.enqueue(db_session, "s", "b", category="token_budget",
                dedupe_key="d1", now=T0)
    body = auth_client.get("/api/stats/pipeline").json()
    assert body["notify_queue_depth"] == 1
    assert body["notify_dropped_total"] == {}
