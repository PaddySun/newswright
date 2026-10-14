"""作者单条全量端点契约测试（GET /api/authors/{author_id}——UI2 W0b，
服务 P6 作者配置表单初始值）。

覆盖口径：200 全量字段（readable_directions 富化 direction_name、
memory_counts 按 module 分组计数、运行时绑定与呈现位列）；不存在 → 404
coded AUTHOR_NOT_FOUND。设计依据见 docs/design-index.md「AC-10.1」。
"""
from app.models import Author, Direction, MemoryEntry


def _seed_author(db) -> tuple[Author, Direction]:
    d = Direction(name="详情方向", prompt="p", prompt_version=1)
    db.add(d)
    db.commit()
    a = Author(name="详情作者", model="m-detail", enabled=False,
               public_visible=True, bio="详情简介",
               rank_provider="bocha_reranker", rank_exclude_below=45,
               include_hot_brief=True,
               readable_directions=[{"direction_id": d.id, "threshold": 35}],
               memory_config={"feedback_memory": 5, "topic_memory": 3},
               author_json={"id": "detail", "version": "v1"})
    db.add(a)
    db.commit()
    db.add_all([
        MemoryEntry(author_id=a.id, module="feedback", content="f1",
                    source_event="feedback"),
        MemoryEntry(author_id=a.id, module="feedback", content="f2",
                    source_event="write"),
        MemoryEntry(author_id=a.id, module="topic", content="t1",
                    source_event="write"),
    ])
    db.commit()
    return a, d


def test_author_detail_returns_full_contract_fields(auth_client, db_session):
    """全量字段：身份 + 运行时绑定（rank 两列/热点段开关）+ 富化方向 + 记忆两态。"""
    a, d = _seed_author(db_session)
    r = auth_client.get(f"/api/authors/{a.id}")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "id", "name", "model", "enabled", "public_visible", "bio",
        "rank_provider", "rank_exclude_below", "include_hot_brief",
        "readable_directions", "memory_config", "memory_counts",
        "has_author_json",
    }
    assert body["name"] == "详情作者"
    assert body["model"] == "m-detail"
    assert body["enabled"] is False
    assert body["public_visible"] is True
    assert body["bio"] == "详情简介"
    assert body["rank_provider"] == "bocha_reranker"
    assert body["rank_exclude_below"] == 45
    assert body["include_hot_brief"] is True
    assert body["readable_directions"] == [
        {"direction_id": d.id, "direction_name": "详情方向", "threshold": 35},
    ]
    assert body["memory_config"] == {"feedback_memory": 5, "topic_memory": 3}
    assert body["memory_counts"] == {"feedback": 2, "topic": 1}
    assert body["has_author_json"] is True


def test_author_detail_enriches_direction_name_per_entry(auth_client, db_session):
    """readable_directions 富化：每条带 direction_name；行不存在的失效 id
    name=null（配置原样呈现不丢条目）。"""
    live = Direction(name="富化方向", prompt="p", prompt_version=1)
    db_session.add(live)
    db_session.commit()
    a = Author(name="富化作者", model="m",
               readable_directions=[
                   {"direction_id": live.id, "threshold": 20},
                   {"direction_id": 424242, "threshold": 55},
               ])
    db_session.add(a)
    db_session.commit()

    body = auth_client.get(f"/api/authors/{a.id}").json()
    assert body["readable_directions"] == [
        {"direction_id": live.id, "direction_name": "富化方向", "threshold": 20},
        {"direction_id": 424242, "direction_name": None, "threshold": 55},
    ]


def test_author_detail_not_found_is_coded(auth_client, db_session):
    """不存在 → 404 coded AUTHOR_NOT_FOUND（不翻新既有 string 404 的另册端点）。"""
    r = auth_client.get("/api/authors/99999")
    assert r.status_code == 404
    assert r.json() == {"code": "AUTHOR_NOT_FOUND", "message": "作者不存在"}


def test_author_detail_memory_counts_empty_without_entries(auth_client, db_session):
    """无记忆条目 memory_counts={}；无 JSON 配置 has_author_json=false。"""
    a = Author(name="素详情作者", model="m")
    db_session.add(a)
    db_session.commit()
    body = auth_client.get(f"/api/authors/{a.id}").json()
    assert body["memory_counts"] == {}
    assert body["memory_config"] == {}
    assert body["has_author_json"] is False
