"""DeepSeek（OpenAI 兼容 chat/completions）provider。

写作管线增量（M14）：① model_tier 按调用传模型档位（chat|reasoner），reasoner 档
实测不可用（HTTP 4xx）时记入 unavailable 后自动回退 chat 档；② last_usage 透出
最近一次调用的计量（管线逐节点 trace 的 token 归因用），usage_log 照常全量落库。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from .. import config
from .base import HTTPProvider, JSONParseError, ProviderError, parse_strict_json

log = logging.getLogger("newswright.providers")


class DeepSeekProvider(HTTPProvider):
    name = "deepseek"

    def __init__(self, db: Session) -> None:
        super().__init__(
            db, base_url=config.DEEPSEEK_BASE_URL, api_key=config.DEEPSEEK_API_KEY
        )
        self._last_meter: dict[str, int] = {}
        # None=未探测；False=实测不可用（后续 reasoner 请求直接回退 chat）
        self.reasoner_available: bool | None = None
        self.last_usage: dict[str, int] = {}

    def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        resp = self._post_json("/chat/completions", payload)
        body = resp.json()
        meter = self._meter_from_openai_usage(body.get("usage"))
        self._last_meter = meter
        return body, meter

    def _resolve_model(self, model: str | None, model_tier: str | None) -> str:
        if model_tier == "reasoner":
            if self.reasoner_available is False:
                return model or config.DEEPSEEK_MODEL
            return config.DEEPSEEK_REASONER_MODEL
        return model or config.DEEPSEEK_MODEL

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
        """返回 (content, model)。json_mode=True 时请求 strict JSON 输出。

        model_tier="reasoner" 时用 reasoner 档模型（response_format 不发给
        reasoner——其 JSON 输出靠 parse_strict_json 抢救）；档位不可用时回退
        chat 档并把原因写入 fallback_note。
        """
        self.fallback_note: str | None = None
        requested_tier = model_tier
        effective_tier = model_tier
        if model_tier == "reasoner" and self.reasoner_available is False:
            effective_tier = None
            self.fallback_note = "reasoner 档此前实测不可用，回退 chat"
        payload: dict[str, Any] = {
            "model": self._resolve_model(model, effective_tier),
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode and effective_tier != "reasoner":
            payload["response_format"] = {"type": "json_object"}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        try:
            body = self._call(
                payload,
                call_point=call_point,
                ref_type=ref_type,
                ref_id=ref_id,
                max_retries=max_retries,
            )
        except ProviderError as e:
            # reasoner 档首探失败（4xx 类不可重试错误）：标记不可用并回退 chat 重发一次
            if requested_tier == "reasoner" and self.reasoner_available is None:
                self.reasoner_available = False
                self.fallback_note = f"reasoner 档实测不可用，回退 chat: {str(e)[:200]}"
                log.warning("reasoner 档不可用，%s 回退 chat", call_point)
                payload["model"] = self._resolve_model(model, None)
                payload.pop("response_format", None)
                body = self._call(
                    payload,
                    call_point=call_point,
                    ref_type=ref_type,
                    ref_id=ref_id,
                    max_retries=max_retries,
                )
            else:
                raise
        self.last_usage = dict(self._last_meter)
        if requested_tier == "reasoner" and self.reasoner_available is None:
            self.reasoner_available = True
        try:
            content = body["choices"][0]["message"]["content"]
            actual_model = body.get("model", payload["model"])
        except (KeyError, IndexError, TypeError) as e:
            raise JSONParseError(f"chat 响应结构异常: {body!r:.200}") from e
        return content, actual_model

    def chat_json(self, messages: list[dict[str, str]], **kwargs: Any) -> tuple[dict[str, Any], str]:
        """strict JSON 便捷封装：返回 (解析后的 dict, model)。"""
        kwargs.setdefault("json_mode", True)
        content, model = self.chat(messages, **kwargs)
        return parse_strict_json(content), model
