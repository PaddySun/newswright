"""db 轻量迁移测试：方向生命周期列与来源失效列的旧库升级（G2/W1）。

夹具模式沿用旧库升级测试先例（tests/test_mutation_db_migration_contract.py 的
历史形状裸建 + init_db 由测试自调）：direction 为「生命周期列上线前」形态，
source 为「失效判别列上线前」形态，含历史行。断言全部来自设计书条款：
- 技术书 §4.1 表结构（direction 增 temp/expires_at/deleted_at/status；source 增
  failure_level/failure_since/last_error）；
- 产品书 US-03（软删除/TTL 语义要求 status 为唯一真值——历史行按旧 enabled 布尔
  换算，停用方向不得复活为 active）；
- 产品书 §0 决策表（prompt_version 统一 integer——'v1' 形态存量行一次性归一）。
设计依据见 docs/design-index.md「AC-03.3」「AC-03.4」「D19」「DT-1」。
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

import app.config as cfg
import app.db as appdb
from app.models import Direction, ScoreResult

# ---------- 旧库夹具：新列上线前的历史形状 ----------

_OLD_DIRECTION = """
CREATE TABLE direction (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(200) UNIQUE,
    prompt TEXT,
    prompt_version VARCHAR(20) DEFAULT 'v1',
    threshold INTEGER DEFAULT 60,
    enabled BOOLEAN DEFAULT 1
)"""
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
_OLD_SCORE_RESULT = """
CREATE TABLE score_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER REFERENCES item(id),
    direction_id INTEGER REFERENCES direction(id),
    quality_score INTEGER,
    relevance_score INTEGER,
    band VARCHAR(10),
    reason TEXT DEFAULT '',
    prompt_version VARCHAR(20) DEFAULT 'v1',
    model VARCHAR(100),
    passed BOOLEAN DEFAULT 0,
    status VARCHAR(20) DEFAULT 'OK',
    error TEXT,
    created_at VARCHAR(40)
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


@pytest.fixture()
def g2_old_db(tmp_path):
    """旧库夹具：direction/source/score_result 均为新列上线前形状，含历史行
    （启用方向 + 停用方向 + 'v1'/'v3' 形态版本号存量行）。"""
    _bind_engine(tmp_path, "g2_old.db")
    with appdb.engine.begin() as conn:
        conn.execute(text(_OLD_DIRECTION))
        conn.execute(text(_OLD_SOURCE))
        conn.execute(text(_OLD_SCORE_RESULT))
        conn.execute(text(
            "INSERT INTO direction (name, prompt, prompt_version, threshold, enabled) "
            "VALUES ('启用方向', 'p', 'v1', 60, 1)"))
        conn.execute(text(
            "INSERT INTO direction (name, prompt, prompt_version, threshold, enabled) "
            "VALUES ('停用方向', 'p', 'v1', 60, 0)"))
        conn.execute(text(
            "INSERT INTO score_result (item_id, direction_id, reason, prompt_version, "
            "model, status) VALUES (1, 1, '旧分', 'v3', 'm', 'OK')"))
    yield
    _restore_engine()


# G2 搜索归因上线前的 item 形状（sanitize/指纹链列已在，source_keyword 缺）
_OLD_ITEM = """
CREATE TABLE item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES source(id),
    guid VARCHAR(1000) NOT NULL,
    url VARCHAR(2000),
    title VARCHAR(2000),
    content_text TEXT,
    summary TEXT,
    published_at VARCHAR(40),
    fetched_at VARCHAR(40),
    fetch_status VARCHAR(20) DEFAULT 'FETCHED',
    rule_reject_reason VARCHAR(500),
    sanitize_status VARCHAR(20) DEFAULT 'PENDING',
    sanitize_reason VARCHAR(500),
    sanitize_detail JSON,
    raw JSON,
    direction_id INTEGER,
    fingerprint VARCHAR(64),
    duplicate_of INTEGER
)"""


@pytest.fixture()
def g2_older_item_db(tmp_path):
    """更全旧库夹具：四表齐备（item 为搜索归因列上线前形状），source 含历史行
    （failure_level 枚举精确性与 source_keyword 补列断言面）、direction/score_result
    含 'v2'/'v1' 形态版本号存量行（D19 库内归一 raw 读断言面）。"""
    _bind_engine(tmp_path, "g2_older_item.db")
    with appdb.engine.begin() as conn:
        conn.execute(text(_OLD_DIRECTION))
        conn.execute(text(_OLD_SOURCE))
        conn.execute(text(_OLD_SCORE_RESULT))
        conn.execute(text(_OLD_ITEM))
        conn.execute(text(
            "INSERT INTO direction (name, prompt, prompt_version, threshold, enabled) "
            "VALUES ('归一方向', 'p', 'v2', 60, 1)"))
        conn.execute(text(
            "INSERT INTO source (direction_id, url, type, enabled) "
            "VALUES (1, 'https://old.example/feed', 'rss', 1)"))
        conn.execute(text(
            "INSERT INTO score_result (item_id, direction_id, reason, prompt_version, "
            "model, status) VALUES (1, 1, '旧分', 'v1', 'm', 'OK')"))
    yield
    _restore_engine()


def _columns_of(table: str) -> set[str]:
    return {c["name"] for c in inspect(appdb.engine).get_columns(table)}


# ---------- direction 生命周期列（§4.1 + US-03） ----------


def test_migrate_old_db_adds_direction_lifecycle_columns(g2_old_db):
    """旧库补方向生命周期四列与来源失效判别/降频计数列、条目关键词归因列；
    历史行状态按旧 enabled 换算——停用方向保持 disabled，失效与降频状态视为正常。"""
    from app.db import init_db

    init_db()
    assert {"status", "temp", "expires_at", "deleted_at"} <= _columns_of("direction")
    assert {"failure_level", "failure_since", "last_error", "hard_failures",
            "empty_rounds", "rate_limited_until", "rate_level", "rate_ok_rounds",
            "keyword_limited_until", "keyword_rate_level",
            "keyword_zero_rounds"} <= _columns_of("source")
    assert {"source_keyword"} <= _columns_of("item")
    with appdb.SessionLocal() as db:
        active = db.query(Direction).filter_by(name="启用方向").one()
        disabled = db.query(Direction).filter_by(name="停用方向").one()
    assert active.status == "active"
    assert disabled.status == "disabled"  # 停用方向不得复活为 active


def test_migrate_old_db_prompt_version_rows_normalized(g2_old_db):
    """prompt_version 统一 integer：'v1' 形态存量行归一为 1（direction 与
    score_result 两侧），ORM 读回一律 int。"""
    from app.db import init_db

    init_db()
    with appdb.SessionLocal() as db:
        d = db.query(Direction).filter_by(name="启用方向").one()
        assert d.prompt_version == 1 and isinstance(d.prompt_version, int)
        row = db.query(ScoreResult).filter_by(item_id=1).one()
        assert row.prompt_version == 3 and isinstance(row.prompt_version, int)


# ---------- G2 搜索归因列 / 失效判别枚举 / D19 库内归一（C2-4 分诊补强） ----------


def test_migrate_old_source_failure_level_exact_enum(g2_older_item_db):
    """旧库补列后历史行 failure_level 为精确小写枚举 'none'（三级判别按精确
    枚举取值，DT-1 历史行视为正常态）。设计依据见 docs/design-index.md「DT-1」。"""
    from app.db import init_db
    from app.models import Source

    init_db()
    with appdb.SessionLocal() as db:
        s = db.query(Source).filter_by(url="https://old.example/feed").one()
        assert s.failure_level == "none"


def test_migrate_old_item_adds_source_keyword_column(g2_older_item_db):
    """旧库 item 补 source_keyword 列（§4.1 搜索通道逐词归因数据面），且 ORM
    写入路径可用（列名精确）。设计依据见 docs/design-index.md「AC-04.x 搜索通道」。"""
    from app.db import init_db
    from app.models import Item

    init_db()
    assert "source_keyword" in _columns_of("item")
    with appdb.SessionLocal() as db:
        src_id = db.execute(text("SELECT id FROM source")).scalar_one()
        db.add(Item(source_id=src_id, guid="g-new", title="t", source_keyword="关键词"))
        db.commit()
        row = db.query(Item).filter_by(guid="g-new").one()
        assert row.source_keyword == "关键词"


def test_migrate_old_prompt_version_normalized_in_storage(g2_older_item_db):
    """D19 统一 integer 的库内形态：'v2'/'v1' 存量行经一次性归一后库内不再
    保留 'v' 前缀（文本亲和列连整数也回读为文本，故断言面=无前缀形态而非 int
    存储；raw SQL 读——ORM 读回被 PromptVersion 类型双向归一兜底，遮蔽库内形态）。
    设计依据见 docs/design-index.md「D19」。"""
    from app.db import init_db

    init_db()
    with appdb.engine.connect() as conn:
        d_pv = conn.execute(
            text("SELECT prompt_version FROM direction")).scalar_one()
        s_pv = conn.execute(
            text("SELECT prompt_version FROM score_result")).scalar_one()
    assert str(d_pv) == "2"
    assert str(s_pv) == "1"
