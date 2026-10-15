"""LLM 选源层：进程级实例缓存、有序候选列表与 TTL 冷却结构。

覆盖：同 (域,名,model) 两次解析同实例且 reasoner 探测状态跨调用存活 /
缓存实例的计量会话随调用方刷新 / 候选列表按序取用与冷却跳过 /
单候选永不冷却 / 全冷却返回 None 且消费方走既有降级链 /
默认配置（单候选 deepseek、冷却不启用）行为零变。
设计依据见 docs/design-index.md「LR-2」「LR-3」。
"""
import pytest

import app.config as cfg
from app.models import Direction
from app.providers.resolve import (
    cooldown_remaining,
    mark_cooldown,
    resolve,
    resolve_chat,
)


@pytest.fixture()
def clean_resolve():
    """选源层进程级状态的测试隔离位（生产不调用）。"""
    from app.providers import resolve as resolve_mod
    resolve_mod._reset_for_tests()
    yield resolve_mod
    resolve_mod._reset_for_tests()


def test_resolve_returns_same_instance_across_calls(clean_resolve, db_session):
    p1 = resolve("deepseek", db_session)
    p2 = resolve("deepseek", db_session)
    assert p1 is p2


def test_reasoner_probe_state_survives_across_calls(clean_resolve, db_session):
    """探测缓存跨调用（治理目标：探测状态不随实例逐调用丢失）。"""
    p1 = resolve("deepseek", db_session)
    p1.reasoner_available = False
    p2 = resolve("deepseek", db_session)
    assert p2 is p1 and p2.reasoner_available is False


def test_pipeline_direct_write_visible_through_shared_cache(clean_resolve, db_session):
    """管线门禁早停对 provider.reasoner_available 的直写作用于缓存共享实例，
    下一次选源取到的仍是该实例（直写即全局生效）。"""
    p_runner = resolve_chat(db_session)
    assert p_runner.name == "deepseek"
    p_runner.reasoner_available = False  # 与 authors/pipeline.py 门禁直写同形态
    assert resolve("deepseek", db_session).reasoner_available is False
    assert resolve_chat(db_session) is p_runner


def test_model_is_part_of_cache_key(clean_resolve, db_session):
    p_default = resolve("deepseek", db_session)
    p_variant = resolve("deepseek", db_session, model="deepseek-v4-pro")
    assert p_variant is not p_default
    assert resolve("deepseek", db_session, model="deepseek-v4-pro") is p_variant


def test_cached_instance_follows_caller_session(clean_resolve, db_session):
    """缓存命中的实例把计量归属（db）刷新为当前调用方会话——
    跨测试/跨请求复用实例时不写向已关闭的旧会话。"""
    from app.db import SessionLocal
    p1 = resolve("deepseek", db_session)
    with SessionLocal() as other:
        p2 = resolve("deepseek", other)
        assert p2 is p1 and p2.db is other


def test_default_config_single_candidate_zero_change(clean_resolve, db_session):
    """默认配置：单候选 deepseek、冷却不启用——resolve_chat 恒 deepseek 不返回 None。"""
    assert cfg.LLM_CANDIDATES == [] and cfg.LLM_PROVIDER == "deepseek"
    assert resolve_chat(db_session).name == "deepseek"
    mark_cooldown("deepseek")  # TTL 缺省 0：结构就位、行为关闭
    assert cooldown_remaining("deepseek") == 0.0
    assert resolve_chat(db_session).name == "deepseek"


def test_candidates_ordered_first_wins(clean_resolve, db_session, monkeypatch):
    monkeypatch.setattr(cfg, "LLM_CANDIDATES", ["deepseek", "moark"])
    assert resolve_chat(db_session).name == "deepseek"


def test_first_candidate_cooldown_falls_to_second(clean_resolve, db_session, monkeypatch):
    monkeypatch.setattr(cfg, "LLM_CANDIDATES", ["deepseek", "moark"])
    mark_cooldown("deepseek", seconds=60)
    assert cooldown_remaining("deepseek") > 0
    p = resolve_chat(db_session)
    assert p.name == "moark" and p is resolve("moark", db_session)  # 次项同样进缓存


def test_cooldown_ttl_from_config_when_enabled(clean_resolve, db_session, monkeypatch):
    monkeypatch.setattr(cfg, "LLM_CANDIDATES", ["deepseek", "moark"])
    monkeypatch.setattr(cfg, "LLM_PROVIDER_COOLDOWN_SECONDS", 30)
    mark_cooldown("deepseek")
    assert 0 < cooldown_remaining("deepseek") <= 30
    assert resolve_chat(db_session).name == "moark"


def test_single_candidate_never_enters_cooldown(clean_resolve, db_session):
    """单候选永不冷却：无备源可切，冷却只会让 resolve 平白返回 None。"""
    mark_cooldown("deepseek", seconds=60)
    assert resolve_chat(db_session).name == "deepseek"


def test_all_candidates_cooling_returns_none(clean_resolve, db_session, monkeypatch):
    monkeypatch.setattr(cfg, "LLM_CANDIDATES", ["deepseek", "moark"])
    mark_cooldown("deepseek", seconds=60)
    mark_cooldown("moark", seconds=60)
    assert resolve_chat(db_session) is None


def test_consumer_degrades_to_slow_path_when_all_cooling(clean_resolve, db_session, monkeypatch):
    """全冷却返回 None → 消费方走既有降级链：检索层查询向量生成按未就绪处理
    （该方向本轮全量慢速，不抛出）。"""
    monkeypatch.setattr(cfg, "LLM_CANDIDATES", ["deepseek", "moark"])
    mark_cooldown("deepseek", seconds=60)
    mark_cooldown("moark", seconds=60)
    monkeypatch.setattr(cfg, "MOARK_EMBED_MODEL", "Qwen3-Embedding-0.6B")
    monkeypatch.setattr(cfg, "EMBED_PROVIDER", "moark")
    d = Direction(name="resolve-degrade", prompt="接纳高质量内容", prompt_version=1, threshold=60)
    db_session.add(d)
    db_session.commit()
    from app.retrieval.query import ensure_direction_query_vec
    assert ensure_direction_query_vec(db_session, d) is False


def test_embed_provider_none_disables_retrieval(db_session, monkeypatch):
    """EMBED_PROVIDER=none：检索层整体回退全量慢速（与既有嵌入模型禁用语义同轨）。"""
    from app.retrieval.embedder import default_provider, embed_enabled
    monkeypatch.setattr(cfg, "EMBED_PROVIDER", "none")
    assert embed_enabled() is False
    assert default_provider(db_session) is None


def test_embed_provider_defaults_to_moark(db_session):
    from app.embedding.moark import MoarkEmbeddingProvider
    from app.retrieval.embedder import default_provider
    p = default_provider(db_session)
    # registry 注册名 "moark"；实例计量名沿用既有 "moark_embed"（账面口径不变）
    assert isinstance(p, MoarkEmbeddingProvider) and p.name == "moark_embed"
