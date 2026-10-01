"""向量生成 provider 注册表（与 search/rerank registry 同模式）。"""
from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from .base import EmbeddingError, EmbeddingProvider
from .moark import MoarkEmbeddingProvider

_registry: dict[str, Callable[[Session], EmbeddingProvider]] = {}


def register(name: str, factory: Callable[[Session], EmbeddingProvider]) -> None:
    _registry[name] = factory


def get_provider(name: str, db: Session, *, model: str | None = None) -> EmbeddingProvider:
    if name in ("none", "", None):
        raise EmbeddingError("embedding_provider=none（向量生成未启用）")
    factory = _registry.get(name)
    if factory is None:
        raise EmbeddingError(f"未注册的向量 provider: {name!r}（已注册: {sorted(_registry)}）")
    if model is not None:
        # model 参数化：同一适配器按模型名出多个实例（选型实测需要跨模型对比）
        return factory(db, model=model)  # type: ignore[misc]
    return factory(db)


def available() -> list[str]:
    return sorted(_registry)


register("moark", MoarkEmbeddingProvider)
