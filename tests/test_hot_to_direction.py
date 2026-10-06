"""热点一键转临时方向测试（产品书 US-17.2，设计依据见 docs/design-index.md「AC-17.2」）：
预填创建 temp 方向（temp=true、TTL 默认 7 天）+ 搜索源关键词（freshness=oneDay）；
人在环路确认后才开始采集（创建动作本身不触发任何采集任务）；同名 409。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Direction, PipelineTask, Source


@pytest.fixture()
def kw_payload():
    return {"keyword": "端侧大模型"}


def test_creates_temp_direction_with_ttl_and_prompt(auth_client, db_session, kw_payload):
    r = auth_client.post("/api/hot/to-direction", json=kw_payload)
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"direction_id", "source_id"}

    d = db_session.get(Direction, body["direction_id"])
    now = datetime.now(timezone.utc)
    assert d is not None and d.temp is True
    assert d.status == Direction.STATUS_ACTIVE
    assert d.prompt_version == 1
    assert "端侧大模型" in d.prompt  # 提示词预填模板含关键词
    # TTL 默认 7 天：到期时刻在 6.5~7.5 天窗口内（到期零点取整允许跨日偏移）
    expires = d.expires_at if d.expires_at.tzinfo else d.expires_at.replace(tzinfo=timezone.utc)
    assert timedelta(days=6) < expires - now < timedelta(days=8)


def test_creates_search_source_keyword_form_freshness(auth_client, db_session, kw_payload):
    r = auth_client.post("/api/hot/to-direction", json=kw_payload)
    body = r.json()
    s = db_session.get(Source, body["source_id"])
    assert s is not None
    assert s.type == "search"
    assert s.enabled is True
    assert s.direction_id == body["direction_id"]
    # url 关键词源形态：url 位承载关键词；时效默认 oneDay
    assert "端侧大模型" in s.url
    cfg = s.source_config or {}
    assert cfg.get("keyword") == "端侧大模型"
    assert cfg.get("freshness") == "oneDay"


def test_human_in_loop_no_auto_fetch(auth_client, db_session, kw_payload):
    """创建即确认：端点只建方向+源两行，不产生任何采集任务（调度不因其触发）。"""
    r = auth_client.post("/api/hot/to-direction", json=kw_payload)
    assert r.status_code == 201
    ingest_tasks = (
        db_session.query(PipelineTask)
        .filter(PipelineTask.kind.in_(("fetch", "fetch_round", "hot_round")))
        .all()
    )
    assert ingest_tasks == []


def test_same_name_direction_conflict_409(auth_client, db_session, kw_payload):
    db_session.add(Direction(name="端侧大模型", prompt="p", prompt_version=1,
                             threshold=60))
    db_session.commit()
    r = auth_client.post("/api/hot/to-direction", json=kw_payload)
    assert r.status_code == 409
    assert r.json() == {"code": "DIRECTION_NAME_EXISTS", "message": "同名方向已存在"}


def test_empty_keyword_rejected(auth_client):
    r = auth_client.post("/api/hot/to-direction", json={"keyword": "   "})
    assert r.status_code == 400


def test_requires_session(api_client, kw_payload):
    r = api_client.post("/api/hot/to-direction", json=kw_payload)
    assert r.status_code == 401
