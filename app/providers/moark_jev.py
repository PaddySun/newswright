"""moark 平台 Jev 决策模型 /v1/systemone 协议适配器（V1 验证用）。

协议要点（项目文档（外层）jev-scoring-kit-20260928/jev-scoring-kit/docs/moark-systemone-protocol.md）：
- Jev 模型不走 chat/completions（400），只暴露 POST /v1/systemone。
- state 是唯一内容通道；questions 每个决策点一项，criteria key 即语义枚举值。
- 响应 answers[qid] = {probabilities, confidence, choice}；usage = {input_tokens, output_tokens, billing_units}。
- 客户端组装层必须做 answers 键完整性 + choice 枚举校验（协议文档 2.4 / 提示词文档 2.5）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import config
from .base import HTTPProvider, LLMProvider, ProviderError


class JevAdapterError(ProviderError):
    pass


class MoarkJevProvider(HTTPProvider):
    """systemone 决策协议适配器。"""

    name = "moark_jev"

    def __init__(self, db: Session) -> None:
        super().__init__(db, base_url=config.MOARK_BASE_URL, api_key=config.MOARK_API_KEY)
        self.default_model = config.MOARK_JEV_MODEL

    def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        resp = self._post_json("/v1/systemone", payload)
        body = resp.json()
        usage = body.get("usage") or {}
        meter = {
            "prompt_tokens": int(usage.get("input_tokens") or 0),
            "completion_tokens": int(usage.get("output_tokens") or 0),
            "billing_units": int(usage.get("billing_units") or 0),
        }
        return body, meter

    def decide(
        self,
        *,
        state: str,
        questions: dict[str, dict[str, Any]],
        call_point: str = "prefilter",
        ref_type: str | None = "item",
        ref_id: int | None = None,
        model: str | None = None,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """一次决策调用。返回：
        {
          "answers": {qid: {"choice", "confidence", "probabilities"}},
          "usage": {"input_tokens", "output_tokens", "billing_units"},
          "model": str,
        }
        answers 键完整性 / choice 枚举校验失败抛 JevAdapterError（不重试，属请求构造错误）。
        """
        model = model or self.default_model
        for qid, q in questions.items():
            if q.get("type") != "choice" or not q.get("criteria"):
                raise JevAdapterError(f"question {qid!r} 结构非法：type=choice 且 criteria 不能为空")
        payload = {"model": model, "state": state, "questions": questions}
        body = self._call(
            payload, call_point=call_point, ref_type=ref_type, ref_id=ref_id, max_retries=max_retries
        )
        if "error" in body:
            raise JevAdapterError(f"systemone 返回错误: {body['error']}")
        answers_raw = body.get("answers") or {}
        missing = set(questions) - set(answers_raw)
        if missing:
            raise JevAdapterError(f"answers 缺少 question: {sorted(missing)}")
        answers: dict[str, dict[str, Any]] = {}
        for qid, q in questions.items():
            a = answers_raw[qid]
            choice = a.get("choice")
            valid_keys = set(q["criteria"].keys())
            if choice not in valid_keys:
                raise JevAdapterError(f"question {qid!r} choice={choice!r} 不在 criteria 枚举 {sorted(valid_keys)}")
            answers[qid] = {
                "choice": choice,
                "confidence": float(a.get("confidence") or 0.0),
                "probabilities": a.get("probabilities") or {},
            }
        usage = body.get("usage") or {}
        return {
            "answers": answers,
            "usage": {
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "billing_units": int(usage.get("billing_units") or 0),
            },
            "model": body.get("model", model),
        }
