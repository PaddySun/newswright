"""SMTP 口令备份擦洗（SR-5）：备份产物中 smtp_pass 行被删除、其余
site_config 键保留、原库零触碰；恢复语义=恢复后 SMTP 需重录（docstring 注明）。
凭据一律哑值（不回显真实凭据纪律）。"""
import sqlite3

import pytest

from app.backup import get_backup_target
from app.siteconfig import set_config

DUMMY_SMTP_PASS = "dummy-not-a-real-secret"


@pytest.fixture()
def backup_dir(tmp_path, db_session):
    directory = tmp_path / "backups"
    set_config(db_session, "backup_dir", str(directory))
    return directory


def _site_config_of(db_path) -> dict:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT key, value FROM site_config").fetchall()
    finally:
        conn.close()
    return dict(rows)


def test_backup_scrubs_smtp_pass_only(db_session, backup_dir, caplog):
    set_config(db_session, "smtp_pass", DUMMY_SMTP_PASS)
    set_config(db_session, "notify_on_source_failure", False)  # 陪跑键：应保留
    db_session.commit()
    target = get_backup_target("local_dir", db_session)
    with caplog.at_level("INFO", logger="newswright.backup"):
        path = target.run_backup()
    backed = _site_config_of(path)
    assert "smtp_pass" not in backed
    assert "notify_on_source_failure" in backed
    assert "擦洗" in caplog.text
    # 原库零触碰：smtp_pass 仍在主库
    live = _site_config_of(db_session.get_bind().url.database)
    assert "smtp_pass" in live


def test_backup_without_smtp_pass_still_scrub_safe(db_session, backup_dir):
    """未配置 smtp_pass 时备份照常完成（擦洗语句无行可删，不报错）。"""
    target = get_backup_target("local_dir", db_session)
    path = target.run_backup()
    assert path.exists()
    assert "smtp_pass" not in _site_config_of(path)


def test_run_backup_docstring_notes_reentry():
    """恢复语义注明：恢复后 SMTP 需重录。"""
    from app.backup.localdir import LocalDirectoryBackup

    doc = LocalDirectoryBackup.run_backup.__doc__ or ""
    assert "SMTP" in doc and "重录" in doc
