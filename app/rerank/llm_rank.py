"""LLM 批量相关性排序（deepseek 一次调用，strict JSON，temperature=0）。

口径：模型直接输出 0-100 分 + 三档 band；排序场景理由不入库（如实声明：reason
仅用于模型自检，不落库）。调用走 provider 层计量（call_point=rank_llm）+ rank_call_log。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .base import RankCandidate, RankError, RankProvider, RankedResult


class LLMRankProvider(RankProvider):
    name = "llm"

    def _rank(self, criteria: str, candidates: list[RankCandidate]) -> list[RankedResult]:
        from ..providers.base import JSONParseError, parse_strict_json
        from ..providers.deepseek import DeepSeekProvider

        provider = DeepSeekProvider(self.db)
        items = "\n".join(f"{{\"id\": \"{c.id}\", \"text\": {c.text!r}}}" for c in candidates)
        system = (
            "你是相关性排序器。给定方向标准与一批候选内容，为每条候选输出与方向的相关分。\n"
            "只输出 JSON 对象：{\"results\": [{\"id\": str, \"score\": 0-100 整数, "
            "\"band\": \"high\"|\"mid\"|\"low\"}]}，必须覆盖全部候选 id。"
            "不要输出 JSON 以外的任何内容。"
        )
        user = f"【方向标准】\n{criteria}\n\n【候选】\n[{items}]"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            data, model = provider.chat_json(messages, call_point="rank_llm", temperature=0.0)
        except JSONParseError as e:
            raise RankError(f"rank_llm 解析失败: {e}") from e
        results_raw = data.get("results")
        if not isinstance(results_raw, list):
            raise RankError("rank_llm 响应缺 results")
        band_map = {}
        score_map = {}
        for r in results_raw:
            if isinstance(r, dict) and "id" in r:
                band_map[str(r["id"])] = str(r.get("band") or "low")
                score_map[str(r["id"])] = float(r.get("score") or 0)
        out: list[RankedResult] = []
        for c in candidates:
            if str(c.id) not in score_map:
                continue
            score = max(0.0, min(100.0, score_map[str(c.id)]))
            band = band_map.get(str(c.id), "")
            if band not in ("high", "mid", "low"):
                band = "high" if score >= 75 else ("mid" if score >= 25 else "low")
            out.append(RankedResult(id=c.id, score=score, band=band, confidence=None,
                                    provider=self.name))
        return out
