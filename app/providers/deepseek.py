"""DeepSeek（OpenAI 兼容 chat/completions）provider——按官方 API 文档深度适配（2026-10 版）。

官方口径要点（项目文档（外层）API文档/DS-LLM官方API文档/Chat Completions API.txt）：
- 模型 ID 只有 deepseek-flash | deepseek-v4-pro（deepseek-chat 为兼容别名）；
  **思考模式由 `thinking`/`reasoning_effort` 参数控制，不再用模型名**（deepseek-reasoner
  为旧口径——此前"reasoner 请求实报 flash"的漂移即源于此）。
- max_tokens：1-393216；未设置时非思考默认 8K、思考默认 64K——思考档不再硬设上限。
- usage 细节：prompt_cache_hit_tokens（缓存命中）与 completion_tokens_details.reasoning_tokens
  （思维链）逐调用计量入 usage_log（cache_hit_tokens/reasoning_tokens 列）。
- finish_reason：length=截断、content_filter=被过滤（不可重试）、
  insufficient_system_resource/aborted=服务端中断（可重试）。
- 错误码：402 余额不足/401 认证/400·422 参数——不可重试并给出明确信息。
- temperature 仅非思考模式生效、top_p 仅思考模式生效；JSON 模式须同时指示模型输出 JSON。

chat/chat_json 模板已下沉 LLMProvider 基类；本类退化为「配置 + thinking 档钩子
+ 网关兼容阀声明」。兼容纪律：档位差异全部收拢在 tier_request 钩子——基类默认
零改写（纯模型名档位），其他 OpenAI 兼容 provider 不受影响；旧
DEEPSEEK_REASONER_MODEL 显式设置时按模型名档位路由（向后兼容非官方网关）。
设计依据见 docs/design-index.md「LR-1」。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import config
from .base import OpenAIChatProvider


class DeepSeekProvider(OpenAIChatProvider):
    name = "deepseek"
    # 网关兼容阀：非官方网关可能不认 thinking/reasoning_effort（400/422）→ 剥离重发一次
    gateway_compat_params = ("thinking", "reasoning_effort")

    def __init__(self, db: Session, *, model: str | None = None) -> None:
        super().__init__(
            db, base_url=config.DEEPSEEK_BASE_URL, api_key=config.DEEPSEEK_API_KEY,
            model=model,
        )

    def _default_model(self) -> str:
        return self._model_override or config.DEEPSEEK_MODEL

    # ---------------- 档位（官方 thinking 参数化） ----------------

    def _thinking_by_model_name(self) -> bool:
        """旧口径兼容开关：DEEPSEEK_TIER_MODE=model_name 时 reasoner 档按模型名路由
        （仅非官方网关不认 thinking 参数且必须换模型名时使用）。"""
        return config.DEEPSEEK_TIER_MODE == "model_name"

    def tier_request(self, payload: dict[str, Any], *, model_tier: str | None) -> dict[str, Any]:
        """档位 → 请求参数（官方规则）：
        - chat 档：thinking disabled（temperature 生效、JSON mode 语义稳定、成本最低）；
        - reasoner 档：thinking enabled + reasoning_effort；max_tokens 缺省（官方思考
          默认 64K，不硬设截断上限）；旧口径兼容时改为模型名路由。"""
        payload = dict(payload)
        if model_tier == "reasoner":
            if self._thinking_by_model_name():
                payload["model"] = config.DEEPSEEK_REASONER_MODEL
            else:
                payload["model"] = config.DEEPSEEK_THINKING_MODEL
                payload["thinking"] = {"type": "enabled"}
                if config.DEEPSEEK_REASONING_EFFORT:
                    payload["reasoning_effort"] = config.DEEPSEEK_REASONING_EFFORT
            payload.pop("response_format", None)  # 思考档不吃 JSON mode，靠 parse_strict_json
        else:
            payload["thinking"] = {"type": "disabled"}
        return payload
