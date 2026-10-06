"""搜索关键词降频手工恢复端点测试（产品书 §0 搜索关键词边际降频决策的恢复
条件之一——站长手工刷新，设计依据见 docs/design-index.md「D20」）：
POST /api/directions/{id}/refresh-keyword → 200 {"reset":<n>}；404；会话守卫。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Direction, Source


@pytest.fixture()
def direction_with_limited_search_source(db_session):
    d = Direction(name="刷新方向", prompt="p", prompt_version=1, threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="search://refresh/词", type="search",
                 source_config={"keyword": "词", "provider": "fakeprov"},
                 keyword_zero_rounds=8, keyword_rate_level=2,
                 keyword_limited_until=datetime.now(timezone.utc) + timedelta(hours=1))
    db_session.add(src)
    # 同方向另一搜索源：本就无降频（复位计数不含它）
    src2 = Source(direction_id=d.id, url="search://refresh/词乙", type="search",
                  source_config={"keyword": "词乙", "provider": "fakeprov"})
    db_session.add(src2)
    # 他方向搜索源：不受本端点影响
    d2 = Direction(name="他方向", prompt="p", prompt_version=1, threshold=60)
    db_session.add(d2)
    db_session.commit()
    src3 = Source(direction_id=d2.id, url="search://other/词", type="search",
                  source_config={"keyword": "词", "provider": "fakeprov"},
                  keyword_zero_rounds=7, keyword_rate_level=1)
    db_session.add(src3)
    db_session.commit()
    return d, src, src2, src3


def test_refresh_resets_limited_sources_in_direction(auth_client, db_session,
                                                     direction_with_limited_search_source):
    d, src, src2, src3 = direction_with_limited_search_source
    r = auth_client.post(f"/api/directions/{d.id}/refresh-keyword")
    assert r.status_code == 200
    assert r.json() == {"reset": 1}  # 只有 src 处于降频态（src2 本就干净）
    db_session.refresh(src)
    assert src.keyword_zero_rounds == 0 and src.keyword_rate_level == 0
    assert src.keyword_limited_until is None
    db_session.refresh(src3)
    assert src3.keyword_zero_rounds == 7  # 他方向不动


def test_refresh_direction_not_found(auth_client):
    r = auth_client.post("/api/directions/99999/refresh-keyword")
    assert r.status_code == 404
    assert r.json()["code"] == "DIRECTION_NOT_FOUND"


def test_refresh_requires_session(api_client):
    r = api_client.post("/api/directions/1/refresh-keyword")
    assert r.status_code == 401
