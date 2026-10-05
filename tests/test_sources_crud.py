"""来源管理 API 测试：新增/重复 409/停用/列表与源级间隔。

契约依据：技术书 §3 OpenAPI（POST /api/directions/{id}/sources、GET sources 列表、
PUT /api/sources/{id}）、产品书 US-04（AC-04.1 新增 RSS 源、AC-04.5 停用来源、
AC-04.6 源级间隔）。设计依据见 docs/design-index.md「AC-04.1」「AC-04.5」「AC-04.6」。
"""
from app.db import SessionLocal
from app.models import PipelineTask, Source
from app.pipeline.runner import enqueue_fetch_round


def _mk_direction(client, name: str = "来源管理方向") -> int:
    r = client.post("/api/directions", json={"name": name, "prompt": "p", "threshold": 60})
    assert r.status_code == 201
    return r.json()["id"]


def test_create_source_201(auth_client):
    """新增 RSS 源：201，响应含 id/type/enabled=true/failure_level=none。"""
    did = _mk_direction(auth_client)
    r = auth_client.post(f"/api/directions/{did}/sources",
                         json={"type": "rss", "url": "https://www.ithome.com/rss/"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] > 0 and body["direction_id"] == did
    assert body["type"] == "rss" and body["enabled"] is True
    assert body["failure_level"] == "none"


def test_create_source_duplicate_url_409(auth_client):
    """同方向重复注册同 URL → 409 SOURCE_URL_EXISTS。"""
    did = _mk_direction(auth_client)
    url = "https://www.ithome.com/rss/"
    r1 = auth_client.post(f"/api/directions/{did}/sources", json={"type": "rss", "url": url})
    assert r1.status_code == 201
    r2 = auth_client.post(f"/api/directions/{did}/sources", json={"type": "rss", "url": url})
    assert r2.status_code == 409
    assert r2.json()["code"] == "SOURCE_URL_EXISTS"


def test_create_source_same_url_other_direction_ok(auth_client):
    """同 URL 挂到另一方向是合法的（去重作用域=方向内，跨方向各自独立采集）。"""
    did1 = _mk_direction(auth_client, "方向甲")
    did2 = _mk_direction(auth_client, "方向乙")
    url = "https://feeds.example/shared.xml"
    assert auth_client.post(f"/api/directions/{did1}/sources",
                            json={"type": "rss", "url": url}).status_code == 201
    r = auth_client.post(f"/api/directions/{did2}/sources",
                         json={"type": "rss", "url": url})
    assert r.status_code == 201


def test_create_source_invalid_type_400(auth_client):
    """type 不在 rss|web|search 枚举内 → 400 VALIDATION_ERROR。"""
    did = _mk_direction(auth_client)
    r = auth_client.post(f"/api/directions/{did}/sources",
                         json={"type": "gopher", "url": "https://ex.com/f"})
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_list_sources_contains_failure_and_backoff_fields(auth_client):
    """来源列表：含 failure_level 与退避状态字段（采集面体检消费）。"""
    did = _mk_direction(auth_client)
    auth_client.post(f"/api/directions/{did}/sources",
                     json={"type": "rss", "url": "https://feeds.example/list.xml"})
    rows = auth_client.get(f"/api/directions/{did}/sources").json()
    assert len(rows) == 1
    for key in ("failure_level", "failure_since", "backoff_failures",
                "backoff_skips", "last_error", "enabled", "interval_minutes"):
        assert key in rows[0]
    assert rows[0]["failure_level"] == "none"


def test_disable_source_200_and_unscheduled(auth_client):
    """停用来源：200；此后调度不为其产生 fetch 任务；失效级别字段不变。"""
    did = _mk_direction(auth_client)
    sid = auth_client.post(f"/api/directions/{did}/sources",
                           json={"type": "rss", "url": "https://feeds.example/off.xml"}
                           ).json()["id"]

    r = auth_client.put(f"/api/sources/{sid}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["failure_level"] == "none"  # 停用不改失效判别状态

    rt = enqueue_fetch_round(SessionLocal(), triggered_by="test")
    assert rt is not None
    task_source_ids = [
        t.payload["source_id"]
        for t in SessionLocal().query(PipelineTask).filter_by(kind="fetch").all()
        if isinstance(t.payload, dict) and "source_id" in (t.payload or {})
    ]
    assert sid not in task_source_ids


def test_update_source_interval_minutes(auth_client):
    """源级间隔：PUT interval_minutes 落入 source_config，列表回显。"""
    did = _mk_direction(auth_client)
    sid = auth_client.post(f"/api/directions/{did}/sources",
                           json={"type": "rss", "url": "https://feeds.example/iv.xml"}
                           ).json()["id"]
    r = auth_client.put(f"/api/sources/{sid}", json={"interval_minutes": 720})
    assert r.status_code == 200
    assert r.json()["interval_minutes"] == 720
    rows = auth_client.get(f"/api/directions/{did}/sources").json()
    assert rows[0]["interval_minutes"] == 720


def test_update_missing_source_404(auth_client):
    """不存在的来源 id → 404 SOURCE_NOT_FOUND。"""
    r = auth_client.put("/api/sources/99999", json={"enabled": False})
    assert r.status_code == 404
    assert r.json()["code"] == "SOURCE_NOT_FOUND"
