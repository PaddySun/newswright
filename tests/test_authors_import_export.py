"""作者导入导出端点契约测试（POST /api/authors/import、GET /api/authors/
{author_id}/export——UI2 W0b，AC-10.1 的 HTTP 面）。

覆盖口径：导入新建（带 model 绑定）/同名更新 created=false；AuthorConfigError
→ 400 AUTHOR_JSON_INVALID（message 携带校验细节）；新作者未传 model → 400
AUTHOR_MODEL_REQUIRED；JSON 文档内含 model 键由 schema 校验拒绝；导出
roundtrip（export→import 幂等）；无配置导出 400 AUTHOR_JSON_ABSENT；
Content-Disposition 附件头。端点薄包 app/authors/importer.py 库函数。
设计依据见 docs/design-index.md「AC-10.1」。
"""
from app.authors.schema import default_author_config
from app.models import Author


def test_import_creates_author_with_model_binding(auth_client, db_session):
    """新建导入：identity.name 落库、model 经请求参数绑定、created=true。"""
    doc = default_author_config("imp-1", "导入新作者")
    r = auth_client.post("/api/authors/import",
                         json={"author_json": doc, "model": "glm-4.7"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"id", "name", "created"}
    assert body["name"] == "导入新作者"
    assert body["created"] is True
    a = db_session.get(Author, body["id"])
    assert a is not None
    assert a.model == "glm-4.7"


def test_import_same_name_updates_existing(auth_client, db_session):
    """同名再导入=更新既有作者（upsert 语义）：created=false、model 换绑。"""
    doc = default_author_config("imp-2", "复入作者")
    first = auth_client.post("/api/authors/import",
                             json={"author_json": doc, "model": "m-old"})
    r = auth_client.post("/api/authors/import",
                         json={"author_json": doc, "model": "m-new"})
    assert r.status_code == 200
    assert r.json()["created"] is False
    assert r.json()["id"] == first.json()["id"]
    db_session.expire_all()
    assert db_session.get(Author, first.json()["id"]).model == "m-new"


def test_import_invalid_document_is_coded_400(auth_client, db_session):
    """校验失败（缺 identity 层）→ 400 AUTHOR_JSON_INVALID，message 携带细节。"""
    r = auth_client.post("/api/authors/import",
                         json={"author_json": {"id": "broken", "version": "v"},
                               "model": "m"})
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "AUTHOR_JSON_INVALID"
    assert "identity" in body["message"]


def test_import_new_author_without_model_is_coded_400(auth_client, db_session):
    """新作者未传 model → 400 AUTHOR_MODEL_REQUIRED（模型不在 JSON 中）。"""
    doc = default_author_config("imp-3", "无模型作者")
    r = auth_client.post("/api/authors/import", json={"author_json": doc})
    assert r.status_code == 400
    assert r.json()["code"] == "AUTHOR_MODEL_REQUIRED"


def test_import_document_with_model_key_is_rejected(auth_client, db_session):
    """JSON 文档内含 model 键 → schema 校验拒绝（模型绑定只走请求参数，
    禁止文档携带）。"""
    doc = default_author_config("imp-4", "带模作者")
    doc["model"] = "smuggled-model"
    r = auth_client.post("/api/authors/import",
                         json={"author_json": doc, "model": "glm-4.7"})
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "AUTHOR_JSON_INVALID"
    assert "model" in body["message"]


def test_import_runtime_bindings_pass_through(auth_client, db_session):
    """readable_directions/rank_provider 运行时绑定参数透传 importer。"""
    doc = default_author_config("imp-5", "绑定透传作者")
    r = auth_client.post("/api/authors/import", json={
        "author_json": doc, "model": "m",
        "readable_directions": [{"direction_id": 7, "threshold": 25}],
        "rank_provider": "bocha_jev",
    })
    assert r.status_code == 200
    a = db_session.get(Author, r.json()["id"])
    assert a.readable_directions == [{"direction_id": 7, "threshold": 25}]
    assert a.rank_provider == "bocha_jev"


def test_export_roundtrip_is_idempotent(auth_client, db_session):
    """roundtrip：导入→导出→再导入（不传 model，同名=更新）幂等，bio/
    public_visible 随文档往返。"""
    doc = default_author_config("exp-1", "往返作者")
    doc["bio"] = "往返简介"
    doc["public_visible"] = True
    created = auth_client.post("/api/authors/import",
                               json={"author_json": doc, "model": "m"})
    author_id = created.json()["id"]

    exported = auth_client.get(f"/api/authors/{author_id}/export")
    assert exported.status_code == 200
    assert exported.headers["content-disposition"] == \
        f'attachment; filename="author-{author_id}.json"'
    exported_doc = exported.json()
    assert exported_doc["bio"] == "往返简介"
    assert exported_doc["public_visible"] is True

    again = auth_client.post("/api/authors/import",
                             json={"author_json": exported_doc})
    assert again.status_code == 200
    assert again.json() == {"id": author_id, "name": "往返作者",
                            "created": False}


def test_export_without_author_json_is_coded_400(auth_client, db_session):
    """无 author_json 配置的作者导出 → 400 AUTHOR_JSON_ABSENT。"""
    a = Author(name="素导出作者", model="m")
    db_session.add(a)
    db_session.commit()
    r = auth_client.get(f"/api/authors/{a.id}/export")
    assert r.status_code == 400
    assert r.json() == {"code": "AUTHOR_JSON_ABSENT",
                        "message": "该作者没有 author.json 配置"}


def test_export_not_found_is_coded(auth_client, db_session):
    """不存在 → 404 coded AUTHOR_NOT_FOUND。"""
    r = auth_client.get("/api/authors/99999/export")
    assert r.status_code == 404
    assert r.json()["code"] == "AUTHOR_NOT_FOUND"
