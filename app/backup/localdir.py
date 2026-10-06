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

from ..db import engine
from ..siteconfig import get_config
from . import BackupTarget, register, rotate_backups

log = logging.getLogger("newswright.backup")

FILE_PREFIX = "newswright-backup-"


class LocalDirectoryBackup(BackupTarget):
    name = "local_dir"

    def run_backup(self) -> Path:
        directory = Path(str(get_config(self.db, "backup_dir") or "backups"))
        directory.mkdir(parents=True, exist_ok=True)
        # 纳秒尾缀零补齐 6 位：文件名字典序 = 时间序（轮转按名排序挤出最旧）
        dest_path = directory / f"{FILE_PREFIX}{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000:06d}.db"
        src_conn = engine.raw_connection()
        try:
            dest = sqlite3.connect(str(dest_path))
            try:
                src_conn.backup(dest)
            finally:
                dest.close()
        finally:
            src_conn.close()
        removed = rotate_backups(directory, FILE_PREFIX)
        if removed:
            log.info("备份轮转：挤出最旧 %d 份", len(removed))
        log.info("备份完成: %s", dest_path.name)
        return dest_path


register("local_dir", LocalDirectoryBackup)
