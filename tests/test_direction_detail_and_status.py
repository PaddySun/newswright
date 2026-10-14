"""方向单条与启停测试（UI2 W0c / P7 方向表单面）。

契约：GET /api/directions/{id} 单条 = _direction_out 形态（与列表行同构）；
PUT /api/directions/{id}/status body {"status":"active"|"disabled"} →
Direction.apply_status()（enabled 镜像同步），非法值 400 VALIDATION_ERROR，
deleted 不可经此端点设置（生命周期删除走既有 DELETE）；404 两态沿既有判别。
"""
from app.db import SessionLocal
from app.models import Direction


def _mk_direction(client, name: str = "单条与启停方向", **extra) -> int:
    payload = {"name": name, "prompt": "追踪测试", "threshold": 60, **extra}
    r = client.post("/api/directions", json=payload)
    assert r.status_code == 201
    return r.json()["id"]


def test_direction_detail_shape(auth_client):
    """单条 200 = _direction_out 形态（与列表行同构的八个键）。"""
    did = _mk_direction(auth_client)
    r = auth_client.get(f"/api/directions/{did}")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"id", "name", "prompt", "prompt_version",
                                "threshold", "enabled", "temp", "expires_at",
                                "status"}
    assert body["id"] == did and body["name"] == "单条与启停方向"
    assert body["status"] == "active" and body["enabled"] is True


def test_direction_detail_404_two_states(auth_client):
    """不存在 → 404 DIRECTION_NOT_FOUND；已软删 → 404 DIRECTION_DELETED。"""
    r = auth_client.get("/api/directions/99999")
    assert r.status_code == 404
    assert r.json()["code"] == "DIRECTION_NOT_FOUND"
    did = _mk_direction(auth_client, "已删单查方向")
    assert auth_client.delete(f"/api/directions/{did}").status_code == 204
    r = auth_client.get(f"/api/directions/{did}")
    assert r.status_code == 404
    assert r.json()["code"] == "DIRECTION_DELETED"


def test_direction_status_switch_and_enabled_mirror(auth_client):
    """status 切 active·disabled：apply_status 切状态并同步 enabled 镜像；
    切回 active 后镜像复活。"""
    did = _mk_direction(auth_client, "启停切换方向")
    r = auth_client.put(f"/api/directions/{did}/status", json={"status": "disabled"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "disabled" and body["enabled"] is False
    with SessionLocal() as db:
        row = db.get(Direction, did)
        assert row.status == "disabled" and row.enabled is False  # 行内同步
    r = auth_client.put(f"/api/directions/{did}/status", json={"status": "active"})
    assert r.status_code == 200
    assert r.json()["status"] == "active" and r.json()["enabled"] is True
    with SessionLocal() as db:
        row = db.get(Direction, did)
        assert row.status == "active" and row.enabled is True


def test_direction_status_invalid_value_400(auth_client):
    """非法值（含 "deleted"/"expired" 生命周期态）→ 400 VALIDATION_ERROR。"""
    did = _mk_direction(auth_client, "非法值方向")
    for bad in ("deleted", "expired", "paused", ""):
        r = auth_client.put(f"/api/directions/{did}/status", json={"status": bad})
        assert r.status_code == 400, bad
        assert r.json()["code"] == "VALIDATION_ERROR"
    with SessionLocal() as db:
        assert db.get(Direction, did).status == "active"  # 状态未被扰动


def test_direction_status_404_two_states(auth_client):
    """status 切换的不存在/已删两态与单条同判别。"""
    r = auth_client.put("/api/directions/99999/status", json={"status": "active"})
    assert r.status_code == 404
    assert r.json()["code"] == "DIRECTION_NOT_FOUND"
    did = _mk_direction(auth_client, "已删启停方向")
    assert auth_client.delete(f"/api/directions/{did}").status_code == 204
    r = auth_client.put(f"/api/directions/{did}/status", json={"status": "active"})
    assert r.status_code == 404
    assert r.json()["code"] == "DIRECTION_DELETED"
