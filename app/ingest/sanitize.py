"""零信任过滤预留位（任务书 §4：本阶段只做骨架 + 统计，不做过滤本体）。

威胁模型（正式系统二期实现依据，写入此处作为设计锚点）：
RSS/网页/搜索结果均为不可信输入——
  1. 提示词注入：内容中藏「忽略之前指令…」「输出 API Key」等指令性文本；
  2. HTML/JS payload：script/iframe/事件属性（trafilatura 抽取侧已部分剥离
     HTML 标签，但纯文本层仍可能残留注入性语句——现状如实记录，不夸大）；
  3. 超长内容炸弹：单条或整轮超预算内容拖垮模型调用；
  4. 恶意链接：SSRF 目标、钓鱼链接、跟踪跳转；
  5. 编码混淆：零宽字符、同形字、转义层叠。
二期实现建议：长度与编码归一化 → 注入特征检测（规则+模型）→ HTML 剥离复核 →
链接安全复检（SSRF）→ 按源/方向配置白名单。每一步都应实现为 SanitizeStage，
统计口径（阶段×原因）保持不变。

管线纪律：所有 item 落库前必须流经 sanitize 阶段（哪怕 pass-through）。
fetch_status 与 sanitize_status 语义分离：抓取成功但被过滤 ≠ 抓取失败；
REJECTED 的 item 全文照存。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .. import config


@dataclass
class SanitizeResult:
    passed: bool
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class SanitizeTarget:
    """落库前的内容快照（不依赖 ORM 对象，便于搜索/网页等新通道复用）。"""
    title: str = ""
    content_text: str = ""
    url: str = ""


class SanitizeStage(ABC):
    """过滤阶段接口：check 返回 PASSED 或首个 REJECTED 结果。"""

    name: str = "sanitize"

    @abstractmethod
    def check(self, target: SanitizeTarget) -> SanitizeResult: ...


class DemoPassThroughSanitizer(SanitizeStage):
    """默认实现：一律放行。SANITIZE_ENABLED=false 或链为空时使用。"""

    name = "passthrough"

    def check(self, target: SanitizeTarget) -> SanitizeResult:
        return SanitizeResult(passed=True, reason="demo:零信任过滤未启用")


class KeywordDenySanitizer(SanitizeStage):
    """演示性实现（仅供单测与统计链路验证，不默认启用）：
    标题或正文命中关键词即拒。不是真实过滤能力，勿当安全边界。"""

    name = "keyword_deny"

    def __init__(self, keywords: list[str]) -> None:
        self.keywords = [k for k in (keywords or []) if k]

    def check(self, target: SanitizeTarget) -> SanitizeResult:
        joined = f"{target.title}\n{target.content_text}"
        for kw in self.keywords:
            if kw in joined:
                return SanitizeResult(
                    passed=False,
                    reason=f"keyword_deny:{kw}",
                    detail={"matched_in": "title" if kw in target.title else "content"},
                )
        return SanitizeResult(passed=True)


def build_chain() -> list[SanitizeStage]:
    """按配置组装 sanitizer 链。关闭或配置为空 → pass-through 一项。"""
    if not config.SANITIZE_ENABLED:
        return [DemoPassThroughSanitizer()]
    chain: list[SanitizeStage] = []
    if config.SANITIZE_DENY_KEYWORDS:
        chain.append(KeywordDenySanitizer(config.SANITIZE_DENY_KEYWORDS))
    if not chain:
        # 开关开了但没配任何实现：保持放行并如实标注，防止静默假装已过滤
        return [DemoPassThroughSanitizer()]
    return chain


def run_sanitize(target: SanitizeTarget) -> SanitizeResult:
    """落库前强制调用。逐阶段执行，首个 REJECT 即返回（全量保存原则由调用方保证）。"""
    chain = build_chain()
    last_pass = SanitizeResult(passed=True, reason="demo:零信任过滤未启用")
    for stage in chain:
        result = stage.check(target)
        if not result.passed:
            result.detail = {"stage": stage.name, **result.detail}
            return result
        last_pass = result
    return last_pass
