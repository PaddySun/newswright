"""jev 预筛两段式初筛段（BE-8/D3 打分成本）。

三路路由语义（路由本体在 runner.score_round，本模块只做单条判定）：
- 高置信 REJECT → 终态跳过 chat（省一次全价打分调用）；
- 高置信 KEEP → 照常 chat 打分（KEEP 需要分数）；
- 低置信（< site_config.jev_upgrade_confidence，任意 verdict）→ 显式 deepseek
  复核（升级质量语义，不走候选链）；
- 本函数返回 None = 初筛不可用（jev 冷却中/调用失败/协议异常）——score_round
  据此落 FAILED 下轮续跑，**绝不自动回退 chat**（moark 故障期全量回退成本反超
  +peers 联动下 chat 链已落 deepseek，防成本失控；冷却期满自然恢复）。

协议形态（moark systemone，经 providers 层 MoarkJevProvider.decide——计量/
冷却/账户联动全在位）：state=唯一内容通道（标题+正文截 SCORE_BODY_MAX_CHARS）；
单题 KEEP/REJECT 选择，criteria 键即 choice 枚举（decide 构造期校验面），
方向 prompt 主体进 instructions（判定标准）；options 给两选语义。usage 由
decide→_call→record_usage 自动落账（call_point=score_prefilter，ev7 先例形态）。
设计依据见 docs/design-index.md「SC-1」「SC-2」。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import config
from ..models import Direction, Item


def jev_prefilter(db: Session, item: Item, direction: Direction) -> dict | None:
    """单条 jev 初筛。返回 {"verdict": "KEEP"|"REJECT", "confidence": float,
    "reason": str, "model": str(服务端回显)}；不可用/失败返回 None（不抛）。"""
    from ..providers.resolve import cooldown_remaining, resolve

    try:
        # 冷却中（含自身 402 后的账户联动标记）→ 不可用，且不发起注定失败的调用
        if cooldown_remaining("moark_jev") > 0:
            return None
        provider = resolve("moark_jev", db)
        body = (item.content_text or "").strip()
        state = f"{item.title or ''}\n{body}".strip()[: config.SCORE_BODY_MAX_CHARS]
        answer = provider.decide(
            state=state,
            questions={"keep": {
                "type": "choice",
                "criteria": {"KEEP": 1, "REJECT": 0},
                "instructions": (
                    f"{direction.prompt}\n\n"
                    "依据上述方向标准判断该内容是否值得进入完整打分：与方向主题"
                    "相关、有信息量→KEEP；无关、重复、无实质内容→REJECT。"
                ),
                "options": {"KEEP": "相关，值得完整打分",
                            "REJECT": "不相关或不值得打分"},
            }},
            call_point="score_prefilter",
            ref_type="item",
            ref_id=item.id,
        )
        a = (answer.get("answers") or {}).get("keep") or {}
        choice = str(a.get("choice") or "").strip().upper()
        if choice not in ("KEEP", "REJECT"):
            return None
        return {
            "verdict": choice,
            "confidence": float(a.get("confidence") or 0.0),
            "reason": f"choice={choice}",
            "model": str(answer.get("model") or config.MOARK_JEV_MODEL),
        }
    except Exception:  # noqa: BLE001  初筛失败=不可用（None），绝不阻断打分轮
        return None
