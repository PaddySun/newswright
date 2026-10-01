"""排序 provider 注册表（与 search/registry 同模式）。"""
from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from .. import config
from .base import RankError, RankProvider
from .bocha_reranker import BochaRerankerProvider
from .jev_rank import BochaJevRankProvider, MoarkJevRankProvider
from .llm_rank import LLMRankProvider
from .moark_reranker import MoarkRerankerProvider

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
# moark reranker（EV6 实测四配置，注册不接线；默认模型走 config.MOARK_RERANK_MODEL）
register("moark_reranker", MoarkRerankerProvider)


def _fixed(model: str) -> type[MoarkRerankerProvider]:
    class _Fixed(MoarkRerankerProvider):
        def __init__(self, db: Session) -> None:
            super().__init__(db, model=model)

    return _Fixed


def _fixed_neohorse() -> type:
    from .jev_rank import MoarkJevRankProvider

    class MoarkJevNeohorseRankProvider(MoarkJevRankProvider):
        name = "moark_jev_neohorse"

        def __init__(self, db: Session) -> None:
            super(MoarkJevRankProvider, self).__init__(
                db,
                base_url=config.MOARK_BASE_URL,
                api_key=config.MOARK_API_KEY,
                model=config.MOARK_JEV_MODEL_NEOHORSE,
            )

    return MoarkJevNeohorseRankProvider


register("moark_reranker_qwen3_06b", _fixed("Qwen3-Reranker-0.6B"))
register("moark_reranker_qwen3_4b", _fixed("Qwen3-Reranker-4B"))
register("moark_reranker_qwen3_8b", _fixed("Qwen3-Reranker-8B"))
register("moark_reranker_bge_v2_m3", _fixed("bge-reranker-v2-m3"))
register("moark_jev_neohorse", _fixed_neohorse())
