"""方向重打分任务测试：202 派发 / 分批消化 / 旧分归档（重打分=新增行）。

契约依据：技术书 §3 OpenAPI（POST /api/directions/{id}/rescore → 202 + 任务 id）、
产品书 AC-07.6（任务按突发上限分批重打，完成后每条目存在新旧两行，旧分归档不覆盖）、
ADR-9（重打分走 pipeline_task 分批消化，复用 SCORE_ROUND_MAX_ITEMS 上限）。
设计依据见 docs/design-index.md「AC-07.6」「ADR-9」。
"""
import app.scoring.service as scoring_service
from app import config
from app.db import SessionLocal
from app.models import Direction, Item, PipelineTask, ScoreResult, Source
from app.pipeline.runner import process_rescore_tasks, score_round


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


def _bump_to_v2(client, did: int) -> None:
    """把方向提示词升到 v2（当前版切换，制造「缺当前版 OK 行」候选）。"""
    r = client.put(f"/api/directions/{did}", json={"prompt": "p2 升级版"})
    assert r.json()["prompt_version"] == 2


def _add_item(db, src: Source, did: int, guid: str, *, fetch_status="FETCHED"):
    it = Item(source_id=src.id, guid=guid, url=f"https://ex.com/rc/{guid}",
              title=f"候选-{guid}", content_text="正文" * 150,
              fetch_status=fetch_status, sanitize_status="PASSED", direction_id=did)
    db.add(it)
    db.flush()
    return it


def _ok_row(db, did: int, item_id: int, ver: int) -> None:
    db.add(ScoreResult(item_id=item_id, direction_id=did, quality_score=80,
                       relevance_score=90, band="high", reason="行",
                       prompt_version=ver, model="m", passed=True, status="OK"))


def _add_rescore_task(db, did: int, scope: str) -> int:
    t = PipelineTask(kind="rescore", status="PENDING",
                     payload={"direction_id": did, "scope": scope})
    db.add(t)
    db.commit()
    return t.id


def test_rescore_all_scope_candidate_set(auth_client, monkeypatch):
    """scope=all 候选集：已有 OK 行但缺当前版本 OK 行的条目（含旧版 OK +
    当前版失败的补打情形）+ 无任何 OK 行的 ARCHIVED 条目；仅 FAILED 行的
    条目、无行新条目、已补齐当前版本 OK 行的条目（含 ARCHIVED）不入列。"""
    did = _mk_direction_with_scored_items(auth_client, 1)  # P：OK@v1
    _bump_to_v2(auth_client, did)
    with SessionLocal() as db:
        src = db.query(Source).filter_by(direction_id=did).one()
        p_id = db.query(Item).filter_by(guid="rs-0").one().id
        r_cur = _add_item(db, src, did, "rc-cur")          # R：OK@v2 已补齐
        _ok_row(db, did, r_cur.id, 2)
        f_fail = _add_item(db, src, did, "rc-fail")        # F：仅 FAILED 行
        db.add(ScoreResult(item_id=f_fail.id, direction_id=did, reason="",
                           prompt_version=1, model="m", passed=False,
                           status="FAILED", error="解析失败"))
        _add_item(db, src, did, "rc-new")                  # Q：无任何行
        s_arch_ok = _add_item(db, src, did, "rc-arch-ok", fetch_status="ARCHIVED")
        _ok_row(db, did, s_arch_ok.id, 2)                  # S：ARCHIVED+OK@v2
        s_arch = _add_item(db, src, did, "rc-arch", fetch_status="ARCHIVED")  # S2
        fv = _add_item(db, src, did, "rc-fv")              # FV：OK@v1 + FAILED@v2
        _ok_row(db, did, fv.id, 1)
        db.add(ScoreResult(item_id=fv.id, direction_id=did, reason="",
                           prompt_version=2, model="m", passed=False,
                           status="FAILED", error="解析失败"))
        expected = sorted([p_id, s_arch.id, fv.id])
        _add_rescore_task(db, did, "all")
    calls: list[int] = []
    monkeypatch.setattr(scoring_service, "score_item", _fake_score_factory(calls))
    process_rescore_tasks(SessionLocal())
    assert sorted(calls) == expected


def test_rescore_failed_scope_candidate_set(auth_client, monkeypatch):
    """scope=failed 候选集：只补打仅落过 FAILED 行的条目；已有 OK 行的
    条目（即使缺当前版本行）与无行新条目不入列。"""
    did = _mk_direction_with_scored_items(auth_client, 1)  # P：OK@v1（缺 v2 行）
    _bump_to_v2(auth_client, did)
    with SessionLocal() as db:
        src = db.query(Source).filter_by(direction_id=did).one()
        p_id = db.query(Item).filter_by(guid="rs-0").one().id
        f2 = _add_item(db, src, did, "rc-fail2")
        db.add(ScoreResult(item_id=f2.id, direction_id=did, reason="",
                           prompt_version=1, model="m", passed=False,
                           status="FAILED", error="解析失败"))
        _add_item(db, src, did, "rc-new2")                 # 无行新条目
        task_id = _add_rescore_task(db, did, "failed")
    calls: list[int] = []
    monkeypatch.setattr(scoring_service, "score_item", _fake_score_factory(calls))
    process_rescore_tasks(SessionLocal())
    assert calls == [f2.id]  # 恰好 FAILED 条目；P（all 会选）不得混入
    assert p_id not in calls


def test_rescore_broken_direction_fails_and_queue_continues(auth_client, monkeypatch):
    """方向缺失/已删除的任务落 FAILED 且失败原因落库；队列中后续
    rescore 任务照常消化，不得被单个坏任务饿死。"""
    did = _mk_direction_with_scored_items(auth_client, 1)
    _bump_to_v2(auth_client, did)  # 制造缺当前版 OK 行的候选
    with SessionLocal() as db:
        t1 = _add_rescore_task(db, 999999, "all")  # 方向不存在
        t2 = _add_rescore_task(db, did, "all")
    calls: list[int] = []
    monkeypatch.setattr(scoring_service, "score_item", _fake_score_factory(calls))
    process_rescore_tasks(SessionLocal())
    with SessionLocal() as db:
        t1_row = db.get(PipelineTask, t1)
        assert t1_row.status == "FAILED"
        assert t1_row.last_error  # 失败原因落库
        assert db.get(PipelineTask, t2).status == "DONE"
    assert len(calls) == 1


def test_rescore_processor_only_touches_rescore_kind(auth_client, monkeypatch):
    """rescore 处理器只消化 kind=rescore 的 PENDING 任务：其他 kind 的
    待执行任务不得被认领或终结。"""
    did = _mk_direction_with_scored_items(auth_client, 1)
    _bump_to_v2(auth_client, did)
    with SessionLocal() as db:
        fetch_task = PipelineTask(kind="fetch", status="PENDING",
                                  payload={"source_id": 1, "url": "https://x"})
        db.add(fetch_task)
        db.commit()
        fetch_id = fetch_task.id
        _add_rescore_task(db, did, "all")
    calls: list[int] = []
    monkeypatch.setattr(scoring_service, "score_item", _fake_score_factory(calls))
    process_rescore_tasks(SessionLocal())
    with SessionLocal() as db:
        row = db.get(PipelineTask, fetch_id)
        assert row.status == "PENDING" and row.attempts == 0
    assert len(calls) == 1  # rescore 任务本身照常消化


def test_rescore_stats_ledger_counts(auth_client, monkeypatch):
    """完成任务账本：payload.stats 按契约键如实计数——rescored=成功重打数、
    call_failed=调用失败数（含落 FAILED 行与抛异常两种失败）、
    remaining=剩余候选、scope=任务范围；计数跨多次失败累进不丢失。"""
    did = _mk_direction_with_scored_items(auth_client, 5)
    _bump_to_v2(auth_client, did)
    task_id = None
    with SessionLocal() as db:
        task_id = _add_rescore_task(db, did, "all")

    def _ok_call(db, item, direction):
        sr = ScoreResult(item_id=item.id, direction_id=direction.id,
                         quality_score=82, relevance_score=93, band="high",
                         reason="新版理由", prompt_version=direction.prompt_version,
                         model="m", passed=True, status="OK")
        db.add(sr)
        db.commit()
        return sr

    def _failed_call(db, item, direction):
        sr = ScoreResult(item_id=item.id, direction_id=direction.id, reason="",
                         prompt_version=direction.prompt_version, model="m",
                         passed=False, status="FAILED", error="JSONParseError: 耗尽")
        db.add(sr)
        db.commit()
        return sr

    calls: list[int] = []

    def score(db, item, direction):
        # 五候选项依次：成功 / 异常 / 落 FAILED 行 / 异常 / 成功
        calls.append(item.id)
        if len(calls) in (2, 4):
            raise RuntimeError("模拟打分异常")
        if len(calls) == 3:
            return _failed_call(db, item, direction)
        return _ok_call(db, item, direction)

    monkeypatch.setattr(scoring_service, "score_item", score)
    process_rescore_tasks(SessionLocal())
    task = SessionLocal().get(PipelineTask, task_id)
    assert task.payload["stats"] == {"rescored": 2, "call_failed": 3,
                                     "remaining": 0, "scope": "all"}
    assert task.status == "DONE"
