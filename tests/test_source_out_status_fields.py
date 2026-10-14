"""来源序列化状态字段测试（UI2 W0c / P7 来源表呈现面）。

契约：_source_out 补 8 个状态字段——last_fetched_at / rate_limited_until /
rate_level / keyword_limited_until / keyword_rate_level / hard_failures /
empty_rounds（Source 既有列直出）+ deleted（W0c 新列）；既有字段不回归。
"""
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import Source


def _mk_source(client, name: str = "状态字段方向") -> tuple[int, int]:
    r = client.post("/api/directions", json={"name": name, "prompt": "p", "threshold": 60})
    assert r.status_code == 201
    did = r.json()["id"]
    r = client.post(f"/api/directions/{did}/sources",
                    json={"type": "rss", "url": "https://status-fields.example/rss.xml"})
    assert r.status_code == 201
    return did, r.json()["id"]


def test_source_out_has_status_fields(auth_client):
    """8 个新字段在位；新库默认值直出（deleted=false、档位与计数为 0）。"""
    did, _sid = _mk_source(auth_client)
    rows = auth_client.get(f"/api/directions/{did}/sources").json()
    for key in ("last_fetched_at", "rate_limited_until", "rate_level",
                "keyword_limited_until", "keyword_rate_level",
                "hard_failures", "empty_rounds", "deleted"):
        assert key in rows[0], key
    assert rows[0]["deleted"] is False
    assert rows[0]["rate_level"] == 0 and rows[0]["keyword_rate_level"] == 0
    assert rows[0]["hard_failures"] == 0 and rows[0]["empty_rounds"] == 0
    assert rows[0]["last_fetched_at"] is None
    assert rows[0]["rate_limited_until"] is None
    assert rows[0]["keyword_limited_until"] is None


def test_source_out_reflects_degradation_state(auth_client):
    """降频态与 last_fetched_at：写非默认列值后列表如实直出。"""
    did, sid = _mk_source(auth_client, "降频态方向")
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        row = db.get(Source, sid)
        row.last_fetched_at = now
        row.rate_limited_until = now + timedelta(minutes=30)
        row.rate_level = 2
        row.keyword_limited_until = now + timedelta(hours=2)
        row.keyword_rate_level = 1
        row.hard_failures = 3
        row.empty_rounds = 5
        db.commit()
    out = auth_client.get(f"/api/directions/{did}/sources").json()[0]
    assert out["rate_level"] == 2 and out["keyword_rate_level"] == 1
    assert out["hard_failures"] == 3 and out["empty_rounds"] == 5
    assert out["last_fetched_at"] is not None
    assert out["rate_limited_until"] is not None
    assert out["keyword_limited_until"] is not None


def test_source_out_existing_fields_not_regressed(auth_client):
    """既有 12 字段不回归，取值语义不变。"""
    did, _sid = _mk_source(auth_client, "既有字段方向")
    out = auth_client.get(f"/api/directions/{did}/sources").json()[0]
    for key in ("id", "direction_id", "type", "url", "name", "enabled",
                "interval_minutes", "failure_level", "failure_since",
                "backoff_failures", "backoff_skips", "last_error"):
        assert key in out, key
    assert out["type"] == "rss" and out["enabled"] is True
    assert out["failure_level"] == "none" and out["name"] is None
