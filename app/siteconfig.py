"""site_config 读写助手（G1/W1）：键带代码内默认值，缺失行不落库（读时回退）。

本里程碑仅两键（技术书 §4.1 site_config 预留全部未来键空间，公开 API 属 US-19 后续）：
- session_duration_days：会话保持期限（天），默认 7（AC-01.4）
- client_ip_header：真实客户端 IP 提取头名（ADR-5⑤），空 = 直连 request.client.host
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import SiteConfig

DEFAULTS: dict[str, object] = {
    "session_duration_days": 7,
    "client_ip_header": "",
}


def get_config(db: Session, key: str):
    """读配置：无行回退代码内默认值；键未知返回 None。"""
    row = db.get(SiteConfig, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key)


def set_config(db: Session, key: str, value) -> None:
    """写配置（upsert）。"""
    row = db.get(SiteConfig, key)
    if row is None:
        row = SiteConfig(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
