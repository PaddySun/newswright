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

兼容纪律：档位差异全部收拢在 tier_request 钩子——基类默认零改写（纯模型名档位），
其他 OpenAI 兼容 provider 不受影响；旧 DEEPSEEK_REASONER_MODEL 显式设置时按模型名
档位路由（向后兼容非官方网关）。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from .. import config
from .base import (
    FATAL_FINISH_REASONS,
    HTTPProvider,
    JSONParseError,
    ProviderError,
    RETRYABLE_FINISH_REASONS,
    parse_strict_json,
)

log = logging.getLogger("newswright.providers")


class DeepSeekProvider(HTTPProvider):
    name = "deepseek"

    def __init__(self, db: Session) -> None:
        super().__init__(
            db, base_url=config.DEEPSEEK_BASE_URL, api_key=config.DEEPSEEK_API_KEY
        )
        self._last_meter: dict[str, Any] = {}
        # None=未探测；False=思考档实测不可用（后续 reasoner 请求直接回退 chat）
        self.reasoner_available: bool | None = None
        self.last_usage: dict[str, Any] = {}

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

    def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        resp = self._post_json("/chat/completions", payload)
        body = resp.json()
        meter = self._meter_from_openai_usage(body.get("usage"))
        meter["finish_reason"] = self._finish_reason(body)
        self._last_meter = meter
        return body, meter

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        call_point: str,
        ref_type: str | None = None,
        ref_id: int | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        max_retries: int = 2,
        model_tier: str | None = None,
    ) -> tuple[str, str]:
        """返回 (content, model)。

        model_tier="reasoner" 走官方思考档；档位不可用（首探 4xx / 空正文截断）时
        记入 reasoner_available=False 并回退 chat 档，fallback_note 留因。
        finish_reason=length（截断）与 content_filter（过滤）如实抛错。
        """
        self.fallback_note: str | None = None
        requested_tier = model_tier
        effective_tier = model_tier
        if model_tier == "reasoner" and self.reasoner_available is False:
            effective_tier = None
            self.fallback_note = "reasoner 档此前实测不可用，回退 chat"

        def build(tier: str | None) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "model": model or config.DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": temperature,
            }
            if json_mode and tier != "reasoner":
                payload["response_format"] = {"type": "json_object"}
            # 官方 max_tokens 语义：思考档缺省 64K（不设），非思考档按调用方约束
            if max_tokens and tier != "reasoner":
                payload["max_tokens"] = max_tokens
            return self.tier_request(payload, model_tier=tier)

        def attempt(p: dict[str, Any]) -> dict[str, Any]:
            try:
                return self._call(p, call_point=call_point, ref_type=ref_type,
                                  ref_id=ref_id, max_retries=max_retries)
            except ProviderError as e:
                s = str(e)
                # 兼容阀：非官方网关可能不认识 thinking/reasoning_effort 参数（400/422）
                if ("thinking" in p or "reasoning_effort" in p) and ("400" in s or "422" in s):
                    stripped = {k: v for k, v in p.items()
                                if k not in ("thinking", "reasoning_effort")}
                    self.fallback_note = "网关不支持 thinking 参数，已剥离档位参数重发"
                    log.warning("%s: thinking 参数被拒，剥离后重发", call_point)
                    return self._call(stripped, call_point=call_point, ref_type=ref_type,
                                      ref_id=ref_id, max_retries=max_retries)
                raise

        payload = build(effective_tier)
        try:
            body = attempt(payload)
        except ProviderError as e:
            # 思考档首探失败（4xx 类不可重试）：标记不可用并回退 chat 重发一次
            if requested_tier == "reasoner" and self.reasoner_available is None:
                self.reasoner_available = False
                self.fallback_note = f"reasoner 档实测不可用，回退 chat: {str(e)[:200]}"
                log.warning("reasoner 档不可用，%s 回退 chat", call_point)
                payload = build(None)
                body = attempt(payload)
            else:
                raise
        self.last_usage = dict(self._last_meter)
        if requested_tier == "reasoner" and self.reasoner_available is None:
            self.reasoner_available = True

        finish_reason = self.last_usage.get("finish_reason")
        if finish_reason in FATAL_FINISH_REASONS:
            raise ProviderError(f"生成被过滤（finish_reason={finish_reason}），不可重试")
        # 服务端中断（官方 finish_reason）：content 为空时重试一次
        if finish_reason in RETRYABLE_FINISH_REASONS:
            body2 = attempt(payload)
            self.last_usage = dict(self._last_meter)
            body = body2
        try:
            message = body["choices"][0]["message"]
            content = message.get("content")
            actual_model = body.get("model", payload["model"])
        except (KeyError, IndexError, TypeError) as e:
            raise JSONParseError(f"chat 响应结构异常: {body!r:.200}") from e
        return content or "", actual_model

    def chat_json(self, messages: list[dict[str, str]], **kwargs: Any) -> tuple[dict[str, Any], str]:
        """strict JSON 便捷封装：返回 (解析后的 dict, model)。"""
        kwargs.setdefault("json_mode", True)
        content, model = self.chat(messages, **kwargs)
        return parse_strict_json(content), model
