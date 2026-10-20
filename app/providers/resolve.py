"""LLM 选源层：进程级实例缓存 + 有序候选列表 + TTL 冷却结构。

治理目标：消费方只见名字（经 registry），切换提供方 = 配置一处变化；
reasoner_available 探测状态随缓存实例跨调用存活（不再逐调用丢失）。
D1（BE-7）起默认启用：候选链 moark→deepseek 双账户真冗余、冷却 TTL 缺省
1800 秒，供应商级致命 4xx 由 providers.base._call 标记（键=(name, None)，
与 resolve_chat 查询键一致）；冷却态为进程级 time.monotonic——重启即清、
下次失败重标（接受语义，低流量系统不做持久熔断状态）。

语义要点：
- 实例缓存键=(域,名,model)，命中时把实例的计量归属（db）刷新为当前调用方
  会话——跨请求/跨测试复用实例不写向已关闭的旧会话；
- 冷却 TTL 显式 0 时标记为 no-op（不启用哨兵，缺省 1800 已启用）；
  单候选永不进入冷却判定——无备源可切，冷却只会让选源平白返回 None；
- 全部候选冷却中 → 返回 None，消费方走各自既有降级链（FAILED 终态 /
  回退生成 / 全量慢速等，不在本层统一吞错）。
设计依据见 docs/design-index.md「LR-2」「LR-3」「PV-1」「PV-2」。
"""
from __future__ import annotations

import time

from sqlalchemy.orm import Session

from .. import config
from ..transport.errors import FrameworkError
from . import registry
from .base import LLMProvider

_DOMAIN_CHAT = "chat"

# 进程级状态：实例缓存 + 冷却到期表（键=(名, model)）
_cache: dict[tuple[str, str, str | None], LLMProvider] = {}
_cooldown_until: dict[tuple[str, str | None], float] = {}


def resolve(name: str, db: Session, *, model: str | None = None) -> LLMProvider:
    """单名解析（进程级缓存）：同 (域,名,model) 返回同一实例，探测状态
    （reasoner_available 等）与观测面随实例跨调用存活。"""
    key = (_DOMAIN_CHAT, name, model)
    inst = _cache.get(key)
    if inst is None:
        inst = registry.get_provider(name, db, model=model)
        _cache[key] = inst
    else:
        # 缓存实例归因到当前调用方会话（计量落账随调用方，不滞留旧会话）
        inst.db = db
    return inst


def configured_candidates() -> list[str]:
    """有序候选列表：LLM_CANDIDATES 显式配置优先（缺省 moark→deepseek
    双候选，D1），空值回落 [LLM_PROVIDER] 单候选形态。"""
    names = [n for n in (config.LLM_CANDIDATES or []) if n]
    return names or [config.LLM_PROVIDER]


def resolve_chat(db: Session, *, candidates: list[str] | None = None) -> LLMProvider | None:
    """chat 域选源主入口：按序返回首个未冷却候选；全部候选冷却中返回 None
    （消费方走既有降级链）。单候选形态跳过冷却判定（永不因冷却返回 None）。"""
    names = candidates if candidates is not None else configured_candidates()
    if len(names) < 2:
        return resolve(names[0], db)
    now = time.monotonic()
    for name in names:
        if _cooldown_until.get((name, None), 0.0) > now:
            continue
        return resolve(name, db)
    return None


def mark_cooldown(name: str, *, model: str | None = None, seconds: float | None = None) -> None:
    """标记一个候选进入冷却（生产调用方=providers.base._call 供应商级致命
    接线，键必须 (name, None)——与 resolve_chat 查询键一致，按 payload
    模型名标记即键不匹配静默失效）。TTL 取 seconds 显式值，缺省读
    LLM_PROVIDER_COOLDOWN_SECONDS（BE-7 起缺省 1800）；显式 0=no-op 哨兵。"""
    ttl = config.LLM_PROVIDER_COOLDOWN_SECONDS if seconds is None else seconds
    if ttl <= 0:
        return
    _cooldown_until[(name, model)] = time.monotonic() + ttl


def cooldown_remaining(name: str, *, model: str | None = None) -> float:
    """候选剩余冷却秒数（观测面：测试与运维查询用）。"""
    return max(0.0, _cooldown_until.get((name, model), 0.0) - time.monotonic())


def validate_provider_config() -> None:
    """启动期 provider 名解析校验：配置名不可解析即拒绝启动（报错含可用名单）。
    嵌入域允许 none（禁用回退全量慢速）；chat 域不允许 none。"""
    problems: list[str] = []
    chat_names = registry.available()
    chat = str(config.LLM_PROVIDER or "").strip()
    if chat in ("", "none"):
        problems.append(
            f"LLM_PROVIDER={chat!r} 非法：chat 域不支持 none 禁用（可用: {chat_names}）")
    elif chat not in chat_names:
        problems.append(f"LLM_PROVIDER={chat!r} 未注册（可用: {chat_names}）")
    for cand in config.LLM_CANDIDATES:
        if cand == "none" or cand not in chat_names:
            problems.append(
                f"LLM_CANDIDATES 含不可用名 {cand!r}（chat 域不支持 none；可用: {chat_names}）")
    embed = str(config.EMBED_PROVIDER or "").strip()
    if embed and embed != "none":
        from ..embedding import registry as embed_registry
        embed_names = embed_registry.available()
        if embed not in embed_names:
            problems.append(
                f"EMBED_PROVIDER={embed!r} 未注册（可用: {embed_names + ['none']}）")
    if problems:
        raise FrameworkError("provider 配置校验失败: " + "; ".join(problems))


def _reset_for_tests() -> None:
    """清空选源层进程级状态（测试复位位；生产不调用——缓存随进程存活）。"""
    _cache.clear()
    _cooldown_until.clear()
