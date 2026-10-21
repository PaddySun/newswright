"""统计总览作者名映射契约测试（GET /api/stats/overview 增并列键
author_names——UI2 W0b，服务 P5 作者卡 token 呈现）。

覆盖口径：author_names 为 {author_id(str): name} 并列映射（token_by_author
原结构零破坏）；用量行指向已删/不存在作者时该 id 不进映射，但 token_by_author
原键保留。设计依据见 docs/design-index.md「AC-10.1」。
"""
from datetime import datetime, timedelta, timezone

from app.models import Author, UsageLog


def _mk_usage(db, ref_id: int, *, call_point="writing", prompt=100) -> None:
    db.add(UsageLog(provider="deepseek", model="m", call_point=call_point,
                    prompt_tokens=prompt, completion_tokens=10,
                    ref_type="author", ref_id=ref_id,
                    # 相对当下（窗口内）——overview 按 now-window 滚动过滤，
                    # 硬编码历史日期会随真实时间流逝滚出 7 天窗（2026-10-21
                    # 实证：固定 2026-10-14 恰好过期，BE-8 执行期修复）
                    created_at=datetime.now(timezone.utc) - timedelta(days=1)))


def test_overview_author_names_maps_ids_to_names(auth_client, db_session):
    """author_names 并列映射与 token_by_author 键对齐（str(id) → name）。"""
    a1 = Author(name="映射作者一", model="m")
    a2 = Author(name="映射作者二", model="m")
    db_session.add_all([a1, a2])
    db_session.commit()
    _mk_usage(db_session, a1.id)
    _mk_usage(db_session, a2.id)
    _mk_usage(db_session, a1.id, call_point="prefilter", prompt=50)
    db_session.commit()

    body = auth_client.get("/api/stats/overview").json()
    assert body["author_names"] == {str(a1.id): "映射作者一", str(a2.id): "映射作者二"}
    # 原结构零破坏：键集合不变、call_point 聚合形态不变
    assert set(body["token_by_author"]) == {str(a1.id), str(a2.id)}
    assert body["token_by_author"][str(a1.id)]["writing"]["prompt_tokens"] == 100
    assert body["token_by_author"][str(a1.id)]["prefilter"]["prompt_tokens"] == 50


def test_overview_skips_missing_author_rows(auth_client, db_session):
    """用量行指向不存在的作者：token_by_author 保留原键，author_names 不含该 id。"""
    a = Author(name="在册作者", model="m")
    db_session.add(a)
    db_session.commit()
    _mk_usage(db_session, a.id)
    _mk_usage(db_session, 66666)  # 作者行不存在（已删等）
    db_session.commit()

    body = auth_client.get("/api/stats/overview").json()
    assert str(66666) in body["token_by_author"]
    assert body["author_names"] == {str(a.id): "在册作者"}


def test_overview_without_author_usage_has_empty_mapping(auth_client, db_session):
    """无作者用量 → author_names={}（空映射原样呈现）。"""
    body = auth_client.get("/api/stats/overview").json()
    assert body["author_names"] == {}
    assert body["token_by_author"] == {}
