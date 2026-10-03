"""C1-2 变异分诊批次 3 补强测试（app.db 60 + app.main 4 = 64 条 C 类）。

缺口根源：现有测试只走「新库 create_all」路径，db._migrate_added_columns 的
旧库升级路径此前无测试（与 C1-1 providers.base 同构）；main.create_app 启动装配
仅被 import 期顺带执行、无独立断言。断言全部来自设计书 v1.5 条款：
- 技术书 §4.1 表结构（source/author/item/write_run/usage_log 新增列；item 的
  fingerprint 索引 = (direction_id, fingerprint)——作用域=方向内 D15）；
- 技术书模块表 db.py「engine/session + 轻量迁移（ALTER 补列）」职责 + ADR-1
  （SQLite WAL，schema 由 create_all + 轻量迁移承载，迁移目标=与 models 定义对齐）；
- 产品书 AC-06.1（sanitize demo 语义：PASSED + "demo:零信任过滤未启用" 原因标记，
  历史行视为已通过骨架过滤——db 模块 docstring 回填语义）；
- 产品书 AC-01.1（启动时 users 空表创建 admin）+ 技术书 §4.2 OpenAPI 契约
  （create_app 注册 auth + 业务全部路由为其实现前提）。

命名 test_<断言点>；风格与 tests/test_mutation_c1_1.py 一致。引擎绑定/还原手法
与 conftest.db_session、test_models_smoke.tables 相同（cfg.DATABASE_URL +
appdb.engine 重绑，teardown 还原）。
"""
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy import create_engine, inspect, text

import app.config as cfg
import app.db as appdb
from app.models import Direction, User

# ---------- 旧库夹具：历史版本 schema（缺迁移列） ----------

_OLD_SOURCE = """
CREATE TABLE source (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction_id INTEGER REFERENCES direction(id),
    url VARCHAR(500) NOT NULL,
    type VARCHAR(20) DEFAULT 'rss',
    enabled BOOLEAN DEFAULT 1,
    last_fetched_at VARCHAR(40),
    etag VARCHAR(200),
    last_modified VARCHAR(40)
)"""
_OLD_AUTHOR = """
CREATE TABLE author (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200) UNIQUE,
    model VARCHAR(100),
    persona_prompt TEXT DEFAULT '',
    global_system_prompt TEXT DEFAULT '',
    readable_directions JSON,
    memory_config JSON,
    enabled BOOLEAN DEFAULT 1
)"""
_OLD_WRITE_RUN = """
CREATE TABLE write_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id INTEGER REFERENCES author(id),
    triggered_by VARCHAR(40),
    reading_set_item_ids JSON,
    decision VARCHAR(40),
    article_id INTEGER,
    skip_reason VARCHAR(100),
    skip_thinking TEXT,
    model VARCHAR(100),
    status VARCHAR(20),
    error TEXT,
    created_at VARCHAR(40)
)"""
_OLD_USAGE_LOG = """
CREATE TABLE usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider VARCHAR(50),
    model VARCHAR(100),
    call_point VARCHAR(60),
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    billing_units INTEGER,
    latency_ms INTEGER,
    ok BOOLEAN,
    error TEXT,
    ref_type VARCHAR(40),
    ref_id INTEGER,
    created_at VARCHAR(40)
)"""
# 旧 item：sanitize 上线前形态（无 sanitize_*/raw/direction_id/fingerprint/duplicate_of）
_OLD_ITEM = """
CREATE TABLE item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES source(id),
    guid VARCHAR(200) NOT NULL,
    url VARCHAR(500),
    title VARCHAR(300),
    published_at VARCHAR(40),
    content_text TEXT DEFAULT '',
    fetch_status VARCHAR(20) DEFAULT 'fetched',
    rule_reject_reason VARCHAR(100),
    fetched_at VARCHAR(40),
    created_at VARCHAR(40),
    UNIQUE (source_id, guid)
)"""
# 部分升级态 item：sanitize 三列已补，缺 raw/direction_id/fingerprint/duplicate_of
_PARTIAL_ITEM = """
CREATE TABLE item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES source(id),
    guid VARCHAR(200) NOT NULL,
    url VARCHAR(500),
    title VARCHAR(300),
    published_at VARCHAR(40),
    content_text TEXT DEFAULT '',
    fetch_status VARCHAR(20) DEFAULT 'fetched',
    rule_reject_reason VARCHAR(100),
    fetched_at VARCHAR(40),
    created_at VARCHAR(40),
    sanitize_status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    sanitize_reason VARCHAR(500),
    sanitize_detail JSON,
    UNIQUE (source_id, guid)
)"""


def _bind_engine(tmp_dir: Path, db_name: str) -> None:
    url = f"sqlite:///{(tmp_dir / db_name).as_posix()}"
    cfg.DATABASE_URL = url
    appdb.engine.dispose()
    appdb.engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
    appdb.SessionLocal.configure(bind=appdb.engine)


def _restore_engine() -> None:
    appdb.engine.dispose()
    cfg.DATABASE_URL = f"sqlite:///{(cfg.PROJECT_ROOT / 'newswright.db').as_posix()}"


def _seed_history(conn) -> None:
    """历史行：迁移上线前入库的 source/item/author（item 无 sanitize 痕迹）。"""
    conn.execute(text(
        "INSERT INTO source (direction_id, url, type, enabled) VALUES (1, 'https://ex/f', 'rss', 1)"))
    conn.execute(text(
        "INSERT INTO item (source_id, guid, title, content_text) VALUES (1, 'g1', '旧条目', '正文')"))
    conn.execute(text(
        "INSERT INTO author (name, model, persona_prompt) VALUES ('旧作者', 'deepseek-chat', 'p')"))


@pytest.fixture()
def old_db(tmp_path):
    """F1 旧库升级夹具：direction 用现模型建（无迁移列），其余五表为历史形状裸建，
    含历史行。init_db 由测试自己调用（崩溃型变异应在 init_db 调用处落红）。"""
    _bind_engine(tmp_path, "old.db")
    models_Base = Direction.metadata
    models_Base.create_all(appdb.engine, tables=[Direction.__table__])
    with appdb.engine.begin() as conn:
        conn.execute(text("INSERT INTO direction (name, prompt, prompt_version, threshold, enabled) VALUES ('D', 'p', 'v1', 60, 1)"))
        for ddl in (_OLD_SOURCE, _OLD_AUTHOR, _OLD_WRITE_RUN, _OLD_USAGE_LOG, _OLD_ITEM):
            conn.execute(text(ddl))
        _seed_history(conn)
    yield
    _restore_engine()


@pytest.fixture()
def partial_old_db(tmp_path):
    """F2 部分升级态夹具：item 的 sanitize 三列已在、缺后四列，且存在一条合法的
    PENDING 行（过滤已上线、打分链未处理——非历史行）。"""
    _bind_engine(tmp_path, "partial.db")
    Direction.metadata.create_all(appdb.engine, tables=[Direction.__table__])
    with appdb.engine.begin() as conn:
        conn.execute(text("INSERT INTO direction (name, prompt, prompt_version, threshold, enabled) VALUES ('D', 'p', 'v1', 60, 1)"))
        for ddl in (_OLD_SOURCE, _OLD_AUTHOR, _OLD_WRITE_RUN, _OLD_USAGE_LOG, _PARTIAL_ITEM):
            conn.execute(text(ddl))
        conn.execute(text(
            "INSERT INTO source (direction_id, url, type, enabled) VALUES (1, 'https://ex/f', 'rss', 1)"))
        conn.execute(text(
            "INSERT INTO item (source_id, guid, title, sanitize_status) VALUES (1, 'g1', '新条目', 'PENDING')"))
    yield
    _restore_engine()


def _columns_of(table: str) -> set[str]:
    return {c["name"] for c in inspect(appdb.engine).get_columns(table)}


# ---------- db._migrate_added_columns：旧库补列（§4.1 + 模块表 db.py 职责） ----------


def test_migrate_old_db_adds_all_missing_columns(old_db):
    """技术书 §4.1 表结构 + 模块表「轻量迁移（ALTER 补列）」：对旧库缺列逐一补齐，
    五表全部对齐当前 models 定义（ADR-1：schema 由 create_all + 轻量迁移承载）。"""
    from app.db import init_db

    init_db()  # Given：缺列旧库；崩溃型变异（非法 DDL/execute(None)）在此落红

    assert {"backoff_failures", "backoff_skips", "source_config", "content_hash"} <= _columns_of("source")
    assert {"rank_provider", "rank_exclude_below", "include_hot_brief", "author_json"} <= _columns_of("author")
    assert {"payload"} <= _columns_of("write_run")
    assert {"cache_hit_tokens", "reasoning_tokens", "finish_reason", "item_count"} <= _columns_of("usage_log")
    assert {"sanitize_status", "sanitize_reason", "sanitize_detail", "raw",
            "direction_id", "fingerprint", "duplicate_of"} <= _columns_of("item")


def test_migrate_old_db_backfills_sanitize_history(old_db):
    """AC-06.1 + db 模块回填语义：sanitize 上线前的历史行视为已通过骨架过滤——
    状态 PASSED，原因保留 demo 标记（统计按 reason 分组，AC-06.1 标记前缀不得漂移）。"""
    from app.db import init_db

    init_db()
    with appdb.engine.connect() as conn:
        row = conn.execute(text(
            "SELECT sanitize_status, sanitize_reason FROM item WHERE guid='g1'")).one()
    assert row[0] == "PASSED"
    assert row[1].startswith("demo:零信任过滤未启用")


def test_migrate_old_db_column_defaults_match_model_schema(old_db):
    """§4.1 author/source 行 + models 列默认（迁移=与 models 定义对齐）：历史行回填
    缺省值必须与 ORM 默认一致——author.rank_provider 哨兵 'none'（小写）触发
    writer 的「rank_provider=none 回退 relevance」判定，值漂移即行为漂移。"""
    from app.db import init_db

    init_db()
    with appdb.engine.connect() as conn:
        src = conn.execute(text("SELECT backoff_failures, backoff_skips FROM source")).one()
        author = conn.execute(text(
            "SELECT rank_provider, rank_exclude_below, include_hot_brief FROM author")).one()
    assert src == (0, 0)
    assert author == ("none", 30, 0)


def test_migrate_old_db_creates_direction_fingerprint_index(old_db):
    """§4.1 item 行（索引 = (direction_id, fingerprint)，作用域=方向内 D15）+ G1/W4：
    新库由 create_all 的 __table_args__ 建立，旧库由迁移补建同名同列索引。"""
    from app.db import init_db

    init_db()
    idx = [i for i in inspect(appdb.engine).get_indexes("item")
           if i["name"] == "ix_item_direction_fingerprint"]
    assert len(idx) == 1
    assert idx[0]["column_names"] == ["direction_id", "fingerprint"]


def test_migrate_partial_upgrade_backfills_only_historical_rows(partial_old_db):
    """模块表 db.py 职责 + db 模块回填语义（「历史行回填，仅补列当次执行」）：补列
    逐一补齐（已有列跳过不中断后续列）；且只回填历史行——sanitize 列非本次补入时，
    合法 PENDING 行（过滤已上线、打分链未处理）不得被改写（AC-06.2 状态归过滤链管）。"""
    from app.db import init_db

    init_db()
    assert {"raw", "direction_id", "fingerprint", "duplicate_of"} <= _columns_of("item")
    with appdb.engine.connect() as conn:
        row = conn.execute(text(
            "SELECT sanitize_status FROM item WHERE guid='g1'")).one()
    assert row[0] == "PENDING"  # 非历史行不被回填


# ---------- main.create_app：启动装配（AC-01.1 + §4.2 OpenAPI 契约前提） ----------


def test_create_app_boots_bootstrap_and_registers_routers(db_session):
    """AC-01.1（启动时 users 空表创建 admin）+ §4.2 OpenAPI 契约（auth 与业务
    路由全部注册）：create_app 返回可用 ASGI 应用并完成启动初始化。"""
    from fastapi import FastAPI

    from app.main import create_app

    app = create_app()
    assert isinstance(app, FastAPI)
    paths = set(app.openapi()["paths"])
    assert "/api/auth/login" in paths  # 守卫豁免路由（AC-01.1b 登录入口）
    assert "/items" in paths  # 业务路由（守卫依赖）
    assert "/" in {getattr(r, "path", "") for r in app.routes}
    assert db_session.query(User).count() == 1  # admin 已引导且唯一
