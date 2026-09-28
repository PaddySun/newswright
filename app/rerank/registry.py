"""排序 provider 注册表（与 search/registry 同模式）。"""
from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from .base import RankError, RankProvider
from .bocha_reranker import BochaRerankerProvider
from .jev_rank import BochaJevRankProvider, MoarkJevRankProvider
from .llm_rank import LLMRankProvider

_registry: dict[str, Callable[[Session], RankProvider]] = {}


def register(name: str, factory: Callable[[Session], RankProvider]) -> None:
    _registry[name] = factory


def get_provider(name: str, db: Session) -> RankProvider:
    if name in ("none", "", None):
        raise RankError("rank_provider=none（排序未启用）")
    factory = _registry.get(name)
    if factory is None:
        raise RankError(f"未注册的排序 provider: {name!r}（已注册: {sorted(_registry)}）")
    return factory(db)


def available() -> list[str]:
    return sorted(_registry)


register("bocha_reranker", BochaRerankerProvider)
register("bocha_jev", BochaJevRankProvider)
register("moark_jev", MoarkJevRankProvider)
register("llm", LLMRankProvider)
