"""全部 ORM 模型（任务书 §5.1 最小集）。JSON 一律用 SQLAlchemy JSON 类型，保持 PG 可迁移。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Direction(Base):
    __tablename__ = "direction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    prompt: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(20), default="v1")
    threshold: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Source(Base):
    __tablename__ = "source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    direction_id: Mapped[int] = mapped_column(ForeignKey("direction.id"))
    url: Mapped[str] = mapped_column(String(1000))
    type: Mapped[str] = mapped_column(String(20), default="rss")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 调度退避计数（能力①）：连续失败 ≥阈值跳过该源并探测拉长
    backoff_failures: Mapped[int] = mapped_column(Integer, default=0)
    backoff_skips: Mapped[int] = mapped_column(Integer, default=0)
    # type=web 扩展（M9）：监测配置与内容哈希（etag/Last-Modified 缺失时的变更检测兜底）
    source_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Item(Base):
    __tablename__ = "item"
    __table_args__ = (UniqueConstraint("source_id", "guid", name="uq_item_source_guid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    guid: Mapped[str] = mapped_column(String(1000))
    url: Mapped[str] = mapped_column(String(2000), default="")
    title: Mapped[str] = mapped_column(String(2000), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_text: Mapped[str] = mapped_column(Text, default="")
    # FETCHED / REJECTED_RULED / FAILED（抓取侧语义：抓取成功但被过滤 ≠ 抓取失败）
    fetch_status: Mapped[str] = mapped_column(String(30), default="FETCHED")
    rule_reject_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 零信任过滤预留位：PASSED / REJECTED / PENDING；REJECTED 条目全文照存
    sanitize_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    sanitize_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sanitize_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScoreResult(Base):
    __tablename__ = "score_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"))
    direction_id: Mapped[int] = mapped_column(ForeignKey("direction.id"))
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relevance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    band: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    prompt_version: Mapped[str] = mapped_column(String(20), default="v1")
    model: Mapped[str] = mapped_column(String(100))
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    # OK / FAILED（解析失败或调用耗尽重试后落 FAILED + error）
    status: Mapped[str] = mapped_column(String(20), default="OK")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Author(Base):
    __tablename__ = "author"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    model: Mapped[str] = mapped_column(String(100))
    persona_prompt: Mapped[str] = mapped_column(Text, default="")
    global_system_prompt: Mapped[str] = mapped_column(Text, default="")
    # JSON: [{direction_id, threshold}]
    readable_directions: Mapped[list] = mapped_column(JSON, default=list)
    # JSON: {占位符名: 载入条数}，如 {"feedback_memory": 5, "topic_memory": 3}
    memory_config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class MemoryEntry(Base):
    __tablename__ = "memory_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("author.id"))
    module: Mapped[str] = mapped_column(String(50))  # feedback / topic / style
    content: Mapped[str] = mapped_column(Text)
    source_event: Mapped[str] = mapped_column(String(50))  # feedback / write
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WriteRun(Base):
    __tablename__ = "write_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("author.id"))
    triggered_by: Mapped[str] = mapped_column(String(50), default="manual")
    reading_set_item_ids: Mapped[list] = mapped_column(JSON, default=list)
    prompt_snapshot: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[str | None] = mapped_column(String(10), nullable=True)  # WRITE / SKIP
    article_id: Mapped[int | None] = mapped_column(ForeignKey("article.id"), nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_thinking: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(100))
    # OK / FAILED（引用校验二次失败或调用失败）
    status: Mapped[str] = mapped_column(String(20), default="OK")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Article(Base):
    __tablename__ = "article"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("author.id"))
    title: Mapped[str] = mapped_column(String(2000))
    body: Mapped[str] = mapped_column(Text)
    # JSON: [{item_id, quote}]
    citations: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="PUBLISHED_TO_C")


class UsageLog(Base):
    __tablename__ = "usage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    call_point: Mapped[str] = mapped_column(String(30))  # scoring / writing / prefilter
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # moark 等非 token 计费方使用（deepseek 恒 0）
    billing_units: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # item / author
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PipelineTask(Base):
    __tablename__ = "pipeline_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # fetch / score / write
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING/RUNNING/DONE/FAILED
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
