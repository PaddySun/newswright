"""作者更新端点契约测试（PUT /api/authors/{author_id}——UI2 W0b，服务
P6 作者配置表单：模型绑定与呈现位）。

覆盖口径：传值即改/缺省不动（沿 SourceUpdate 形态）；改名撞名 → 409
AUTHOR_NAME_EXISTS（作者名=唯一句柄，统筹裁定待站长追认）；自身同名
不视为撞名；空名拒绝；不存在 → 404 coded AUTHOR_NOT_FOUND；200 响应
= 单条全量（同详情形态）。设计依据见 docs/design-index.md「AC-10.1」。
"""
from app.models import Author


def _mk(db, name: str, **kw) -> Author:
    a = Author(name=name, model="m0", **kw)
    db.add(a)
    db.commit()
    return a


def test_update_changes_only_passed_fields(auth_client, db_session):
    """传值即改（model/enabled/bio/public_visible/rank_provider/include_hot_brief），
    未传字段（name）保持原值。"""
    a = _mk(db_session, "绑定作者", bio="旧简介", enabled=True,
            public_visible=False, rank_provider="none", include_hot_brief=False)
    r = auth_client.put(f"/api/authors/{a.id}", json={
        "model": "glm-new", "enabled": False, "bio": "新简介",
        "public_visible": True, "rank_provider": "moark_jev",
        "include_hot_brief": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "绑定作者"  # 未传 name 不动
    assert body["model"] == "glm-new"
    assert body["enabled"] is False
    assert body["bio"] == "新简介"
    assert body["public_visible"] is True
    assert body["rank_provider"] == "moark_jev"
    assert body["include_hot_brief"] is True
    db_session.expire_all()
    refreshed = db_session.get(Author, a.id)
    assert refreshed.model == "glm-new"
    assert refreshed.bio == "新简介"


def test_update_rename_keeps_other_fields_untouched(auth_client, db_session):
    """改名成功且其余字段全不动（缺省不动的完备面）。"""
    a = _mk(db_session, "改名作者", bio="保持", enabled=False,
            rank_provider="bocha_reranker")
    r = auth_client.put(f"/api/authors/{a.id}", json={"name": "新句柄"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "新句柄"
    assert body["bio"] == "保持"
    assert body["enabled"] is False
    assert body["model"] == "m0"
    assert body["rank_provider"] == "bocha_reranker"


def test_update_rename_conflict_is_coded_409(auth_client, db_session):
    """改名撞既有作者名 → 409 AUTHOR_NAME_EXISTS；原名不变。"""
    _mk(db_session, "占名作者")
    a = _mk(db_session, "撞名作者")
    r = auth_client.put(f"/api/authors/{a.id}", json={"name": "占名作者"})
    assert r.status_code == 409
    assert r.json() == {"code": "AUTHOR_NAME_EXISTS", "message": "作者名已存在"}
    db_session.expire_all()
    assert db_session.get(Author, a.id).name == "撞名作者"


def test_update_rename_to_own_name_is_allowed(auth_client, db_session):
    """改名=自身当前名不算撞名（幂等改名 200）。"""
    a = _mk(db_session, "自名作者")
    r = auth_client.put(f"/api/authors/{a.id}", json={"name": "自名作者"})
    assert r.status_code == 200
    assert r.json()["name"] == "自名作者"


def test_update_rejects_blank_name(auth_client, db_session):
    """空名（纯空白字符串）拒绝——作者名是唯一句柄，不可为空。"""
    a = _mk(db_session, "空名作者")
    r = auth_client.put(f"/api/authors/{a.id}", json={"name": "   "})
    assert r.status_code == 400
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_update_not_found_is_coded(auth_client, db_session):
    """不存在 → 404 coded AUTHOR_NOT_FOUND。"""
    r = auth_client.put("/api/authors/99999", json={"model": "m"})
    assert r.status_code == 404
    assert r.json() == {"code": "AUTHOR_NOT_FOUND", "message": "作者不存在"}
