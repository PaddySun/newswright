"""方向管理 API 测试：创建/编辑升版/软删除/临时方向 TTL 四景。

契约依据：技术书 §3 OpenAPI（POST/PUT/DELETE /api/directions，响应码与错误体）、
产品书 US-03 全组（创建 201 版本从 1 起、改 prompt 必升版本且历史打分行版本不变、
软删除 204 列表不含条目保留不再调度、temp 方向 TTL 到期 expired）。
设计依据见 docs/design-index.md「AC-03.1」「AC-03.2」「AC-03.3」「AC-03.4」。
"""
from datetime import datetime, timedelta, timezone

from app.db import SessionLocal
from app.models import Direction, Item, PipelineTask, ScoreResult, Source
from app.pipeline.runner import enqueue_fetch_round


def _create(client, **overrides) -> dict:
    body = {"name": "AI 与软件工程",
            "prompt": "关注 AI 工程实践：模型发布、推理优化、测试与工具链。",
            "threshold": 60}
    body.update(overrides)
    return client.post("/api/directions", json=body)


def _mk_source_and_item(db, direction_id: int, guid: str = "g-1") -> tuple[int, int]:
    """造一个源 + 一条可被打分引用的条目，返回 (source_id, item_id)。"""
    src = Source(direction_id=direction_id, url=f"https://feeds.example/{guid}.xml",
                 type="rss")
    db.add(src)
    db.flush()
    item = Item(source_id=src.id, guid=guid, url="https://ex.com/1", title="条目",
                content_text="正文" * 150, fetch_status="FETCHED",
                sanitize_status="PASSED", direction_id=direction_id)
    db.add(item)
    db.commit()
    return src.id, item.id


def test_create_direction_201_version_one(auth_client):
    """创建方向：201、prompt_version 从 1 起、enabled 派生真值（仅 active 为真）。"""
    r = _create(auth_client)
    assert r.status_code == 201
    body = r.json()
    assert body["id"] > 0
    assert body["prompt_version"] == 1
    assert body["threshold"] == 60
    assert body["enabled"] is True
    assert body["status"] == "active"
    assert body["temp"] is False and body["expires_at"] is None


def test_create_direction_validation_error_400(auth_client):
    """缺必填字段（prompt）→ 400 VALIDATION_ERROR（message 含字段路径）。"""
    r = auth_client.post("/api/directions", json={"name": "缺 prompt", "threshold": 60})
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "prompt" in body["message"]


def test_create_direction_threshold_out_of_range_400(auth_client):
    """threshold 越界（>100）→ 400 VALIDATION_ERROR。"""
    r = _create(auth_client, threshold=101)
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_edit_prompt_bumps_version_history_kept(auth_client):
    """编辑提示词：prompt_version 1→2；已有打分行的版本号保持 1 不变（历史可回溯）；
    未改动 prompt 的编辑不升版本。"""
    d = _create(auth_client).json()
    with SessionLocal() as db:
        _, item_id = _mk_source_and_item(db, d["id"])
        db.add(ScoreResult(item_id=item_id, direction_id=d["id"], quality_score=80,
                           relevance_score=90, band="high", reason="r", prompt_version=1,
                           model="deepseek-flash", passed=True, status="OK"))
        db.commit()

    r = auth_client.put(f"/api/directions/{d['id']}",
                        json={"prompt": "改版后的提示词，范围收窄。"})
    assert r.status_code == 200
    assert r.json()["prompt_version"] == 2

    with SessionLocal() as db:
        rows = db.query(ScoreResult).filter_by(direction_id=d["id"]).all()
        assert len(rows) == 1 and rows[0].prompt_version == 1  # 历史打分行版本不变

    r = auth_client.put(f"/api/directions/{d['id']}", json={"threshold": 70})
    assert r.status_code == 200
    assert r.json()["prompt_version"] == 2  # 非 prompt 编辑不升版本
    assert r.json()["threshold"] == 70


def test_soft_delete_204_data_kept_and_unscheduled(auth_client):
    """软删除：204；列表不含；items 查询 404 DIRECTION_DELETED；条目与打分全保留；
    该方向的源不再进入采集调度。"""
    d = _create(auth_client).json()
    with SessionLocal() as db:
        source_id, item_id = _mk_source_and_item(db, d["id"], guid="g-del")
        db.add(ScoreResult(item_id=item_id, direction_id=d["id"], quality_score=80,
                           relevance_score=90, band="high", reason="r", prompt_version=1,
                           model="m", passed=True, status="OK"))
        db.commit()

    r = auth_client.delete(f"/api/directions/{d['id']}")
    assert r.status_code == 204

    listed = auth_client.get("/api/directions").json()
    assert all(row["id"] != d["id"] for row in listed)  # 列表不含已删方向

    r = auth_client.get(f"/api/items?direction_id={d['id']}")
    assert r.status_code == 404
    assert r.json()["code"] == "DIRECTION_DELETED"

    with SessionLocal() as db:
        assert db.get(Item, item_id) is not None  # 条目全保留
        assert db.query(ScoreResult).filter_by(direction_id=d["id"]).count() == 1
        deleted = db.get(Direction, d["id"])
        assert deleted.status == "deleted" and deleted.deleted_at is not None

    # 该方向的源不再进入采集调度（不再产生 fetch 任务）
    rt = enqueue_fetch_round(SessionLocal(), triggered_by="test")
    assert rt is not None
    task_ids = [
        t.payload["source_id"]
        for t in SessionLocal().query(PipelineTask).filter_by(kind="fetch").all()
        if isinstance(t.payload, dict) and "source_id" in (t.payload or {})
    ]
    assert source_id not in task_ids


def test_deleted_direction_further_ops_404(auth_client):
    """已软删方向再编辑/再删除 → 404 DIRECTION_DELETED；不存在 id → DIRECTION_NOT_FOUND。"""
    d = _create(auth_client).json()
    auth_client.delete(f"/api/directions/{d['id']}")
    r = auth_client.put(f"/api/directions/{d['id']}", json={"threshold": 50})
    assert r.status_code == 404 and r.json()["code"] == "DIRECTION_DELETED"
    r = auth_client.delete(f"/api/directions/{d['id']}")
    assert r.status_code == 404 and r.json()["code"] == "DIRECTION_DELETED"
    r = auth_client.put("/api/directions/99999", json={"threshold": 50})
    assert r.status_code == 404 and r.json()["code"] == "DIRECTION_NOT_FOUND"


def test_temp_direction_ttl_expiry(auth_client):
    """临时方向：创建时按 ttl_days 得到 expires_at；到期后 status=expired、
    列表可见但不再进入采集调度（历史数据保留）。"""
    r = _create(auth_client, name="RAG 追踪", threshold=50, temp=True, ttl_days=14)
    assert r.status_code == 201
    body = r.json()
    assert body["temp"] is True
    assert body["expires_at"] is not None
    assert body["status"] == "active"

    with SessionLocal() as db:
        source_id, _ = _mk_source_and_item(db, body["id"], guid="g-ttl")

    # 到期：把 expires_at 拨到过去（等价验证，不真等 TTL）
    past = datetime.now(timezone.utc) - timedelta(days=1)
    with SessionLocal() as db:
        d = db.get(Direction, body["id"])
        d.expires_at = past
        db.commit()

    listed = auth_client.get("/api/directions").json()
    row = next(row for row in listed if row["id"] == body["id"])
    assert row["status"] == "expired" and row["enabled"] is False  # 懒扫描已翻态

    rt = enqueue_fetch_round(SessionLocal(), triggered_by="test")
    assert rt is not None
    task_source_ids = [
        t.payload["source_id"]
        for t in SessionLocal().query(PipelineTask).filter_by(kind="fetch").all()
        if isinstance(t.payload, dict) and "source_id" in (t.payload or {})
    ]
    assert source_id not in task_source_ids

    with SessionLocal() as db:  # 历史数据保留（条目不删）
        assert db.query(Item).filter_by(source_id=source_id).count() == 1


def test_list_directions_excludes_deleted_only(auth_client):
    """方向列表：active/disabled/expired 都可见，仅 deleted 不出现。"""
    d1 = _create(auth_client, name="方向一").json()
    d2 = _create(auth_client, name="方向二").json()
    auth_client.delete(f"/api/directions/{d2['id']}")
    listed = auth_client.get("/api/directions").json()
    ids = {row["id"] for row in listed}
    assert d1["id"] in ids and d2["id"] not in ids
