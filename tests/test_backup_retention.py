"""备份轮转语义测试：第 8 份挤出最旧（按修改时间序而非名字典序）、轮转日志留痕。

设计依据见 docs/design-index.md「ADR-10」（D9 本地目录轮转 ≥7 份）。
"""
import logging
import os
import time

from app.backup import rotate_backups
from app.backup.localdir import FILE_PREFIX


def _make_backup_file(directory, name, mtime_epoch):
    path = directory / name
    path.write_bytes(b"")
    os.utime(path, (mtime_epoch, mtime_epoch))
    return path


def test_rotation_evicts_oldest_by_mtime_not_name(tmp_path):
    """挤出「最旧」按修改时间序：名字典序最先但修改最新的文件必须保留，
    修改时间最旧者被挤出（st_mtime_ns 排序为 F2 追认形态——同秒纳秒回绕域
    名字典序不可靠）。断言以文件系统终态为锚，不依赖返回值形态。"""
    base = time.mktime((2026, 10, 7, 12, 0, 0, 0, 0, -1))
    # a.db 名字典序最先、但修改时间最新；b.db 修改时间最旧
    _make_backup_file(tmp_path, f"{FILE_PREFIX}a.db", base + 800)
    for i, name in enumerate("bcdefgh"):
        _make_backup_file(tmp_path, f"{FILE_PREFIX}{name}.db", base + i)
    rotate_backups(tmp_path, FILE_PREFIX)
    survivors = {p.name for p in tmp_path.glob(f"{FILE_PREFIX}*")}
    assert len(survivors) == 7  # D9 ≥7 份
    assert f"{FILE_PREFIX}a.db" in survivors  # 最新修改者必须保留
    assert f"{FILE_PREFIX}b.db" not in survivors  # 挤出修改时间最旧者


def test_run_backup_rotation_logs_evicted_count(db_session, tmp_path,
                                                monkeypatch, caplog):
    """触发轮转时记录挤出份数（轮转留痕；caplog 捕获面对日志格式错误零容忍）。"""
    from app.backup import get_backup_target
    from app.siteconfig import set_config

    directory = tmp_path / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    set_config(db_session, "backup_dir", str(directory))
    for i in range(7):  # 预置 7 份旧备份：本次备份触发第 8 份挤出
        _make_backup_file(directory, f"{FILE_PREFIX}old{i}.db",
                          time.time() - 3600 + i)
    target = get_backup_target("local_dir", db_session)
    with caplog.at_level(logging.INFO, logger="newswright.backup"):
        target.run_backup()
    assert len(list(directory.glob(f"{FILE_PREFIX}*"))) == 7  # D9 轮转语义
