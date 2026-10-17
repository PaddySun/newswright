"""LLM 选源层与注册表契约（providers.resolve / providers.registry）：补面。

四面（C4 后选源层治理条款）：
- 注册表可用性：注册名可解析出对应 provider 实例（注册语义不因登记值
  损坏而失效——启动校验与全部消费方的前置）；
- 模型变体绑定：resolve(name, model=…) 取到的实例携带该模型绑定
  （缓存键=(域,名,model) 的值半边——键不同只是必要条件，实例内容须绑定）；
- 计量归属会话刷新：resolve_chat 单候选/多候选路径返回的实例归因当前
  调用方会话（缓存实例的 db 刷新为当前会话——不写向已关闭的旧会话）；
- 冷却 TTL 语义：TTL=1 秒是真实冷却（TTL<=0 才是 no-op——结构就位、
  默认不启用，但正 TTL 必须生效）；合法候选名单通过启动校验。
设计依据见 docs/design-index.md「LR-1」「LR-2」「LR-3」。
"""
import pytest

import app.config as cfg
from app.providers import resolve as resolve_mod
from app.providers.deepseek import DeepSeekProvider
from app.providers.registry import get_provider
from app.providers.resolve import (
    cooldown_remaining,
    mark_cooldown,
    resolve,
    resolve_chat,
)


@pytest.fixture()
def clean_resolve():
    resolve_mod._reset_for_tests()
    yield resolve_mod
    resolve_mod._reset_for_tests()


def test_registry_resolves_registered_provider_instance(db_session):
    """注册名解析：get_provider("deepseek") 返回 DeepSeekProvider 实例
    （注册表登记的是可用工厂——名字可解析是配置面与代码面的唯一耦合点）。"""
    inst = get_provider("deepseek", db_session)
    assert isinstance(inst, DeepSeekProvider)


def test_resolve_model_variant_carries_model_binding(clean_resolve, db_session):
    """模型变体绑定：resolve(name, model="X") 的实例缺省模型为 X
    （variant 按模型出变体的语义半边）。"""
    p = resolve("deepseek", db_session, model="deepseek-v4-pro")
    assert p._default_model() == "deepseek-v4-pro"


def test_resolve_chat_single_candidate_attribution_session(clean_resolve, db_session):
    """单候选路径：resolve_chat 返回的实例计量归属当前调用方会话
    （实例 db 即调用方 db——跨请求复用实例不写向旧会话）。"""
    p = resolve_chat(db_session)
    assert p is not None and p.db is db_session


def test_resolve_chat_multi_candidate_attribution_session(
        clean_resolve, db_session, monkeypatch):
    """多候选路径：首个未冷却候选的实例同样归因当前调用方会话。"""
    monkeypatch.setattr(cfg, "LLM_CANDIDATES", ["deepseek", "moark"])
    p = resolve_chat(db_session)
    assert p is not None and p.db is db_session


def test_mark_cooldown_positive_ttl_is_real_cooldown(clean_resolve):
    """TTL=1 秒是真实冷却：标记后剩余冷却 > 0（TTL<=0 才是 no-op 边界，
  正值 TTL 不得被并入 no-op 判定）。"""
    mark_cooldown("probe-name", seconds=1)
    assert cooldown_remaining("probe-name") > 0


def test_validate_accepts_legal_candidate_list(clean_resolve, monkeypatch):
    """合法候选名单通过启动校验：LLM_CANDIDATES 含全部已注册名时不抛
    （候选校验只拦不可用名，不得把合法配置一并拒启动）。"""
    monkeypatch.setattr(cfg, "LLM_CANDIDATES", ["moark"])
    monkeypatch.setattr(cfg, "LLM_PROVIDER", "deepseek")
    resolve_mod.validate_provider_config()  # 不抛即通过
