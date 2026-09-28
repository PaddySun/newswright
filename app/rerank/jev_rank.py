"""Jev 决策协议排序（systemone 协议族：moark / bocha 两套配置复用同一代码路径）。

criteria=方向提示词（照 JEV 提示词文档的 criteria 思维：band 三问 + confidence 路由）。
调用走 provider 层计量（call_point=rank_jev，usage_log 归因）+ rank_call_log + 额度闸。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import config
from .base import HTTPRankProvider, RankError


class MoarkJevRankProvider(HTTPRankProvider):
    name = "moark_jev"

    def __init__(self, db: Session) -> None:
        super().__init__(db, base_url=config.MOARK_BASE_URL,
                         api_key=config.MOARK_API_KEY, model=config.MOARK_JEV_MODEL)


class BochaJevRankProvider(HTTPRankProvider):
    name = "bocha_jev"

    def __init__(self, db: Session, *, api_key: str | None = None) -> None:
        api_key = api_key or config.BOCHA_API_KEY
        if not api_key:
            raise RankError("bocha_jev 缺少 API Key（.env bochaaiAPIKey）")
        super().__init__(db, base_url=config.BOCHA_JEV_BASE_URL,
                         api_key=api_key, model=config.BOCHA_JEV_MODEL)
