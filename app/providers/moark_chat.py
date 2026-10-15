"""moark 平台 chat provider（OpenAI 兼容族，主备切换的备源位）。

平台事实（外部服务治理批统筹冒烟实测，2026-10-15）：
- chat 走 `/v1/chat/completions`（OpenAI 网关族路径前缀——与 deepseek 官方
  base 不带 /v1 是厂商差异，误用即触发网关 302 漏网形态）；
- 默认模型 deepseek-v4.1-flash：与官方 deepseek-flash 同族（跨厂商主备切换
  质量漂移最小的模型对；回显形如 deepseek-v4-1-flash-260910）；
- json_mode 兼容阀照 deepseek 判例：response_format 被拒（400）→ 剥离重发一次；
- 计量 model 以响应回显实况落账（OpenAIChatProvider._post 统一实现）；
- 平台有间歇性长挂起（45s+ 读超时）——定位为备源而非主源的实证依据。
设计依据见 docs/design-index.md「LR-5」「LR-6」。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import config
from .base import OpenAIChatProvider


class MoarkChatProvider(OpenAIChatProvider):
    name = "moark"
    # OpenAI 网关族路径前缀（厂商差异，见类 docstring）
    chat_completions_path = "/v1/chat/completions"
    # json_mode 兼容阀：网关不认 response_format（400）时剥离重发
    gateway_compat_params = ("response_format",)

    def __init__(self, db: Session, *, model: str | None = None) -> None:
        super().__init__(
            db, base_url=config.MOARK_BASE_URL, api_key=config.MOARK_API_KEY,
            model=model,
        )

    def _default_model(self) -> str:
        return self._model_override or config.MOARK_CHAT_MODEL
