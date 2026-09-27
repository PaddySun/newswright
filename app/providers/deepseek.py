"""DeepSeek（OpenAI 兼容 chat/completions）provider。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import config
from .base import HTTPProvider, JSONParseError, LLMProvider, parse_strict_json


class DeepSeekProvider(HTTPProvider):
    name = "deepseek"

    def __init__(self, db: Session) -> None:
        super().__init__(
            db, base_url=config.DEEPSEEK_BASE_URL, api_key=config.DEEPSEEK_API_KEY
        )

    def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        resp = self._post_json("/chat/completions", payload)
        body = resp.json()
        return body, self._meter_from_openai_usage(body.get("usage"))

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
    ) -> tuple[str, str]:
        """返回 (content, model)。json_mode=True 时请求 strict JSON 输出。"""
        payload: dict[str, Any] = {
            "model": model or config.DEEPSEEK_MODEL,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        body = self._call(
            payload,
            call_point=call_point,
            ref_type=ref_type,
            ref_id=ref_id,
            max_retries=max_retries,
        )
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
