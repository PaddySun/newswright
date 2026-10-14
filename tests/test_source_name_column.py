"""来源自定义名称列测试（source.name——UI2 W0a 自 W0c 前置：L1 名称制的
数据基础）。

覆盖口径：SourceCreate 带 name 落库 + _source_out 输出该名；不带 name 创建
输出 null（不强制必填——存量与 CLI 形态兼容）；SourceUpdate 可改名；旧库
（name 列上线前形状）经 init_db 补列且历史行 null（呈现缺省=域名归前端）。
设计依据见 docs/design-index.md「L1」。
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

import app.config as cfg
import app.db as appdb


@pytest.fixture()
def one_direction(auth_client):
    d = auth_client.post("/api/directions",
                         json={"name": "来源命名方向", "prompt": "p",
                               "threshold": 60}).json()
    return d


def test_create_source_with_name_persisted_and_output(auth_client, one_direction):
    r = auth_client.post(f"/api/directions/{one_direction['id']}/sources",
                         json={"type": "rss", "url": "https://named.example/feed",
                               "name": "我的早报源"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "我的早报源"

    listed = auth_client.get(f"/api/directions/{one_direction['id']}/sources").json()
    assert any(src["name"] == "我的早报源" for src in listed)


def test_create_source_without_name_outputs_null(auth_client, one_direction):
    r = auth_client.post(f"/api/directions/{one_direction['id']}/sources",
                         json={"type": "rss", "url": "https://plain.example/feed"})
    assert r.status_code == 201
    assert r.json()["name"] is None


def test_update_source_name(auth_client, one_direction):
    created = auth_client.post(
        f"/api/directions/{one_direction['id']}/sources",
        json={"type": "rss", "url": "https://rename.example/feed"}).json()
    r = auth_client.put(f"/api/sources/{created['id']}", json={"name": "改名后的源"})
    assert r.status_code == 200
    assert r.json()["name"] == "改名后的源"


# ---------- 旧库补列形态（db.py additions 机制） ----------

_OLD_SOURCE_NO_NAME = """
CREATE TABLE source (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction_id INTEGER REFERENCES direction(id),
    url VARCHAR(1000) NOT NULL,
    type VARCHAR(20) DEFAULT 'rss',
    enabled BOOLEAN DEFAULT 1,
    last_fetched_at DATETIME,
    etag VARCHAR(500),
    last_modified VARCHAR(500)
)"""


@pytest.fixture()
def source_name_old_db(tmp_path):
    """name 列上线前的旧库夹具：source 表含历史行（夹具模式沿用
    tests/test_db_migration.py 的历史形状裸建 + init_db 由测试自调）。"""
    url = f"sqlite:///{(tmp_path / 'source_name_old.db').as_posix()}"
    cfg.DATABASE_URL = url
    appdb.engine.dispose()
    appdb.engine = create_engine(url, connect_args={"check_same_thread": False},
                                 future=True)
    appdb.SessionLocal.configure(bind=appdb.engine)
    with appdb.engine.begin() as conn:
        conn.execute(text(_OLD_SOURCE_NO_NAME))
        conn.execute(text(
            "INSERT INTO source (direction_id, url, type, enabled) "
            "VALUES (1, 'https://legacy.example/feed', 'rss', 1)"))
    yield
    appdb.engine.dispose()
    cfg.DATABASE_URL = f"sqlite:///{(cfg.PROJECT_ROOT / 'newswright.db').as_posix()}"


def test_migrate_old_source_adds_name_column_with_null_rows(source_name_old_db):
    """旧库 source 补 name 列（无回填）：历史行 null=呈现缺省域名语义。"""
    from app.db import init_db

    init_db()
    columns = {c["name"] for c in inspect(appdb.engine).get_columns("source")}
    assert "name" in columns
    with appdb.engine.connect() as conn:
        legacy_name = conn.execute(
            text("SELECT name FROM source WHERE url = 'https://legacy.example/feed'")
        ).scalar_one()
    assert legacy_name is None
