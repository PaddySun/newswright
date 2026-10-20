"""BE-7/D1 写作链随链改造（高危洞①防线）：Author.model 语义改「空=随候选链」。

背景：候选链默认 moark 后，存量 author.model=deepseek 官方名发给 moark 网关
会 400（请求级致命——不冷却不切换→写作链永久失败循环），故存量清空、随链走
_default_model()。

覆盖（任务书 §五必含用例）：
- 导入端点 model 可选（W0b 契约放宽呈报）：不传=随链（DB NULL），传了照旧绑定；
- 写作面 writer.py 零逻辑改：author.model 为 NULL → chat_json 收到 model=None
  （打桩断言随链形态）；
- PUT model 语义：缺省=不改，空串=清空回随链（与 SourceUpdate「传值即改、
  缺省不动」形态对齐）；
- 存量迁移（app/db.py）：author.model 列实测 NOT NULL（生产库与新库 DDL 均
  如此——任务书 A6 未记事实，呈报项）→ 表重建可空化+存量清空；幂等=二次
  运行零行命中，且迁移后显式绑定不被再清。
"""
import pytest
from sqlalchemy import text

from app.authors.schema import default_author_config
from app.models import Author, Item, ScoreResult


# ---------- 导入端点：model 可选（缺省随链） ----------


def test_import_without_model_creates_chain_following_author(auth_client, db_session):
    """新作者不传 model → 建为随链（DB NULL）——不再 400 AUTHOR_MODEL_REQUIRED
    （W0b 契约放宽：不传=随链，传了照旧绑定）。"""
    doc = default_author_config("chain-1", "随链作者")
    r = auth_client.post("/api/authors/import", json={"author_json": doc})
    assert r.status_code == 200, r.text
    db_session.expire_all()
    a = db_session.get(Author, r.json()["id"])
    assert a.model is None  # 空=随候选链


def test_import_with_model_still_binds(auth_client, db_session):
    """显式传 model → 照旧绑定（绑定语义不因可选化回退）。"""
    doc = default_author_config("chain-2", "绑模作者")
    r = auth_client.post("/api/authors/import",
                         json={"author_json": doc, "model": "deepseek-flash"})
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.get(Author, r.json()["id"]).model == "deepseek-flash"


# ---------- 写作面：随链形态（chat_json model=None 打桩断言） ----------


@pytest.fixture()
def author_items_unbound(db_session):
    """随链作者（model=NULL）+两条已打分条目（写作最小夹具）。"""
    a = Author(name="随链写作作者", model=None,
               readable_directions=[{"direction_id": 1, "threshold": 60}])
    i1 = Item(source_id=1, guid="cg1", title="t1", content_text="DeepSeek 发布了新模型。")
    i2 = Item(source_id=1, guid="cg2", title="t2", content_text="第二篇文章内容。")
    db_session.add_all([a, i1, i2])
    db_session.commit()
    db_session.add_all([
        ScoreResult(item_id=i1.id, direction_id=1, quality_score=80,
                    relevance_score=80, band="high", reason="r",
                    prompt_version=1, model="m", passed=True, status="OK"),
        ScoreResult(item_id=i2.id, direction_id=1, quality_score=70,
                    relevance_score=70, band="high", reason="r",
                    prompt_version=1, model="m", passed=True, status="OK"),
    ])
    db_session.commit()
    return a, i1, i2


def test_writer_chat_json_receives_none_when_author_unbound(
        db_session, author_items_unbound, monkeypatch):
    """author.model=NULL → writer 零逻辑改下 model or author.model=None →
    chat_json(model=None)（随链——走 _default_model 随候选链）；
    WriteRun.model 建行时同样 NULL（成功后以服务端回显实况回填）。"""
    from app.authors import writer as wr

    a, i1, _ = author_items_unbound
    good_payload = {"decision": "write", "article": {
        "title": "随链文章", "body": "正文内容。",
        "citations": [{"item_id": i1.id, "quote": "DeepSeek 发布了新模型。"}]},
        "reason": "r", "thinking": "t"}
    seen_models: list = []

    class FakeChain:
        def __init__(self, _db):
            pass

        def chat_json(self, messages, **kw):
            seen_models.append(kw.get("model"))
            return good_payload, "deepseek-v4.1-flash"

    monkeypatch.setattr(wr, "resolve_chat", lambda _db: FakeChain(_db))
    run = wr.run_write(db_session, a, triggered_by="test")
    assert run.status == "OK" and run.decision == "WRITE"
    assert seen_models and all(m is None for m in seen_models)
    assert run.model == "deepseek-v4.1-flash"  # 成功后回显实况回填


# ---------- PUT model 语义：缺省不改 / 空串清空回随链 ----------


def test_put_model_empty_string_clears_to_chain(auth_client, db_session):
    """空串=清空回随链（存 NULL）；再传具体名=重新绑定；缺省=不动。"""
    a = Author(name="清空作者", model="old-model")
    db_session.add(a)
    db_session.commit()

    r = auth_client.put(f"/api/authors/{a.id}", json={"model": ""})
    assert r.status_code == 200, r.text
    assert r.json()["model"] is None
    db_session.expire_all()
    assert db_session.get(Author, a.id).model is None

    r = auth_client.put(f"/api/authors/{a.id}", json={"model": "glm-4.7"})
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.get(Author, a.id).model == "glm-4.7"

    r = auth_client.put(f"/api/authors/{a.id}", json={"bio": "只改简介"})
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.get(Author, a.id).model == "glm-4.7"  # 缺省不动


# ---------- 存量迁移：NOT NULL 列重建可空化+清空（幂等） ----------

_LEGACY_DDL = """
CREATE TABLE author (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    model VARCHAR(100) NOT NULL,
    persona_prompt TEXT NOT NULL,
    global_system_prompt TEXT NOT NULL,
    readable_directions JSON NOT NULL,
    memory_config JSON NOT NULL,
    rank_provider VARCHAR(30) NOT NULL DEFAULT 'none',
    rank_exclude_below INTEGER NOT NULL DEFAULT 30,
    include_hot_brief BOOLEAN NOT NULL DEFAULT 0,
    author_json JSON,
    bio TEXT NOT NULL DEFAULT '',
    public_visible BOOLEAN NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL,
    UNIQUE (name)
)
"""


def _model_column_nullable() -> bool:
    from app import db as appdb

    with appdb.engine.connect() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(author)").fetchall()
    col = next(r for r in rows if r[1] == "model")
    return not col[3]


def test_migration_rebuilds_legacy_notnull_and_clears(db_session):
    """存量库（model NOT NULL）→ 表重建可空化+存量清空随链：行保序保留、
    UNIQUE(name) 保留、model 全 NULL；幂等=二次运行零行命中。"""
    from app import db as appdb

    with appdb.engine.begin() as conn:
        conn.execute(text("DROP TABLE author"))
        conn.execute(text(_LEGACY_DDL))
        conn.execute(text(
            "INSERT INTO author (name, model, persona_prompt, global_system_prompt,"
            " readable_directions, memory_config, enabled, author_json)"
            " VALUES ('存量作者', 'deepseek-flash', '', '', '[]', '{}', 1,"
            " '{\"id\": \"legacy\"}')"))

    appdb._migrate_author_model_nullable()

    assert _model_column_nullable()
    with appdb.engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, name, model, author_json FROM author")).fetchall()
    assert len(rows) == 1
    aid, name, model, author_json = rows[0]
    # raw SQL 读 JSON 列为文本（不经 ORM 类型转换），自解析
    import json as _json
    assert name == "存量作者" and model is None
    assert _json.loads(author_json)["id"] == "legacy"

    # 二次运行：幂等（结构已可空即跳过，零行命中零改动）
    appdb._migrate_author_model_nullable()
    with appdb.engine.connect() as conn:
        still = conn.execute(text("SELECT model FROM author")).scalar()
    assert still is None


def test_migration_preserves_explicit_rebinding_after_first_run(db_session):
    """迁移是一次性语义：首次重建清空后，显式重新绑定的 model 不被后续
    init_db 再清（「传了照旧绑定」跨重启存活）。"""
    from app import db as appdb

    appdb._migrate_author_model_nullable()  # 测试库已是可空新形态=首次跳过
    a = Author(name="再绑作者", model="deepseek-v4-pro")
    db_session.add(a)
    db_session.commit()
    appdb._migrate_author_model_nullable()  # 再跑（等价重启后再跑）
    db_session.expire_all()
    assert db_session.get(Author, a.id).model == "deepseek-v4-pro"


def test_migration_keeps_unique_name_constraint(db_session):
    """表重建保留 UNIQUE(name)（作者名=唯一句柄，W0b 契约不因迁移回退）。"""
    from app import db as appdb
    from sqlalchemy.exc import IntegrityError

    with appdb.engine.begin() as conn:
        conn.execute(text("DROP TABLE author"))
        conn.execute(text(_LEGACY_DDL))
        conn.execute(text(
            "INSERT INTO author (name, model, persona_prompt, global_system_prompt,"
            " readable_directions, memory_config, enabled)"
            " VALUES ('唯一作者', 'm', '', '', '[]', '{}', 1)"))
    appdb._migrate_author_model_nullable()

    with pytest.raises(IntegrityError):
        with appdb.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO author (name, model, persona_prompt, global_system_prompt,"
                " readable_directions, memory_config, enabled)"
                " VALUES ('唯一作者', NULL, '', '', '[]', '{}', 1)"))
