"""来源软删除测试（UI2 W0c / P7 删除操作）。

契约：DELETE /api/sources/{id} 软删——deleted=true 且 enabled=false 一步到位
（列表隐藏 + 调度停抓，调度侧既有 enabled 过滤零改动）；已删除源对外即不存在
（再删 / PUT 均 404 SOURCE_NOT_FOUND）；条目数据保留（条目表零改动，该源
既有条目仍可查——P7 删除弹窗话术「该来源下 N 条内容将保留但不再更新」）。
"""
from app.db import SessionLocal
from app.models import Item, Source


def _mk_source(client, name: str = "软删测试方向") -> tuple[int, int]:
    r = client.post("/api/directions", json={"name": name, "prompt": "p", "threshold": 60})
    assert r.status_code == 201
    did = r.json()["id"]
    r = client.post(f"/api/directions/{did}/sources",
                    json={"type": "rss", "url": "https://soft-delete.example/rss.xml"})
    assert r.status_code == 201
    return did, r.json()["id"]


def test_delete_source_soft_and_idempotent(auth_client):
    """首删 200 {"id","deleted":true} 且行内 deleted=true/enabled=false；
    再删 404 SOURCE_NOT_FOUND（删除后对外即不存在）且终态不变。"""
    _did, sid = _mk_source(auth_client)
    r1 = auth_client.delete(f"/api/sources/{sid}")
    assert r1.status_code == 200
    assert r1.json() == {"id": sid, "deleted": True}
    with SessionLocal() as db:
        row = db.get(Source, sid)
        assert row.deleted is True and row.enabled is False
    r2 = auth_client.delete(f"/api/sources/{sid}")
    assert r2.status_code == 404
    assert r2.json()["code"] == "SOURCE_NOT_FOUND"
    with SessionLocal() as db:
        row = db.get(Source, sid)
        assert row.deleted is True and row.enabled is False


def test_delete_source_hidden_from_list(auth_client):
    """列表过滤：已删源从 GET /api/directions/{id}/sources 隐藏，同方向其余源仍在。"""
    did, sid = _mk_source(auth_client, "列表过滤方向")
    keep = auth_client.post(f"/api/directions/{did}/sources",
                            json={"type": "rss",
                                  "url": "https://soft-delete.example/keep.xml"})
    assert keep.status_code == 201
    assert auth_client.delete(f"/api/sources/{sid}").status_code == 200
    rows = auth_client.get(f"/api/directions/{did}/sources").json()
    ids = [s["id"] for s in rows]
    assert sid not in ids
    assert keep.json()["id"] in ids


def test_update_deleted_source_404(auth_client):
    """PUT 对 deleted 源 → 404 SOURCE_NOT_FOUND，且不改变行状态。"""
    _did, sid = _mk_source(auth_client, "更新拦截方向")
    assert auth_client.delete(f"/api/sources/{sid}").status_code == 200
    r = auth_client.put(f"/api/sources/{sid}", json={"enabled": True})
    assert r.status_code == 404
    assert r.json()["code"] == "SOURCE_NOT_FOUND"
    with SessionLocal() as db:
        assert db.get(Source, sid).enabled is False


def test_delete_source_keeps_items(auth_client):
    """条目保留：删除后该源既有条目仍可查（详情端点引用链不断）。"""
    did, sid = _mk_source(auth_client, "条目保留方向")
    with SessionLocal() as db:
        item = Item(source_id=sid, guid="keep-1", url="https://soft-delete.example/a",
                    title="保留条目", content_text="正文", fetch_status="FETCHED")
        db.add(item)
        db.commit()
        item_id = item.id
    assert auth_client.delete(f"/api/sources/{sid}").status_code == 200
    r = auth_client.get(f"/api/items/{item_id}")
    assert r.status_code == 200
    assert r.json()["title"] == "保留条目"
    assert r.json()["source"]["id"] == sid


def test_delete_missing_source_404_coded(auth_client):
    """不存在的来源 id → 404 coded SOURCE_NOT_FOUND。"""
    r = auth_client.delete("/api/sources/99999")
    assert r.status_code == 404
    assert r.json()["code"] == "SOURCE_NOT_FOUND"
