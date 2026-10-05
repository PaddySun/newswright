"""方向重打分任务测试：202 派发 / 分批消化 / 旧分归档（重打分=新增行）。

契约依据：技术书 §3 OpenAPI（POST /api/directions/{id}/rescore → 202 + 任务 id）、
产品书 AC-07.6（任务按突发上限分批重打，完成后每条目存在新旧两行，旧分归档不覆盖）、
ADR-9（重打分走 pipeline_task 分批消化，复用 SCORE_ROUND_MAX_ITEMS 上限）。
设计依据见 docs/design-index.md「AC-07.6」「ADR-9」。
"""
import app.scoring.service as scoring_service
from app import config
from app.db import SessionLocal
from app.models import Item, PipelineTask, ScoreResult, Source
from app.pipeline.runner import score_round


def _mk_direction_with_scored_items(client, n: int, *, name: str = "重打分方向") -> int:
    """建方向（prompt_version=1）并植入 n 条已有 v1 OK 打分的条目。"""
    r = client.post("/api/directions", json={"name": name, "prompt": "p1", "threshold": 60})
    assert r.status_code == 201
    did = r.json()["id"]
    with SessionLocal() as db:
        src = Source(direction_id=did, url=f"https://feeds.example/rs-{did}.xml", type="rss")
        db.add(src)
        db.flush()
        for i in range(n):
            item = Item(source_id=src.id, guid=f"rs-{i}", url=f"https://ex.com/rs/{i}",
                        title=f"条目{i}", content_text="正文" * 150,
                        fetch_status="FETCHED", sanitize_status="PASSED",
                        direction_id=did)
            db.add(item)
            db.flush()
            db.add(ScoreResult(item_id=item.id, direction_id=did, quality_score=80,
                               relevance_score=90, band="high", reason="旧版理由",
                               prompt_version=1, model="m", passed=True, status="OK"))
        db.commit()
    return did


def _fake_score_factory(calls: list[int]):
    def fake_score(db, item, direction):
        calls.append(item.id)
        sr = ScoreResult(item_id=item.id, direction_id=direction.id,
                         quality_score=82, relevance_score=93, band="high",
                         reason="新版理由", prompt_version=direction.prompt_version,
                         model="m", passed=True, status="OK")
        db.add(sr)
        db.commit()
        return sr

    return fake_score


def test_rescore_dispatch_202_creates_task(auth_client):
    """rescore 入口：202 + 任务 id；任务落库 kind=rescore、PENDING、带 scope。"""
    did = _mk_direction_with_scored_items(auth_client, 1)
    r = auth_client.post(f"/api/directions/{did}/rescore", json={"scope": "all"})
    assert r.status_code == 202
    body = r.json()
    assert body["task_id"] > 0
    task = SessionLocal().get(PipelineTask, body["task_id"])
    assert task.kind == "rescore" and task.status == "PENDING"
    assert task.payload["direction_id"] == did
    assert task.payload["scope"] == "all"


def test_rescore_scope_validation_400_and_404(auth_client):
    """scope 非法 → 400 VALIDATION_ERROR；方向不存在 → 404 DIRECTION_NOT_FOUND。"""
    did = _mk_direction_with_scored_items(auth_client, 1, name="校验方向")
    r = auth_client.post(f"/api/directions/{did}/rescore", json={"scope": "bogus"})
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR"
    r = auth_client.post("/api/directions/99999/rescore", json={"scope": "all"})
    assert r.status_code == 404 and r.json()["code"] == "DIRECTION_NOT_FOUND"


def test_rescore_adds_new_rows_old_rows_kept(auth_client, monkeypatch):
    """重打分=新增行：完成后每条目存在 v1 与 v2 两行，旧分行原样保留。"""
    did = _mk_direction_with_scored_items(auth_client, 3)
    # 提示词升级到 v2 后发起重打分
    r = auth_client.put(f"/api/directions/{did}", json={"prompt": "p2 升级版"})
    assert r.json()["prompt_version"] == 2
    r = auth_client.post(f"/api/directions/{did}/rescore", json={"scope": "all"})
    task_id = r.json()["task_id"]

    calls: list[int] = []
    monkeypatch.setattr(scoring_service, "score_item", _fake_score_factory(calls))
    score_round(SessionLocal(), triggered_by="test", direction_id=did)

    assert len(calls) == 3
    task = SessionLocal().get(PipelineTask, task_id)
    assert task.status == "DONE"
    with SessionLocal() as db:
        versions = {}
        for row in db.query(ScoreResult).filter_by(direction_id=did).all():
            versions.setdefault(row.item_id, set()).add(row.prompt_version)
        assert all(v == {1, 2} for v in versions.values())  # 每条目新旧两行
        old_rows = [row for row in db.query(ScoreResult).filter_by(direction_id=did).all()
                    if row.prompt_version == 1]
        assert all(row.reason == "旧版理由" and row.model == "m" for row in old_rows)


def test_rescore_batch_cap_continuation(auth_client, monkeypatch):
    """分批消化：候选超出单轮上限时只处理一批，剩余派生后续任务继续。"""
    did = _mk_direction_with_scored_items(auth_client, 3)
    auth_client.put(f"/api/directions/{did}", json={"prompt": "p2 升级版"})
    auth_client.post(f"/api/directions/{did}/rescore", json={"scope": "all"})
    monkeypatch.setattr(config, "SCORE_ROUND_MAX_ITEMS", 2)

    calls: list[int] = []
    monkeypatch.setattr(scoring_service, "score_item", _fake_score_factory(calls))
    score_round(SessionLocal(), triggered_by="test", direction_id=did)
    assert len(calls) == 2  # 首批只消化 2 条
    pending = [t for t in SessionLocal().query(PipelineTask)
               .filter_by(kind="rescore", status="PENDING").all()]
    assert len(pending) == 1  # 后续任务已派生

    score_round(SessionLocal(), triggered_by="test", direction_id=did)
    assert len(calls) == 3  # 第二批消化剩余 1 条
    assert not [t for t in SessionLocal().query(PipelineTask)
                .filter_by(kind="rescore", status="PENDING").all()]


def test_rescore_failed_scope_targets_only_failed(auth_client, monkeypatch):
    """scope=failed：只补打只有 FAILED 行的条目，已有 OK 行的条目不动。"""
    did = _mk_direction_with_scored_items(auth_client, 2)
    with SessionLocal() as db:
        src = db.query(Source).filter_by(direction_id=did).one()
        bad = Item(source_id=src.id, guid="rs-bad", url="https://ex.com/rs/bad",
                   title="失败条目", content_text="正文" * 150,
                   fetch_status="FETCHED", sanitize_status="PASSED", direction_id=did)
        db.add(bad)
        db.flush()
        db.add(ScoreResult(item_id=bad.id, direction_id=did, reason="", prompt_version=1,
                           model="m", passed=False, status="FAILED", error="解析失败"))
        db.commit()

    r = auth_client.post(f"/api/directions/{did}/rescore", json={"scope": "failed"})
    r.json()["task_id"]
    calls: list[int] = []
    monkeypatch.setattr(scoring_service, "score_item", _fake_score_factory(calls))
    score_round(SessionLocal(), triggered_by="test", direction_id=did)
    assert len(calls) == 1  # 仅 FAILED 条目被补打
