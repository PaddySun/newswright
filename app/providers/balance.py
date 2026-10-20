"""余额主动探测（BE-7/PV-3）：chat 域两供应商每日一查+落账+阈值告警。

别等调用失败才发现欠费（morningdeck 事故根因①的主动面）——402 冷却切换
只兜住失败时刻，余额探测在耗尽前主动发现。口径（外部 API 文档，统筹亲读）：
- DeepSeek ``GET {DEEPSEEK_BASE_URL}/user/balance``（Bearer）→ balance_infos
  取 CNY 记录的 total_balance（string→float）；无 CNY 记录取首条并注记币种；
- moark ``GET {MOARK_BASE_URL}/v1/tokens/packages/balance``（同 key）→
  balance（number，资源包人民币元口径）。

纪律：出网走 get_json 池化面（headers 注入 Bearer，密钥不落日志）；探测自身
失败（网络/5xx/解析）落 error 不告警（次日再试）；落账 site_config
balance_last_{name}（JSON：amount/currency/probed_at/ok/error）——
/api/providers/status 读此呈现。宿主=scheduler._tick_backup 第四段（每日轮）。
设计依据见 docs/design-index.md「PV-3」。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from .. import config
from ..notify.triggers import notify_balance_low
from ..siteconfig import get_config, set_config
from ..transport.errors import ProviderError
from ..transport.http import _scrub, get_json

log = logging.getLogger("newswright.providers")

PROBE_TIMEOUT_S = 15.0


def _parse_deepseek(body: dict[str, Any]) -> tuple[float, str]:
    """DeepSeek 余额体解析：CNY 记录优先；无 CNY 取首条并注记实际币种。"""
    infos = body.get("balance_infos") or []
    if not infos:
        raise ValueError("balance_infos 为空")
    entry = next((i for i in infos
                  if str(i.get("currency", "")).upper() == "CNY"), None)
    if entry is None:
        entry = infos[0]
        log.info("DeepSeek 余额无 CNY 记录，按 %s 币种记账", entry.get("currency"))
    amount = float(str(entry.get("total_balance", "0")))
    return amount, str(entry.get("currency") or "CNY")


def _parse_moark(body: dict[str, Any]) -> tuple[float, str]:
    """moark 资源包余额解析：balance 为 number（人民币元口径——与
    balance_warn_threshold 阈值同口径）。"""
    return float(body.get("balance") or 0.0), "CNY"


def _probes() -> dict[str, dict[str, Any]]:
    """两家探测面（chat 域注册名 → URL/密钥/解析器）。"""
    return {
        "deepseek": {"url": f"{config.DEEPSEEK_BASE_URL}/user/balance",
                     "key": config.DEEPSEEK_API_KEY, "parse": _parse_deepseek},
        "moark": {"url": f"{config.MOARK_BASE_URL}/v1/tokens/packages/balance",
                  "key": config.MOARK_API_KEY, "parse": _parse_moark},
    }


def probe_all(db: Session, *, client_factory: Callable | None = None) -> dict[str, dict]:
    """两家各查各落账（一家失败不拖另一家）：每家返回并持久化
    balance_last_{name} 记录；amount < balance_warn_threshold（缺省 ¥5）→
    notify_balance_low 恰一次（24h 去重在 hub 层）。"""
    return {name: _probe_one(db, name, spec, client_factory=client_factory)
            for name, spec in _probes().items()}


def _probe_one(db: Session, name: str, spec: dict[str, Any],
               *, client_factory: Callable | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "amount": None, "currency": None,
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "ok": False, "error": None,
    }
    try:
        resp = get_json(
            spec["url"],
            headers={"Authorization": f"Bearer {spec['key']}"},
            timeout=PROBE_TIMEOUT_S, db=db, client_factory=client_factory)
        amount, currency = spec["parse"](resp.json())
        record.update(ok=True, amount=amount, currency=currency)
    except (ProviderError, ValueError, KeyError, TypeError) as e:
        # 探测自身失败（网络/5xx/解析）落 error 不告警——次日再试
        record["error"] = _scrub(f"{type(e).__name__}: {e}")[:300]
        log.warning("余额探测失败（%s，次日再试）: %s", name, type(e).__name__)
    set_config(db, f"balance_last_{name}", record)
    if record["ok"]:
        threshold = float(get_config(db, "balance_warn_threshold") or 5)
        if record["amount"] < threshold:
            notify_balance_low(db, name=name, amount=record["amount"],
                               threshold=threshold)
    return record
