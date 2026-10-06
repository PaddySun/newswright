"""备份插件测试：本地目录备份产物可打开、轮转 ≥7 份、注册表语义。

设计依据见 docs/design-index.md「ADR-10」。
"""
import sqlite3

import pytest

from app.backup import (
    BACKUP_KEEP_COUNT,
    default_backup_target,
    get_backup_target,
    register,
)
from app.backup.localdir import FILE_PREFIX, LocalDirectoryBackup
from app.siteconfig import set_config


@pytest.fixture()
def backup_dir(tmp_path, db_session):
    directory = tmp_path / "backups"
    set_config(db_session, "backup_dir", str(directory))
    return directory


def test_registry_semantics(db_session):
    register("local_dir", LocalDirectoryBackup)
    assert isinstance(get_backup_target("local_dir", db_session),
                      LocalDirectoryBackup)
    assert default_backup_target(db_session) is not None


def test_backup_file_created_and_openable(db_session, backup_dir):
    target = get_backup_target("local_dir", db_session)
    path = target.run_backup()
    assert path.exists() and path.parent == backup_dir
    conn = sqlite3.connect(str(path))
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()
    assert {"item", "direction", "pipeline_task"} <= tables  # 在线备份含全部表


def test_backup_rotation_keeps_seven(db_session, backup_dir):
    target = get_backup_target("local_dir", db_session)
    for _ in range(BACKUP_KEEP_COUNT + 1):  # 第 8 份挤出最旧
        path = target.run_backup()
    files = sorted(backup_dir.glob(f"{FILE_PREFIX}*"))
    assert len(files) == BACKUP_KEEP_COUNT
    newest = max(files, key=lambda p: p.stat().st_mtime_ns)
    assert path == newest  # 最新一份在场（按修改时间判定）
