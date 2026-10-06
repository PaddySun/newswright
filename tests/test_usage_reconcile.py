"""月度计费对账端点测试（外部调用统一纪律的计费对账句，设计依据见
docs/design-index.md「ADR-8」）：账本汇总 vs 平台账单、偏差 >10% 告警
（通知+结构化 ERROR）、同月重复提交覆盖（幂等）；month 格式校验。
"""
from datetime import datetime, timezone

import pytest

from app.models import UsageLog
from app.siteconfig import get_config


@pytest.fixture()
def month_rows(db_session):
    """2026-09 账本：100 units（另有一条 2026-08 行不参与当月汇总）。"""
    db_session.add_all([
        UsageLog(provider="moark", model="m", call_point="scoring",
                 billing_units=60, created_at=datetime(2026, 9, 5, 12, tzinfo=timezone.utc)),
        UsageLog(provider="moark", model="m", call_point="scoring",
                 billing_units=40, created_at=datetime(2026, 9, 28, 23, tzinfo=timezone.utc)),
        UsageLog(provider="moark", model="m", call_point="scoring",
                 billing_units=999, created_at=datetime(2026, 8, 31, 23, tzinfo=timezone.utc)),
    ])
    db_session.commit()


def test_reconcile_zero_deviation_no_alert(auth_client, db_session, month_rows):
    r = auth_client.post("/api/settings/usage/reconcile",
                         json={"month": "2026-09", "platform_billed_units": 100})
    assert r.status_code == 200
    assert r.json() == {"month": "2026-09", "ledger_units": 100,
                        "platform_units": 100, "deviation_pct": 0.0, "alerted": False}


def test_reconcile_over_threshold_alerts(auth_client, db_session, month_rows,
                                         monkeypatch):
    """偏差 >10%：结构化 ERROR 日志行 + 通知触发（category=reconcile）。"""
    sent = []

    def fake_dispatch(db, *, switch_key, category, dedupe_key, subject, body):
        sent.append((category, dedupe_key))
        return {"sent": True}

    monkeypatch.setattr("app.notify.triggers._dispatch", fake_dispatch)
    import logging as _logging

    records = []

    class _Handler(_logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Handler()
    logger = _logging.getLogger("newswright.reconcile")
    logger.addHandler(handler)
    try:
        r = auth_client.post("/api/settings/usage/reconcile",
                             json={"month": "2026-09", "platform_billed_units": 130})
    finally:
        logger.removeHandler(handler)
    body = r.json()
    assert body["ledger_units"] == 100 and body["platform_units"] == 130
    assert body["deviation_pct"] == 30.0 and body["alerted"] is True
    assert sent == [("reconcile", "reconcile-2026-09")]
    error_lines = [x for x in records
                   if x.levelno == _logging.ERROR and "2026-09" in x.getMessage()]
    assert error_lines, "偏差超阈必须落 ERROR 级日志行"


def test_reconcile_within_threshold_no_alert(auth_client, db_session, month_rows,
                                             monkeypatch):
    sent = []
    monkeypatch.setattr("app.notify.triggers._dispatch",
                        lambda db, **kw: sent.append(kw) or {"sent": True})
    r = auth_client.post("/api/settings/usage/reconcile",
                         json={"month": "2026-09", "platform_billed_units": 108})
    assert r.json()["deviation_pct"] == 8.0 and r.json()["alerted"] is False
    assert sent == []


def test_reconcile_same_month_resubmit_overwrites_record(auth_client, db_session,
                                                         month_rows):
    """幂等语义：同月重复提交=覆盖对账记录（site_config 快照承载，末次为准）。"""
    auth_client.post("/api/settings/usage/reconcile",
                     json={"month": "2026-09", "platform_billed_units": 100})
    auth_client.post("/api/settings/usage/reconcile",
                     json={"month": "2026-09", "platform_billed_units": 150})
    snapshot = get_config(db_session, "usage_reconcile_2026-09")
    assert snapshot["platform_units"] == 150 and snapshot["deviation_pct"] == 50.0


def test_reconcile_malformed_month_rejected(auth_client):
    r = auth_client.post("/api/settings/usage/reconcile",
                         json={"month": "2026-9", "platform_billed_units": 10})
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_reconcile_requires_session(api_client):
    r = api_client.post("/api/settings/usage/reconcile",
                        json={"month": "2026-09", "platform_billed_units": 10})
    assert r.status_code == 401
