"""搜索 provider 注册表：按名字注册与获取（配置驱动，"新增子类 + 注册一行"）。"""
from __future__ import annotations

from typing import Callable

from .base import SearchError, SearchProvider
from .bocha import BochaSearchProvider
from .tencent import TencentSearchProvider
_registry: dict[str, Callable[[], SearchProvider]] = {}


def register(name: str, factory: Callable[[], SearchProvider]) -> None:
    _registry[name] = factory


def get_provider(name: str) -> SearchProvider:
    factory = _registry.get(name)
    if factory is None:
        raise SearchError(f"未注册的搜索 provider: {name!r}（已注册: {sorted(_registry)}）")
    return factory()


def available() -> list[str]:
    return sorted(_registry)


register("bocha", BochaSearchProvider)
register("tencent", TencentSearchProvider)
