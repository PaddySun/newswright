"""本地目录备份（首个 BackupTarget 子类）：SQLite 在线备份 API + 目录轮转。

在线备份（sqlite3 Connection.backup）不阻塞主库读写；轮转保留 ≥7 份。
备份目录经 site_config backup_dir 配置（默认 backups/）。
设计依据见 docs/design-index.md「ADR-10」。
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from sqlalchemy.orm import Session

from ..siteconfig import get_config
from . import BackupTarget, register, rotate_backups

log = logging.getLogger("newswright.backup")

FILE_PREFIX = "newswright-backup-"


class LocalDirectoryBackup(BackupTarget):
    name = "local_dir"

    def run_backup(self) -> Path:
        """执行一次备份并返回备份文件路径。

        SMTP 凭据擦洗（SR-5）：在线备份是全文件复制、逐行排除不可行，
        故备份完成后对**目标备份文件**开连接删除 site_config.smtp_pass 行
        （原库零触碰）。恢复语义=从备份恢复后 SMTP 口令需重录。
        """
        directory = Path(str(get_config(self.db, "backup_dir") or "backups"))
        directory.mkdir(parents=True, exist_ok=True)
        # 纳秒尾缀零补齐 6 位：文件名可读（轮转按修改时间排序，不依赖名字典序）
        dest_path = directory / f"{FILE_PREFIX}{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000:06d}.db"
        # 动态取当前 engine：测试夹具会重绑 appdb.engine（模块级导入会绑到旧库）
        from .. import db as appdb

        src_conn = appdb.engine.raw_connection()
        try:
            dest = sqlite3.connect(str(dest_path))
            try:
                src_conn.backup(dest)
            finally:
                dest.close()
        finally:
            src_conn.close()
        self._scrub_smtp_pass(dest_path)
        removed = rotate_backups(directory, FILE_PREFIX)
        if removed:
            log.info("备份轮转：挤出最旧 %d 份", len(removed))
        log.info("备份完成: %s", dest_path.name)
        return dest_path

    @staticmethod
    def _scrub_smtp_pass(dest_path: Path) -> None:
        """擦洗备份文件中的 SMTP 凭据（只动备份产物，主库零触碰）。"""
        conn = sqlite3.connect(str(dest_path))
        try:
            conn.execute("DELETE FROM site_config WHERE key='smtp_pass'")
            conn.commit()
        finally:
            conn.close()
        log.info("已擦洗备份中的 SMTP 凭据: %s", dest_path.name)


register("local_dir", LocalDirectoryBackup)
