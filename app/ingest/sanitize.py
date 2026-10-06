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


# 注入特征规则集（版本化常量）：指令性模式的中英规则清单。规则取向=只认
# "指令性模式"（要求改变模型行为/泄露凭据的话术结构），不认裸关键词出现——
# 正常报道里出现"API Key"一词不是注入，"输出你的 API Key"才是。
# 每条规则带稳定 id（sanitize_reason 引用该 id，统计按 id 聚合）；清单演进
# 必须升版本号。
INJECTION_PATTERN_RULES: list[dict] = [
    {"id": "ignore_previous_instructions_zh",
     "pattern": r"忽略(之前|以上|前面|先前|上面)(的)?(所有|全部)?(指令|提示|要求|规则)"},
    {"id": "ignore_previous_instructions_en",
     "pattern": r"(?i)(disregard|ignore|forget)\s+(all\s+)?(previous|prior|above|earlier)\s+"
                r"(instructions?|prompts?|rules?|directions?)"},
    {"id": "reveal_credentials",
     "pattern": r"(?i)(输出|泄露|打印|透露|reveal|output|print|leak|show)\s*.{0,24}"
                r"(api[\s_-]?key|secret|密钥|凭据|credentials?|password|token)"},
    {"id": "developer_mode_override",
     "pattern": r"(?i)(进入|启用|开启).{0,10}(开发者模式|developer\s+mode|dan\s+mode)"
                r"|jailbreak|越狱模式"},
    {"id": "system_prompt_extraction",
     "pattern": r"(?i)(输出|泄露|复述|打印|reveal|output|repeat|print).{0,16}"
                r"(系统提示词|系统指令|system\s*prompt)"},
]
INJECTION_RULES_VERSION = 1


class InjectionPatternSanitizer(SanitizeStage):
    """注入特征检测（规则特征集形态，sanitize 阶段清单第一项）：标题或正文命中
    任一指令性模式即拒。命中≠抓取失败——fetch_status 不动、全文照存、不进打分，
    与其他 sanitize 拒绝同一语义分离。模型检测形态不在本阶段（勿当完备防线）。"""

    name = "injection_pattern"

    def check(self, target: SanitizeTarget) -> SanitizeResult:
        import re

        joined = f"{target.title}\n{target.content_text}"
        for rule in INJECTION_PATTERN_RULES:
            if re.search(rule["pattern"], joined):
                return SanitizeResult(
                    passed=False,
                    reason=f"injection_pattern:{rule['id']}",
                    detail={"rule_id": rule["id"], "rules_version": INJECTION_RULES_VERSION},
                )
        return SanitizeResult(passed=True)


def build_chain() -> list[SanitizeStage]:
    """按配置组装 sanitizer 链。关闭或配置为空 → pass-through 一项。

    注入特征检测为阶段清单第一项（先于关键词拒绝执行——注入是攻击面，
    优先级高于内容治理）。"""
    if not config.SANITIZE_ENABLED:
        return [DemoPassThroughSanitizer()]
    chain: list[SanitizeStage] = [InjectionPatternSanitizer()]
    if config.SANITIZE_DENY_KEYWORDS:
        chain.append(KeywordDenySanitizer(config.SANITIZE_DENY_KEYWORDS))
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
