"""数据库 engine/session。SQLite 文件库，ORM 写法保持 PG 可迁移。

init_db 在 create_all 之后做一次轻量列迁移：对既有表缺失的新增列执行
ALTER TABLE ADD COLUMN（SQLite/PG 均支持加列），并对历史行回填默认值。
"""
from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from . import config

log = logging.getLogger("newswright.db")

_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(config.DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _migrate_added_columns() -> None:
    """为既有表补齐后加的列（create_all 不会 ALTER 已存在表）。"""
    from . import models

    insp = inspect(engine)
    # 表名 → {列名: DDL 片段（列类型 + 默认）}；仅列追加，不改不改删
    additions: dict[str, dict[str, str]] = {
        "source": {
            "backoff_failures": "INTEGER NOT NULL DEFAULT 0",
            "backoff_skips": "INTEGER NOT NULL DEFAULT 0",
            "source_config": "JSON",
            "content_hash": "VARCHAR(64)",
            # 失效判别与错误展示列（G2）：历史行视为正常（none / 无错误）
            "failure_level": "VARCHAR(20) NOT NULL DEFAULT 'none'",
            "failure_since": "DATETIME",
            "last_error": "TEXT",
            # 死刑探活时钟（BE-3/D6）：nullable 无回填——历史行 null = 从未探活
            "last_probe_at": "DATETIME",
            # 三级判别计数与动态降频状态（G2 失效判别批）：历史行均为正常态
            "hard_failures": "INTEGER NOT NULL DEFAULT 0",
            "empty_rounds": "INTEGER NOT NULL DEFAULT 0",
            "rate_limited_until": "DATETIME",
            "rate_level": "INTEGER NOT NULL DEFAULT 0",
            "rate_ok_rounds": "INTEGER NOT NULL DEFAULT 0",
            "keyword_limited_until": "DATETIME",
            "keyword_rate_level": "INTEGER NOT NULL DEFAULT 0",
            "keyword_zero_rounds": "INTEGER NOT NULL DEFAULT 0",
            # RSS/web 内容零收益自适应（BE-6/R3.8）：历史行 0=无放大
            "zero_gain_rounds": "INTEGER NOT NULL DEFAULT 0",
            "zero_gain_level": "INTEGER NOT NULL DEFAULT 0",
            # 来源自定义名称（UI2 W0a / L1 名称制）：无回填——历史行 null 即
            # 呈现缺省（域名），语义归前端
            "name": "VARCHAR(200)",
            # 软删除位（UI2 W0c / P7）：历史行 DEFAULT 0 即未删除，无需回填
            "deleted": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "author": {
            "rank_provider": "VARCHAR(30) NOT NULL DEFAULT 'none'",
            "rank_exclude_below": "INTEGER NOT NULL DEFAULT 30",
            "include_hot_brief": "BOOLEAN NOT NULL DEFAULT 0",
            "author_json": "JSON",
            # 呈现层两列（F2）：历史作者 bio 为空、未公开
            "bio": "TEXT NOT NULL DEFAULT ''",
            "public_visible": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "write_run": {
            "payload": "JSON",
        },
        "article": {
            "citation_violated": "BOOLEAN NOT NULL DEFAULT 0",
            # 呈现层三列（F2）：历史文章未书签、不公开、AI 标识默认开
            "bookmarked": "BOOLEAN NOT NULL DEFAULT 0",
            "public": "BOOLEAN NOT NULL DEFAULT 0",
            "ai_label": "BOOLEAN NOT NULL DEFAULT 1",
            # 成文时间（UI2 W0a）：nullable；补列当次按 write_run 成文时间 MIN
            # 回填（回填口径见下方 backfill），回填不到留 null
            "created_at": "DATETIME",
        },
        "usage_log": {
            "cache_hit_tokens": "INTEGER NOT NULL DEFAULT 0",
            "reasoning_tokens": "INTEGER NOT NULL DEFAULT 0",
            "finish_reason": "VARCHAR(40)",
            "item_count": "INTEGER",
        },
        "item": {
            "sanitize_status": "VARCHAR(20) NOT NULL DEFAULT 'PENDING'",
            "sanitize_reason": "VARCHAR(500)",
            "sanitize_detail": "JSON",
            "raw": "JSON",
            # G1/W4：URL 指纹去重（D15 方向内）；历史行留空，懒回填不做
            "direction_id": "INTEGER",
            "fingerprint": "VARCHAR(64)",
            "duplicate_of": "INTEGER",
            # 搜索通道命中关键词（逐词归因数据面，G2 搜索归因）；历史行留空
            "source_keyword": "VARCHAR(200)",
        },
        "direction": {
            # 生命周期状态（G2）：历史行按旧 enabled 布尔镜像换算（停用→disabled），
            # 其余新列均可空或带默认，无需额外回填
            "status": "VARCHAR(20) NOT NULL DEFAULT 'active'",
            "temp": "BOOLEAN NOT NULL DEFAULT 0",
            "expires_at": "DATETIME",
            "deleted_at": "DATETIME",
            # 方向查询向量缓存（检索层）：历史行为空 = 未生成，路由时按未命中处理
            "query_vec": "BLOB",
            "query_vec_version": "INTEGER",
            # 探索层方向级配置（JSON）：null = 继承 site_config 全局键
            "explore_config": "JSON",
        },
    }
    with engine.begin() as conn:
        backfill_sanitize = False
        backfill_direction_status = False
        backfill_article_created_at = False
        for table, cols in additions.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col in existing:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                if table == "item" and col == "sanitize_status":
                    backfill_sanitize = True
                if table == "direction" and col == "status":
                    backfill_direction_status = True
                if table == "article" and col == "created_at":
                    backfill_article_created_at = True
                log.info("migrate: %s.%s 已补列", table, col)
        # G1/W4：方向内指纹索引（新库由 create_all 的 __table_args__ 建立；旧库补建）
        if insp.has_table("item"):
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_item_direction_fingerprint "
                "ON item (direction_id, fingerprint)"
            ))
        # G2：direction 生命周期状态历史行换算——status 列随本次补列新增时，
        # 旧 enabled 布尔列是唯一状态痕迹（停用方向必须保持停用，不得复活为 active）
        if backfill_direction_status:
            conn.execute(text(
                "UPDATE direction SET status = "
                "CASE WHEN enabled = 1 THEN 'active' ELSE 'disabled' END "
                "WHERE status = 'active'"
            ))
        # G2：提示词版本存量行归一（D19 统一 integer）：'v1' 形态文本 → 整数。
        # ORM 读写路径由 PromptVersion 类型双向归一兜底，此处做一次性数据归一，
        # 让库内不再保留 'v' 前缀文本形态。
        for tbl in ("direction", "score_result"):
            if not insp.has_table(tbl):
                continue
            cols = {c["name"] for c in insp.get_columns(tbl)}
            if "prompt_version" in cols:
                conn.execute(text(
                    f"UPDATE {tbl} SET prompt_version = CAST(SUBSTR(prompt_version, 2) AS INTEGER) "
                    "WHERE typeof(prompt_version) = 'text' AND prompt_version LIKE 'v%'"
                ))
        # 历史行回填（仅补列当次执行）：sanitize 字段上线前入库的条目视为已通过骨架过滤
        if backfill_sanitize:
            conn.execute(text(
                "UPDATE item SET sanitize_status='PASSED', "
                "sanitize_reason='demo:零信任过滤未启用(历史回填)' WHERE sanitize_status='PENDING'"
            ))
        # UI2 W0a：article.created_at 历史行回填 = 该文章 write_run 成文时间 MIN
        # （多次成文取最早；SKIP/失败无 write_run 的文章回填不到留 null——呈现
        # 按时间未知处理，归前端）。write_run 表由 create_all 先行补建，此处必在。
        if backfill_article_created_at:
            conn.execute(text(
                "UPDATE article SET created_at = "
                "(SELECT MIN(write_run.created_at) FROM write_run "
                " WHERE write_run.article_id = article.id) "
                "WHERE created_at IS NULL"
            ))


def init_db() -> None:
    from . import models  # noqa: F401  确保模型注册后再建表

    models.Base.metadata.create_all(engine)
    _migrate_added_columns()


def get_session() -> Iterator[Session]:
    """FastAPI 依赖用；脚本侧直接用 SessionLocal()。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
