"""LLM provider 注册表（与 embedding/rerank registry 同模式）。

消费方一律经 resolve 选源层取用，不 import 具体厂商类；注册名是配置面
（LLM_PROVIDER / LLM_CANDIDATES）与代码面的唯一耦合点。
none 哨兵语义仅对可禁用能力（嵌入域）合法——chat 域配置 none 即配置错误，
本注册表不为 chat 实现 none 禁用路径。
设计依据见 docs/design-index.md「LR-1」「LR-4」。
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from ..transport.errors import FrameworkError
from .base import LLMProvider
from .deepseek import DeepSeekProvider
from .moark_chat import MoarkChatProvider
from .moark_jev import MoarkJevProvider

_registry: dict[str, Callable[..., LLMProvider]] = {}


def register(name: str, factory: Callable[..., LLMProvider]) -> None:
    _registry[name] = factory


def get_provider(name: str, db: Session, *, model: str | None = None) -> LLMProvider:
    if name in ("none", "", None):
        raise FrameworkError("chat 域不支持 none 禁用（none 哨兵仅嵌入域合法）")
    factory = _registry.get(name)
    if factory is None:
        raise FrameworkError(f"未注册的 LLM provider: {name!r}（已注册: {sorted(_registry)}）")
    if model is not None:
        return factory(db, model=model)  # type: ignore[misc]
    return factory(db)


def available() -> list[str]:
    return sorted(_registry)


def variant(name: str, *, model: str | None = None) -> Callable[[Session], LLMProvider]:
    """模型绑定变体工厂：variant("moark", model="X")(db) → 以 X 为缺省模型的实例
    （选型实测与主备候选位需要按模型出变体，与 embedding registry 的 model
    参数化同构）。"""
    def _factory(db: Session) -> LLMProvider:
        return get_provider(name, db, model=model)

    return _factory


register("deepseek", DeepSeekProvider)
register("moark", MoarkChatProvider)
register("moark_jev", MoarkJevProvider)
