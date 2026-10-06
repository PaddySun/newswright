"""备份能力插件层：BackupTarget 接口 + 注册表 + 本地目录子类（SQLite 在线备份）。

纪律（ADR-10 同构）：抽象 + 子类 + 注册一行；本地目录轮转保留 ≥7 份；
对象存储为未来子类。备份失败 WARN + 任务可恢复，不阻断任何轮。
设计依据见 docs/design-index.md「ADR-10」。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from sqlalchemy.orm import Session

log = logging.getLogger("newswright.backup")

_registry: dict[str, type["BackupTarget"]] = {}

BACKUP_KEEP_COUNT = 7


def register(name: str, cls: type["BackupTarget"]) -> None:
    _registry[name] = cls


def get_backup_target(name: str, db: Session) -> "BackupTarget | None":
    cls = _registry.get(name)
    return cls(db) if cls else None


def default_backup_target(db: Session) -> "BackupTarget | None":
    if not _registry:
        return None
    return get_backup_target(sorted(_registry)[0], db)


class BackupTarget(ABC):
    """备份目标接口：run_backup 执行一次备份并返回备份文件路径。"""

    name = "base"

    def __init__(self, db: Session) -> None:
        self.db = db

    @abstractmethod
    def run_backup(self) -> Path:
        """执行一次备份，返回备份产物路径；失败抛异常由调用方统一转 WARN。"""


def rotate_backups(directory: Path, prefix: str,
                   *, keep: int = BACKUP_KEEP_COUNT) -> list[Path]:
    """备份轮转：保留最新 keep 份，挤出更旧的。返回被删除的文件列表。"""
    files = sorted(
        (p for p in directory.glob(f"{prefix}*") if p.is_file()),
        key=lambda p: p.name,
    )
    removed = []
    for old in files[:-keep] if len(files) > keep else []:
        old.unlink(missing_ok=True)
        removed.append(old)
    return removed
