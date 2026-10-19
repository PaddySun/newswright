"""过期会话行清理（SR-2）：purge_expired_sessions 删过期行返回行数、
保留未过期行；挂入 _tick_backup 轮内顺带执行（同一 daily job）。logout 语义
不变（单行删除，见既有 test_auth_logout_me）。"""
from datetime import timedelta

from app.auth import issue_session, purge_expired_sessions
from app.models import User, UserSession


def _user(db_session) -> User:
    user = User(username="purgee", password_hash="x", must_change_password=False)
    db_session.add(user)
    db_session.commit()
    return user


def test_purge_removes_only_expired_rows(db_session):
    user = _user(db_session)
    expired = issue_session(db_session, user, duration_days=-1)  # 已过期
    live = issue_session(db_session, user, duration_days=1)
    expired_id, live_id = expired.id, live.id  # expire 后访问属性会触发 refresh，先取
    n = purge_expired_sessions(db_session)
    assert n == 1
    db_session.expire_all()  # bulk delete 不同步 identity map，读库为准
    assert db_session.query(UserSession).filter_by(id=expired_id).count() == 0
    assert db_session.query(UserSession).filter_by(id=live_id).count() == 1


def test_purge_empty_table_returns_zero(db_session):
    assert purge_expired_sessions(db_session) == 0


def test_purge_keeps_naive_datetime_rows_past_expiry(db_session):
    """边界口径：expires_at 落库为 naive 字符串时的比较行为与 get_valid_session
    同向（naive 视作 UTC）——过期 naive 行同样被清。"""
    user = _user(db_session)
    sess = issue_session(db_session, user, duration_days=1)
    # 直接改成昨天（naive 形态）
    from datetime import datetime, timezone

    sess.expires_at = datetime.now(timezone.utc).replace(
        tzinfo=None) - timedelta(days=1)
    db_session.commit()
    assert purge_expired_sessions(db_session) == 1


def test_tick_backup_also_purges_expired_sessions(db_session, monkeypatch, caplog):
    """_tick_backup 轮内顺带执行：无已注册备份目标（备份跳过）时清理仍发生，
    且 log 一行删除数。"""
    import app.backup
    import app.scheduler as sched

    user = _user(db_session)
    issue_session(db_session, user, duration_days=-1)
    monkeypatch.setattr(app.backup, "default_backup_target", lambda db: None)
    with caplog.at_level("INFO", logger="newswright.scheduler"):
        sched._tick_backup()
    assert db_session.query(UserSession).count() == 0
    assert "过期会话" in caplog.text or "会话清理" in caplog.text
