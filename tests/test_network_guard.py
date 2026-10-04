"""测试环境出网封禁（结构性防范）：conftest 的 autouse 夹具把 httpx 的真实网络
传输层替换为直接抛 AssertionError 的哨兵。本文件验证封禁本体：

- 未打桩的 LLM/嵌入 provider 调用必须当场炸掉（AssertionError），绝不发出真实请求；
- 打桩测试不受影响（替换 Client 类、实例级替换 _post/_post_json 均绕开真实传输层）。

背景：C1-7 联网事故——一处 provider 未打桩导致真实 API 调用一次；结构性封禁
把"每条测试自觉打桩"升级为"漏打桩即红"。
"""
import pytest

from app.providers.deepseek import DeepSeekProvider


def test_unstubbed_llm_provider_blocked_not_silent(db_session):
    """LLM provider 未打桩：调用链触达真实传输层 → AssertionError（含目标 URL），
    且不被重试/计量层吞掉转成 ProviderError。"""
    p = DeepSeekProvider(db_session)
    with pytest.raises(AssertionError, match="出网封禁"):
        p.chat_json([{"role": "user", "content": "hi"}], call_point="scoring")


def test_unstubbed_embedding_provider_blocked_not_silent(db_session):
    """嵌入 provider 未打桩：同样在传输层被哨兵拦截。"""
    from app.embedding.moark import MoarkEmbeddingProvider

    p = MoarkEmbeddingProvider(db_session)
    with pytest.raises(AssertionError, match="出网封禁"):
        p.embed(["一段文本"])
