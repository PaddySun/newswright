"""反馈频控与记忆回流闸（SR-1）：per-IP 小时频控（身份轮换不可绕过）、
per-article 聚合日上限（DB 计数口径）、record_feedback 回流聚合闸（超 cap 丢弃
回流但 reaction 照常入库）。设计依据见 docs/design-index.md「AC-13.1」。
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.api.deps import VISITOR_COOKIE_NAME
from app.models import Article, ArticleReaction, Author, MemoryEntry
from app.siteconfig import set_config

DEFAULT_IP_LIMIT = 30
DEFAULT_ARTICLE_LIMIT = 100
DEFAULT_MEMORY_CAP = 50


@pytest.fixture()
def article(db_session):
    author = Author(name="频控作者", model="m")
    db_session.add(author)
    db_session.commit()
    a = Article(author_id=author.id, title="频控文章", body="b", citations=[])
    db_session.add(a)
    db_session.commit()
    return a


@pytest.fixture(autouse=True)
def _reset_feedback_limiter():
    """频控器进程内状态不跨测试泄漏（本文件攻击用例会打满 IP 桶，必须清理
    以免波及后续测试文件——conftest 不改，文件内自理）。"""
    from app.api.feedback import feedback_limiter

    feedback_limiter._store.clear()
    yield
    feedback_limiter._store.clear()


def _like(api_client, article, visitor_id):
    api_client.cookies.set(VISITOR_COOKIE_NAME, visitor_id)
    return api_client.post(
        "/feedback", json={"article_id": article.id, "verdict": "like"})


def test_ip_bucket_blocks_cookie_rotation_attack(api_client, db_session, article):
    """AC-1.4 攻击回归：同 IP 轮换 cookie 连发（每次新身份绕过唯一约束）——
    第 31 次（缺省口径）起 429，证明闸门不受身份轮换绕过。"""
    for i in range(DEFAULT_IP_LIMIT):
        r = _like(api_client, article, f"attacker-{i}")
        assert r.status_code == 200, f"第 {i + 1} 次应放行: {r.text}"
        assert r.json() == {"counted": True}
    r31 = _like(api_client, article, "attacker-31")
    assert r31.status_code == 429
    assert r31.json()["code"] == "FEEDBACK_RATE_LIMITED"
    # 前 30 次均已入库（身份轮换确实造成了刷量，闸门在第 31 次截断）
    assert db_session.query(ArticleReaction).filter_by(
        article_id=article.id).count() == DEFAULT_IP_LIMIT


def test_ip_limit_keeps_already_counted_semantics(api_client, db_session, article):
    """限内重复请求（同 cookie）仍落 already_counted 幂等语义（AC-1.4 尾句）。"""
    r1 = _like(api_client, article, "dup-1")
    assert r1.status_code == 200 and r1.json() == {"counted": True}
    r2 = _like(api_client, article, "dup-1")
    assert r2.status_code == 200
    assert r2.json() == {"counted": False, "reason": "already_counted"}


def test_ip_limit_covers_comment_path(api_client, db_session, article, auth_client):
    """comment 同入口计数（AC-1.1：like/dislike/comment 全部）——登录评论与匿名
    点赞共享同一 IP 桶（auth_client 与 api_client 同 TestClient 进程）。"""
    r = auth_client.post("/feedback", json={
        "article_id": article.id, "verdict": "comment", "text": "占一次额度"})
    assert r.status_code == 200
    # auth_client 已带登录 cookie 但 visitor cookie 每次请求同一 IP；再打满剩余额度
    for i in range(DEFAULT_IP_LIMIT - 1):
        rr = _like(api_client, article, f"fill-{i}")
        assert rr.status_code == 200
    r_over = auth_client.post("/feedback", json={
        "article_id": article.id, "verdict": "comment", "text": "应超限"})
    assert r_over.status_code == 429
    assert r_over.json()["code"] == "FEEDBACK_RATE_LIMITED"


def test_ip_limit_window_roll_with_injected_now():
    """固定窗语义单测：满 30 拒绝，注入 now 前滚 1 小时后窗口翻新放行
    （禁真等——now 注入口）。"""
    from app.api.deps import FeedbackRateLimiter

    base = datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc)
    clock = {"t": base}

    def fake_now():
        return clock["t"]

    limiter = FeedbackRateLimiter(now=fake_now)
    for _ in range(DEFAULT_IP_LIMIT):
        assert limiter.allow("1.2.3.4", limit=DEFAULT_IP_LIMIT)
    assert not limiter.allow("1.2.3.4", limit=DEFAULT_IP_LIMIT)
    clock["t"] = base + timedelta(hours=1, seconds=1)
    assert limiter.allow("1.2.3.4", limit=DEFAULT_IP_LIMIT)


def test_ip_limit_site_config_override(api_client, db_session, article):
    """feedback_ip_hourly_limit 可经 site_config 调低（缺省 30 非硬编码）。"""
    set_config(db_session, "feedback_ip_hourly_limit", 2)
    assert _like(api_client, article, "cfg-1").status_code == 200
    assert _like(api_client, article, "cfg-2").status_code == 200
    r3 = _like(api_client, article, "cfg-3")
    assert r3.status_code == 429
    assert r3.json()["code"] == "FEEDBACK_RATE_LIMITED"


def test_article_daily_limit_blocks_new_reactions(api_client, db_session, article):
    """AC-1.2：当日该文 ArticleReaction 行数达缺省 100 后，新访客首赞 429；
    already_counted 幂等不受影响（无新行不消耗判定）。"""
    for i in range(DEFAULT_ARTICLE_LIMIT):
        db_session.add(ArticleReaction(article_id=article.id,
                                       visitor_hash=f"cookie:seed-{i}",
                                       verdict="like"))
    db_session.commit()
    r_new = _like(api_client, article, "fresh-visitor")
    assert r_new.status_code == 429
    assert r_new.json()["code"] == "FEEDBACK_RATE_LIMITED"
    r_dup = _like(api_client, article, "seed-0")
    assert r_dup.status_code == 200
    assert r_dup.json() == {"counted": False, "reason": "already_counted"}


def test_article_daily_limit_boundary_allows_at_99(api_client, db_session, article):
    """99 行（上限 -1）时新访客仍可计到第 100 行（含边界：达 100 后拒绝）。"""
    for i in range(DEFAULT_ARTICLE_LIMIT - 1):
        db_session.add(ArticleReaction(article_id=article.id,
                                       visitor_hash=f"cookie:b-{i}",
                                       verdict="like"))
    db_session.commit()
    r = _like(api_client, article, "b-100th")
    assert r.status_code == 200 and r.json() == {"counted": True}
    r_next = _like(api_client, article, "b-101th")
    assert r_next.status_code == 429


def test_article_daily_limit_config_override(api_client, db_session, article):
    set_config(db_session, "feedback_article_daily_limit", 1)
    assert _like(api_client, article, "d-1").status_code == 200
    r2 = _like(api_client, article, "d-2")
    assert r2.status_code == 429
    assert r2.json()["code"] == "FEEDBACK_RATE_LIMITED"


def test_memory_gate_drops_refeed_at_cap(api_client, db_session, article, caplog):
    """AC-1.3：同作者当日 feedback 记忆已达缺省 50 条 → 回流丢弃（reaction
    照常入库）+ log.warning 含 author_id；未达 cap 照常回流。"""
    author_id = article.author_id
    for i in range(DEFAULT_MEMORY_CAP):
        db_session.add(MemoryEntry(author_id=author_id, module="feedback",
                                   content=f"存量记忆 {i}", source_event="feedback"))
    db_session.commit()
    with caplog.at_level("WARNING", logger="newswright.authors.memory"):
        r = _like(api_client, article, "mem-cap")
    assert r.status_code == 200 and r.json() == {"counted": True}
    # reaction 入库、记忆不增
    assert db_session.query(ArticleReaction).filter_by(
        article_id=article.id).count() == 1
    assert db_session.query(MemoryEntry).filter_by(
        author_id=author_id, module="feedback").count() == DEFAULT_MEMORY_CAP
    assert str(author_id) in caplog.text


def test_memory_gate_allows_below_cap(api_client, db_session, article):
    """cap-1 条时回流照常（第 50 条入内，此后第 51 次计数被丢）。"""
    author_id = article.author_id
    for i in range(DEFAULT_MEMORY_CAP - 1):
        db_session.add(MemoryEntry(author_id=author_id, module="feedback",
                                   content=f"存量 {i}", source_event="feedback"))
    db_session.commit()
    r = _like(api_client, article, "mem-50th")
    assert r.status_code == 200
    assert db_session.query(MemoryEntry).filter_by(
        author_id=author_id, module="feedback").count() == DEFAULT_MEMORY_CAP
    r2 = _like(api_client, article, "mem-51th")
    assert r2.status_code == 200
    assert db_session.query(MemoryEntry).filter_by(
        author_id=author_id, module="feedback").count() == DEFAULT_MEMORY_CAP


def test_memory_gate_counts_only_today_entries(db_session, article):
    """当日窗口口径：昨日记忆条不计入今日 cap（local_day_start 日切）。"""
    author_id = article.author_id
    yesterday = datetime.now(timezone.utc) - timedelta(days=2)
    for i in range(DEFAULT_MEMORY_CAP):
        db_session.add(MemoryEntry(author_id=author_id, module="feedback",
                                   content=f"昨日 {i}", source_event="feedback",
                                   created_at=yesterday))
    db_session.commit()
    from app.authors.memory import record_feedback

    entry = record_feedback(db_session, article, verdict="like")
    assert entry is not None  # 昨日条不占今日额度，回流照常


def test_memory_gate_config_override(api_client, db_session, article):
    set_config(db_session, "feedback_memory_daily_cap", 1)
    assert _like(api_client, article, "cap1-a").status_code == 200
    _like(api_client, article, "cap1-b")
    assert db_session.query(MemoryEntry).filter_by(
        author_id=article.author_id, module="feedback").count() == 1
