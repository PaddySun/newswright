"""发布能力插件位（纯接口占位）：PublishPort 接口 + 注册表。

WordPress 等发布渠道为未来子类（本批零实现）——接口先行锁死注册形态，
与 Notifier/BackupTarget 同构（抽象 + 子类 + 注册一行）。
设计依据见 docs/design-index.md「ADR-10」。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from sqlalchemy.orm import Session

_registry: dict[str, type["PublishPort"]] = {}


def register(name: str, cls: type["PublishPort"]) -> None:
    _registry[name] = cls


def get_publish_port(name: str, db: Session) -> "PublishPort | None":
    cls = _registry.get(name)
    return cls(db) if cls else None


def available() -> list[str]:
    return sorted(_registry)


class PublishPort(ABC):
    """发布端口接口：把成文文章投递到外部渠道（WordPress 为未来子类）。"""

    name = "base"

    def __init__(self, db: Session) -> None:
        self.db = db

    @abstractmethod
    def publish(self, article_row, *, body_markdown: str) -> dict:
        """发布一篇文章，返回 {external_id, url} 形态结果。占位接口，本批零实现。"""


def export_article_snapshot(article_row, *, body_markdown: str) -> Path:
    """占位期的唯一产出形态：文章快照落文件（发布行为本身不做）。"""
    raise NotImplementedError("PublishPort 本批为纯接口占位（WordPress 为未来子类）")
