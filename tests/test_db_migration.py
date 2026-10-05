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


def _columns_of(table: str) -> set[str]:
    return {c["name"] for c in inspect(appdb.engine).get_columns(table)}


# ---------- direction 生命周期列（§4.1 + US-03） ----------


def test_migrate_old_db_adds_direction_lifecycle_columns(g2_old_db):
    """旧库补方向生命周期四列；历史行状态按旧 enabled 换算——停用方向保持 disabled。"""
    from app.db import init_db

    init_db()
    assert {"status", "temp", "expires_at", "deleted_at"} <= _columns_of("direction")
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
