"""方向打分：单次 LLM 调用（质量+相关+理由），strict JSON，绑定提示词版本。

纪律（任务书 §5.3 / 选型草稿）：
- 每条内容全链路只烧一次打分 LLM（score_round 跳过已有 OK 打分的条目）；
- 输出走 response_format json_object + 解析校验；解析失败同条重试 1 次，仍失败落 FAILED+原因；
- 正文截断 ≤4000 字符（config.SCORE_BODY_MAX_CHARS）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from .. import config
from ..models import Direction, Item, ScoreResult
from ..providers.base import JSONParseError, ProviderError, parse_strict_json
from ..providers.deepseek import DeepSeekProvider

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_BAND_RE = re.compile(r"^(high|mid|low)$")


def load_prompt_template(version: str) -> str:
    path = PROMPTS_DIR / f"score_{version}.md"
    return path.read_text(encoding="utf-8")


def _render_user_message(item: Item, direction: Direction) -> str:
    body = (item.content_text or "").strip()[: config.SCORE_BODY_MAX_CHARS]
    pub = item.published_at.strftime("%Y-%m-%d") if item.published_at else "未知"
    return (
        f"【方向】{direction.name}\n"
        f"【来源域名】{_host(item)}\n"
        f"【发布日期】{pub}\n"
        f"【标题】{item.title}\n"
        f"【正文】\n{body or '（无正文）'}"
    )


def _host(item: Item) -> str:
    try:
        from urllib.parse import urlparse

        return urlparse(item.url or "").netloc or "未知"
    except ValueError:
        return "未知"


def _validate(data: dict) -> dict:
    """字段完整性校验；不合规抛 JSONParseError（调用方计入解析失败）。"""
    try:
        quality = int(data["quality"])
        relevance = int(data["relevance"])
        band = str(data["band"]).strip().lower()
        reason = str(data["reason"]).strip()
    except (KeyError, TypeError, ValueError) as e:
        raise JSONParseError(f"打分字段缺失/非法: {e}; got={json.dumps(data, ensure_ascii=False)[:200]}") from e
    if not (0 <= quality <= 100 and 0 <= relevance <= 100):
        raise JSONParseError(f"分数越界 quality={quality} relevance={relevance}")
    if not _BAND_RE.match(band):
        raise JSONParseError(f"band 非法: {band!r}")
    if not reason:
        raise JSONParseError("reason 为空")
    return {"quality": quality, "relevance": relevance, "band": band, "reason": reason[:300]}


def score_item(db: Session, item: Item, direction: Direction, *, model: str | None = None) -> ScoreResult:
    """对单条内容打分一次（内含一次解析失败重试），返回落库的 ScoreResult。"""
    provider = DeepSeekProvider(db)
    template = load_prompt_template(direction.prompt_version)
    system = template.replace("{{direction_prompt}}", direction.prompt)
    user = _render_user_message(item, direction)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    result = ScoreResult(
        item_id=item.id,
        direction_id=direction.id,
        prompt_version=direction.prompt_version,
        model=model or config.DEEPSEEK_MODEL,
        status="FAILED",
    )
    last_error: str | None = None
    for attempt in range(2):  # 解析失败重试一次（同条内容）
        try:
            data, actual_model = provider.chat_json(
                messages,
                model=model,
                call_point="scoring",
                ref_type="item",
                ref_id=item.id,
                temperature=0.0,
            )
            validated = _validate(data)
            result.quality_score = validated["quality"]
            result.relevance_score = validated["relevance"]
            result.band = validated["band"]
            result.reason = validated["reason"]
            result.model = actual_model
            result.passed = validated["relevance"] >= direction.threshold
            result.status = "OK"
            result.error = None
            break
        except JSONParseError as e:
            last_error = str(e)
            # 第二次尝试时附加违规说明（任务书 §5.3：解析失败重试一次）
            messages = messages + [
                {"role": "assistant", "content": "（上次输出不合规）"},
                {"role": "user", "content": f"你上次的输出不合规：{e}。请严格只输出规定结构的 JSON 对象，重新打分。"},
            ]
        except ProviderError as e:
            # 网络层重试已在 provider 层耗尽：内容不丢，落 FAILED 终态
            last_error = f"ProviderError: {e}"
            break
        # ProviderError（网络/调用耗尽）不重试——已由 provider 层重试过，直接落 FAILED

    if result.status != "OK":
        result.error = last_error
    db.add(result)
    db.commit()
    return result
