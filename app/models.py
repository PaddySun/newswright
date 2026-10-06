"""全部 ORM 模型（任务书 §5.1 最小集）。JSON 一律用 SQLAlchemy JSON 类型，保持 PG 可迁移。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, LargeBinary, false, ForeignKey, Index, Integer, String, Text, TypeDecorator, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PromptVersion(TypeDecorator):
    """提示词版本号，统一 integer 存储（设计依据见 docs/design-index.md「D19」）。

    旧库存量行以 'v1' 形态文本存储（SQLite 文本亲和列连整数也回读为文本）：
    写入端把 'v1'/'1'/1 归一为 int，读取端把文本回读值归一为 int，两类存量
    形态都在 ORM 读写路径上无感归一。None 原样放行（列不可空，由默认值兜底）。
    """
    impl = Integer
    cache_ok = True

    @staticmethod
    def _to_int(value) -> int:
        if isinstance(value, int):
            return value
        text = str(value).strip().lower()
        if text.startswith("v"):
            text = text[1:]
        return int(text)

    def process_bind_param(self, value, dialect):
        return None if value is None else self._to_int(value)

    def process_result_value(self, value, dialect):
        return None if value is None else self._to_int(value)


class Base(DeclarativeBase):
    pass


class User(Base):
    """单管理员账号（US-01/ADR-4）。密码只存 argon2id 哈希（D2/D18）。"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    # 首登强制改密（AC-01.1）：改密端点成功后置 false
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSession(Base):
    """服务端会话（ADR-4：HttpOnly cookie 只存 id，状态全在 DB）。

    id = secrets.token_urlsafe(32)（≥128bit）。表名 sessions；类名避开
    sqlalchemy.orm.Session。
    """
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SiteConfig(Base):
    """站点级键值配置（技术书 §4.1）：key(TEXT PK) + value(JSON)。

    本里程碑仅 session_duration_days / client_ip_header 两键（代码内默认值见
    app/siteconfig.py）；表结构预留全部未来键空间（模式 A/B/C、AI 标识、robots、
    timezone、SMTP、预算闸……），公开 REST API 属 US-19 后续，不在此实现。
    """
    __tablename__ = "site_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)


class Direction(Base):
    __tablename__ = "direction"

    # 生命周期状态（设计依据见 docs/design-index.md「AC-03.3」「AC-03.4」）：
    # status 为唯一真值；enabled 是历史布尔列，仅作 active 镜像维持旧读路径兼容，
    # 新代码一律以 status 为准。
    STATUS_ACTIVE = "active"
    STATUS_DISABLED = "disabled"
    STATUS_EXPIRED = "expired"
    STATUS_DELETED = "deleted"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    prompt: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[int] = mapped_column(PromptVersion, default=1)
    threshold: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_ACTIVE, server_default=STATUS_ACTIVE)
    # 临时方向 TTL（temp=true 时有效）；到期由调度侧懒扫描翻 status=expired
    temp: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 方向查询向量缓存（检索路由）：生成文本 = 方向提示词提炼的 rubric 摘要式查询，
    # query_vec_version 记录生成时的 prompt_version——提示词升版即缓存失效重生成
    query_vec: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    query_vec_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 探索层方向级配置（JSON: {enabled, floor, percentile, quota}）：null = 继承
    # site_config 全局键；enabled 缺失键同样回退全局。参数全部为示例值，正式值实测后定
    explore_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def apply_status(self, new_status: str) -> None:
        """切换生命周期状态并同步 enabled 镜像列（仅 active 为真）。"""
        self.status = new_status
        self.enabled = new_status == self.STATUS_ACTIVE
        if new_status == self.STATUS_DELETED:
            self.deleted_at = utcnow()


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
    # 失效三级判别状态（设计依据见 docs/design-index.md「DT-1」）：none/suspect/hard_failed；
    # failure_since 记录进入当前失效态的时间（正常轮清零回 none 时一并清空）。
    # 采集调度与判别状态机在 G2 失效判别批次接线。
    failure_level: Mapped[str] = mapped_column(String(20), default="none", server_default="none")
    failure_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 最近一次抓取错误摘要（DT-1 硬失效判据的展示与排查面，从抓取任务错误同步）
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 连续硬失效轮数（404/403/410）与连续空轮数（200 但内容空/条目归零）——
    # 三级判别的计数状态，成功轮或豁免轮按判据清零
    hard_failures: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    empty_rounds: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # 429/Retry-After 动态降频（D13）：until 期内跳过（reason=rate_limited）；
    # rate_ok_rounds 记降频期满后的连续正常轮数（连续 2 轮正常逐级降档恢复）
    rate_limited_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_level: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    rate_ok_rounds: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # 搜索源关键词边际降频（与 429 降频同构但独立计数）：连续零新增轮计数、
    # 档位与 until；恢复 = hot_batch 关键词更新 / 站长手工刷新 / 方向提示词升版
    keyword_limited_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    keyword_rate_level: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    keyword_zero_rounds: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class Item(Base):
    __tablename__ = "item"
    __table_args__ = (
        UniqueConstraint("source_id", "guid", name="uq_item_source_guid"),
        Index("ix_item_direction_fingerprint", "direction_id", "fingerprint"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    guid: Mapped[str] = mapped_column(String(1000))
    url: Mapped[str] = mapped_column(String(2000), default="")
    title: Mapped[str] = mapped_column(String(2000), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_text: Mapped[str] = mapped_column(Text, default="")
    # FETCHED / REJECTED_RULED / FAILED（抓取侧语义：抓取成功但被过滤 ≠ 抓取失败）
    # G1/W4 新增 DUP：方向内跨源同 URL 指纹命中（全文照存、不进打分，AC-05.2/D15）
    fetch_status: Mapped[str] = mapped_column(String(30), default="FETCHED")
    # 冗余方向外键 + 方向内指纹索引（D15 比对分母=方向内）；历史行两者留空（懒回填不做）
    direction_id: Mapped[int | None] = mapped_column(ForeignKey("direction.id"), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 同方向原 item id（语义近重复/标题兜底链后续批次复用此引用列）
    duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("item.id"), nullable=True)
    rule_reject_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 零信任过滤预留位：PASSED / REJECTED / PENDING；REJECTED 条目全文照存
    sanitize_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    sanitize_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sanitize_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 通道原始响应存档（type=search：单条结果上下文；预留其他通道）
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 搜索通道命中关键词（逐词新增率归因的数据面；其他通道为空）
    source_keyword: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ItemVec(Base):
    """条目语义向量（检索层一等模块的存储基座）。

    - vec 为 float32 小端序列化的 BLOB（标题+截断正文嵌入产物），反序列化与点积
      检索为纯函数（app/retrieval/embedder.py）；万条规模内内存暴力点积足够，
      不引入向量索引组件。
    - model_version 记录生成向量所用的嵌入模型名：换模型场景下历史向量不匹配即
      视同无向量（渐进补齐或显式全量重嵌任务），维度与模型口径绑定防相似度漂移。
    - 唯一约束 (item_id, model_version)：同一条目每个模型版本至多一行向量。
    """
    __tablename__ = "item_vec"
    __table_args__ = (
        UniqueConstraint("item_id", "model_version", name="uq_item_vec_item_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"))
    model_version: Mapped[str] = mapped_column(String(100))
    vec: Mapped[bytes] = mapped_column(LargeBinary)


class ScoreResult(Base):
    __tablename__ = "score_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"))
    direction_id: Mapped[int] = mapped_column(ForeignKey("direction.id"))
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relevance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    band: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    prompt_version: Mapped[int] = mapped_column(PromptVersion, default=1)
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
    # 排序底座开关（能力⑤，M12）：none=不排序；bocha_reranker/bocha_jev/moark_jev/llm
    rank_provider: Mapped[str] = mapped_column(String(30), default="none")
    rank_exclude_below: Mapped[int] = mapped_column(Integer, default=30)  # 归一化 0-100
    # 热点风向段注入写作提示词（能力③→作者侧，M13）
    include_hot_brief: Mapped[bool] = mapped_column(Boolean, default=False)
    # 可配置写作管线（M14）：author.json 全量配置（身份/管线/记忆层）；模型绑定不在此，
    # 仍由本表 model 列（后台/DB 绑定）。NULL=未配置 JSON，走现行 single 路线，行为不变。
    author_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
    # 排序明细/热点段等非结构化过程产物（M12：候选 id/score/provider/耗时）
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
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
    # 引用违规标记：引用校验重试耗尽后仍入库的文章置 true（数据保留，展示侧据此提示"引用存疑"）
    citation_violated: Mapped[bool] = mapped_column(Boolean, default=False)


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
    # DeepSeek 官方 usage 细节（2026-10 文档）：上下文缓存命中与思考模式思维链 token
    cache_hit_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    finish_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # embedding 类调用的输入条数（LLM 调用恒 NULL）
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # item / author
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PipelineTask(Base):
    __tablename__ = "pipeline_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # fetch / score / write / fetch_round / hot_round
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING/RUNNING/DONE/FAILED
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class HotTopic(Base):
    """热榜原始条目（能力③）。每平台每轮全量覆盖式记录，不做增量合并（BettaFish daily 语义）。"""
    __tablename__ = "hot_topic"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(50))
    rank: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(2000))
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 热度值/icon/hover 等
    keyword_contrib: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否进入当轮关键词提炼输入
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    batch_id: Mapped[int] = mapped_column(ForeignKey("hot_batch.id"))


class HotBatch(Base):
    """每轮热榜批次 + 当日关键词提炼结果（hot_round 的聚合产物）。"""
    __tablename__ = "hot_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD（本地日期，BettaFish daily 语义）
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    source_platforms: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchCallLog(Base):
    """搜索 API 调用日志（能力④，与 usage_log 同级纪律）：每次调用一行，成败/被拦截都记。"""
    __tablename__ = "search_call_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50))
    query: Mapped[str] = mapped_column(String(1000))
    keyword_group: Mapped[str | None] = mapped_column(String(200), nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    # ok / error / blocked(SKIPPED_QUOTA)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchQuota(Base):
    """provider × 周期 的调用计数（period_key：日=YYYY-MM-DD，分钟=YYYY-MM-DDTHH:MM）。"""
    __tablename__ = "search_quota"
    __table_args__ = (UniqueConstraint("provider", "period", "period_key", name="uq_search_quota"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50))
    period: Mapped[str] = mapped_column(String(10))  # minute / day
    period_key: Mapped[str] = mapped_column(String(20))
    count: Mapped[int] = mapped_column(Integer, default=0)


class RankCallLog(Base):
    """排序调用日志（能力⑤）。选独立表而非复用 search_call_log 的理由：排序按
    criteria 批次计（一次调用 N 候选），与搜索的 query 语义和限额口径不同，分开归因
    便于 /stats/rank 的分档分布统计。同样受额度闸约束（provider 名即额度键）。"""
    __tablename__ = "rank_call_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50))
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    criteria_key: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 方向名等
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok / error / blocked
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
