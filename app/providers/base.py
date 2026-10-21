"""LLM provider 抽象 + 计量/重试/usage_log 包装。

纪律（选型草稿 §3.2.3）：
- 所有 LLM 调用统一经此层，每次调用落一条 usage_log（调用点/模型/token/延迟/成败/归属）。
- 网络失败重试最多 2 次（退避经传输脊协商：Retry-After 优先、随机化指数退避），
  耗尽抛 RetryExhausted（继承 ProviderError）由上层进 FAILED 终态。
- 日志与报错绝不携带 Key。

传输横切面（错误分类学/_scrub/计量/HTTP 出口/重试协商）已上提至 app/transport/
（传输脊中立化批）；本模块保留 LLM 域语义（chat/chat_json 模板、_call 重试
包装、strict JSON 解析、OpenAI usage 计量映射、thinking 档位钩子、网关兼容
阀钩子），并 re-export 兼容名（既有 import 面零改动）。

chat/chat_json 自 DeepSeekProvider 下沉至 LLMProvider 基类：档位差异经
tier_request 钩子注入（默认零改写），网关兼容阀经 _compat_resend_payload
钩子注入（默认不触发），观测面属性（last_usage / fallback_note /
reasoner_available）初始化在基类——authors 管线直读直写这些属性，选源层
缓存共享实例后直写即跨调用生效。
设计依据见 docs/design-index.md「TR-1」「TR-3」「TR-4」「TR-5」「LR-1」「ADR-8」。
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..transport.errors import (
    REASON_ERROR_NOT_RETRYABLE,
    REASON_MAX_RETRIES_EXCEEDED,
    ProviderError,
    RetryExhausted,
    VendorFatalError,
)
from ..transport.http import (
    RETRYABLE_STATUS,
    FATAL_STATUS_MESSAGE,
    _scrub,
    post_json,
    retry_delay_ms,
)
from ..transport.metering import record_usage
from ..transport import retry_budget

__all__ = [
    "FATAL_STATUS_MESSAGE",
    "HTTPProvider",
    "JSONParseError",
    "LLMProvider",
    "OpenAIChatProvider",
    "ProviderError",
    "RETRYABLE_STATUS",
    "RetryExhausted",
    "_scrub",
    "error_status",
    "mark_vendor_cooldown",
    "parse_strict_json",
    "record_usage",
]

log = logging.getLogger("newswright.providers")

# finish_reason 官方语义：length=截断（max_tokens/上下文）、content_filter=被过滤
# （不可重试）、insufficient_system_resource/aborted=服务端中断（可重试）、stop/tool_calls 正常
RETRYABLE_FINISH_REASONS = {"insufficient_system_resource", "aborted"}
FATAL_FINISH_REASONS = {"content_filter"}

# 网关兼容阀触发状态域：参数被网关拒绝（400/422）才值得剥离重发，其余状态码
# 与参数无关（如 402 余额），剥离重发只会多烧一次注定失败的调用
COMPAT_VALVE_STATUS = (400, 422)


class JSONParseError(Exception):
    """LLM 返回内容无法解析为合法 JSON / 字段缺失。"""


def _error_is_retryable(e: BaseException) -> bool:
    """传输脊 typed 错误按结构化字段判定；httpx 网络异常一律可重试；
    朴素异常按类属性兜底（兼容既有鸭子属性形态）。"""
    if isinstance(e, httpx.HTTPError):
        return True
    return bool(getattr(e, "retryable", False))


def error_status(err: BaseException) -> int | None:
    """从异常（或其重试尝试链）提取 HTTP 状态码——兼容阀等状态判定统一走
    结构化字段，不嗅探异常文案。RetryExhausted 自尝试链末位回溯首个带
    状态码的错误。"""
    status = getattr(err, "status", None)
    if status is not None:
        return status
    if isinstance(err, RetryExhausted):
        for sub in reversed(err.errors):
            status = getattr(sub, "status", None)
            if status is not None:
                return status
    return None


def mark_vendor_cooldown(err: VendorFatalError, *, name: str, db: Session,
                         peers: tuple[str, ...] = ()) -> None:
    """供应商级致命 → 冷却标记 + 边沿通知（BE-7/TR-2 接线；BE-8 提为模块级，
    供非 chat 调用路径与账户联动复用）。

    - 冷却键必须 (name, None)——选源层查询键就是 (name, None)（resolve.py
      resolve_chat），按 payload 模型名标记即键不匹配、冷却静默失效；
    - peers=账户联动域（BE-8：moark_jev 与 moark chat 同 key 同账户独立余额，
      jev 遭 402 时 chat 主源也该冷却）：一并标记；边沿判定取并集——「任一
      未冷却 → 全冷却」转换为一次进入冷却，通知恰一次且以主名（name）发；
    - 通知边沿触发：仅在「未冷却 → 冷却」转换时发一次（打分轮逐条 402
      不灌爆通知）；TTL 配置 0 时 mark 为 no-op（冷却未发生则不发）；
    - 函数内延迟 import 破环：providers.base→resolve→registry→
      providers.deepseek→base（robots 判例同款惰性导入）；
    - 治理面异常绝不改变调用错误语义（WARN 吞出，原错误照常上抛）。
    """
    try:
        from .. import config as _config
        from ..providers import resolve as _resolve
        from ..notify.triggers import notify_provider_switched

        names = (name, *peers)
        was_cooling = any(_resolve.cooldown_remaining(n) > 0 for n in names)
        for n in names:
            _resolve.mark_cooldown(n)  # 不传 model——键=(n, None)
        if not was_cooling and _resolve.cooldown_remaining(name) > 0:
            notify_provider_switched(
                db, name=name, status=err.status,
                ttl_seconds=_config.LLM_PROVIDER_COOLDOWN_SECONDS)
    except Exception:  # noqa: BLE001  治理面异常不改变调用错误语义
        log.warning("供应商冷却接线异常（不影响原错误上抛）: %s",
                    type(err).__name__, exc_info=True)


class LLMProvider(ABC):
    """同步 provider。子类实现 _post 与 _default_model；基类负责
    chat/chat_json 模板、重试与计量、档位钩子与兼容阀钩子、观测面属性。"""

    name: str = "base"
    # 供应商级致命冷却的账户联动域（BE-8）：空=单键（基类缺省）；
    # moark_jev 覆写为 ("moark",)——同 key 同账户，jev 遭 402 时 chat 主源同冷却
    COOLDOWN_PEERS: tuple[str, ...] = ()

    def __init__(self, db: Session) -> None:
        self.db = db
        self._last_meter: dict[str, Any] = {}
        # 观测面（authors/pipeline 直读直写；经选源层缓存共享后跨调用存活）
        self.reasoner_available: bool | None = None  # None=未探测；False=实测不可用
        self.last_usage: dict[str, Any] = {}
        self.fallback_note: str | None = None

    @abstractmethod
    def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """发一次请求，返回 (响应体, 计量信息)。计量信息含
        prompt_tokens / completion_tokens / billing_units，可选
        cache_hit_tokens / reasoning_tokens / finish_reason / item_count / model
        （model=服务端回显实况，优先于请求名落账）。
        抛 httpx/ProviderError。"""

    def _default_model(self) -> str:
        """chat 档缺省模型（子类按自身配置覆写；未覆写视为无缺省）。"""
        raise NotImplementedError(f"{type(self).__name__} 未实现 _default_model")

    def _cooldown_and_notify(self, err: VendorFatalError) -> None:
        """供应商级致命接线（方法壳，BE-7 调用点零变）：转发模块级
        mark_vendor_cooldown，peers 取类属性 COOLDOWN_PEERS（BE-8 账户联动）。"""
        mark_vendor_cooldown(err, name=self.name, db=self.db,
                             peers=tuple(getattr(self, "COOLDOWN_PEERS", ()) or ()))

    def tier_request(self, payload: dict[str, Any], *, model_tier: str | None) -> dict[str, Any]:
        """按调用档位改写请求 payload 的 provider 钩子（默认不改写——纯模型名档位，
        任何 OpenAI 兼容 provider 零改动兼容；DeepSeek 覆盖为官方 thinking 参数）。"""
        return payload

    def _compat_resend_payload(self, payload: dict[str, Any],
                               err: ProviderError) -> dict[str, Any] | None:
        """网关兼容阀钩子：网关拒绝某请求参数（按 err 状态码判定，非文案嗅探）
        时返回剥离该参数后的 payload 供重发一次；不适用返回 None（默认不触发）。"""
        return None

    def _call(
        self,
        payload: dict[str, Any],
        *,
        call_point: str,
        ref_type: str | None = None,
        ref_id: int | None = None,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """重试 + 计量包装，返回完整响应体。失败退避经传输脊协商（Retry-After
        优先夹逼 / 随机化指数退避），耗尽抛 RetryExhausted（reason 两态+尝试链）。
        计量 model 口径：服务端回显实况（meter.model）优先，请求名兜底。"""
        attempt = 0
        last_err: Exception | None = None
        attempt_errors: list[Exception] = []
        budget_exhausted = False
        while attempt <= max_retries:
            t0 = time.monotonic()
            try:
                body, meter = self._post(payload)
                latency_ms = int((time.monotonic() - t0) * 1000)
                record_usage(
                    self.db,
                    provider=self.name,
                    model=meter.get("model") or payload.get("model", ""),
                    call_point=call_point,
                    prompt_tokens=meter.get("prompt_tokens", 0),
                    completion_tokens=meter.get("completion_tokens", 0),
                    billing_units=meter.get("billing_units", 0),
                    cache_hit_tokens=meter.get("cache_hit_tokens", 0),
                    reasoning_tokens=meter.get("reasoning_tokens", 0),
                    finish_reason=meter.get("finish_reason"),
                    item_count=meter.get("item_count"),
                    latency_ms=latency_ms,
                    ok=True,
                    ref_type=ref_type,
                    ref_id=ref_id,
                )
                return body
            except JSONParseError:
                # 解析失败不是网络问题，不在此层重试（任务书：解析失败由业务层重试一次）
                raise
            except (httpx.HTTPError, ProviderError) as e:
                latency_ms = int((time.monotonic() - t0) * 1000)
                last_err = e
                attempt_errors.append(e)
                retryable = _error_is_retryable(e)
                record_usage(
                    self.db,
                    provider=self.name,
                    model=payload.get("model", ""),
                    call_point=call_point,
                    latency_ms=latency_ms,
                    ok=False,
                    error=f"{type(e).__name__}: {e}",
                    ref_type=ref_type,
                    ref_id=ref_id,
                )
                if isinstance(e, VendorFatalError):
                    self._cooldown_and_notify(e)
                if not retryable or attempt == max_retries:
                    break
                if not retry_budget.spend("llm", db=self.db):
                    log.warning("重试预算耗尽（caller=llm，60s 滑窗超限）：本次失败按不可重试快速失败")
                    budget_exhausted = True
                    break
                delay = retry_delay_ms(e, attempt) / 1000.0
                log.warning("provider 调用失败（第 %d 次，%.1fs 后重试）: %s", attempt + 1, delay, e)
                time.sleep(delay)
                attempt += 1
        reason = (REASON_MAX_RETRIES_EXCEEDED if _error_is_retryable(last_err)
                  and not budget_exhausted
                  else REASON_ERROR_NOT_RETRYABLE)
        raise RetryExhausted(
            f"{self.name} 调用失败（重试 {attempt} 次后放弃）: {last_err}",
            reason=reason, errors=attempt_errors,
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        call_point: str,
        ref_type: str | None = None,
        ref_id: int | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        max_retries: int = 2,
        model_tier: str | None = None,
    ) -> tuple[str, str]:
        """一次 chat 调用，返回 (content, model)。model 返回口径=服务端回显实况。

        model_tier="reasoner" 经 tier_request 钩子参数化（DeepSeek 官方思考档）；
        档位不可用（首探失败/空正文截断）时记入 reasoner_available=False 并回退
        chat 档，fallback_note 留因。finish_reason=length（截断）如实返回、
        content_filter（过滤）如实抛错、服务端中断（空正文）重试一次。
        """
        self.fallback_note = None
        requested_tier = model_tier
        effective_tier = model_tier
        if model_tier == "reasoner" and self.reasoner_available is False:
            effective_tier = None
            self.fallback_note = "reasoner 档此前实测不可用，回退 chat"

        def build(tier: str | None) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "model": model or self._default_model(),
                "messages": messages,
                "temperature": temperature,
            }
            if json_mode and tier != "reasoner":
                payload["response_format"] = {"type": "json_object"}
            # 官方 max_tokens 语义：思考档缺省 64K（不设），非思考档按调用方约束
            if max_tokens and tier != "reasoner":
                payload["max_tokens"] = max_tokens
            return self.tier_request(payload, model_tier=tier)

        def attempt(p: dict[str, Any]) -> dict[str, Any]:
            try:
                return self._call(p, call_point=call_point, ref_type=ref_type,
                                  ref_id=ref_id, max_retries=max_retries)
            except ProviderError as e:
                stripped = self._compat_resend_payload(p, e)
                if stripped is not None:
                    log.warning("%s: 网关兼容阀触发，剥离参数后重发", call_point)
                    return self._call(stripped, call_point=call_point, ref_type=ref_type,
                                      ref_id=ref_id, max_retries=max_retries)
                raise

        payload = build(effective_tier)
        try:
            body = attempt(payload)
        except ProviderError as e:
            # 思考档首探失败：标记不可用并回退 chat 重发一次
            if requested_tier == "reasoner" and self.reasoner_available is None:
                self.reasoner_available = False
                self.fallback_note = f"reasoner 档实测不可用，回退 chat: {str(e)[:200]}"
                log.warning("reasoner 档不可用，%s 回退 chat", call_point)
                payload = build(None)
                body = attempt(payload)
            else:
                raise
        self.last_usage = dict(self._last_meter)
        if requested_tier == "reasoner" and self.reasoner_available is None:
            self.reasoner_available = True

        finish_reason = self.last_usage.get("finish_reason")
        if finish_reason in FATAL_FINISH_REASONS:
            raise ProviderError(f"生成被过滤（finish_reason={finish_reason}），不可重试")
        # 服务端中断（官方 finish_reason）：content 为空时重试一次
        if finish_reason in RETRYABLE_FINISH_REASONS:
            body2 = attempt(payload)
            self.last_usage = dict(self._last_meter)
            body = body2
        try:
            message = body["choices"][0]["message"]
            content = message.get("content")
            actual_model = body.get("model", payload["model"])
        except (KeyError, IndexError, TypeError) as e:
            raise JSONParseError(f"chat 响应结构异常: {body!r:.200}") from e
        return content or "", actual_model

    def chat_json(self, messages: list[dict[str, str]], **kwargs: Any) -> tuple[dict[str, Any], str]:
        """strict JSON 便捷封装：返回 (解析后的 dict, model)。"""
        kwargs.setdefault("json_mode", True)
        content, model = self.chat(messages, **kwargs)
        return parse_strict_json(content), model


class HTTPProvider(LLMProvider):
    """带 base_url/api_key 的 HTTP provider 公共部分。

    HTTP 出网经传输脊 post_json（非 2xx 全入错、3xx 可重试带 location、
    客户端进程级复用）；本层只保留 LLM 域鉴权头与响应契约
    （返回原始 httpx.Response，调用方自行 .json()）。"""

    def __init__(self, db: Session, *, base_url: str, api_key: str, timeout: float = 120.0) -> None:
        super().__init__(db)
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout

    def _post_json(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        return post_json(
            f"{self.base_url}{path}", payload,
            headers=self._headers, timeout=self._timeout, db=self.db,
        )

    @staticmethod
    def _meter_from_openai_usage(usage: dict[str, Any] | None) -> dict[str, int]:
        usage = usage or {}
        return {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "billing_units": 0,
            # 官方 usage 细节（缓存命中 / 思维链 token；其他 provider 缺省为 0）
            "cache_hit_tokens": int(usage.get("prompt_cache_hit_tokens")
                                    or (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
            "reasoning_tokens": int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
        }

    @staticmethod
    def _finish_reason(body: dict[str, Any]) -> str | None:
        try:
            return body["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError):
            return None


class OpenAIChatProvider(HTTPProvider):
    """OpenAI chat/completions 族公共实现。

    厂商差异收拢为两处声明：chat_completions_path（路径前缀——官方 base
    不带 /v1，OpenAI 网关族带 /v1，误用即触发网关 302 漏网形态）与
    gateway_compat_params（网关可能不认、可剥离重发的参数名集合）。"""

    chat_completions_path = "/chat/completions"
    gateway_compat_params: tuple[str, ...] = ()

    def __init__(self, db: Session, *, base_url: str, api_key: str,
                 timeout: float = 120.0, model: str | None = None) -> None:
        super().__init__(db, base_url=base_url, api_key=api_key, timeout=timeout)
        self._model_override = model

    def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        resp = self._post_json(self.chat_completions_path, payload)
        body = resp.json()
        meter = self._meter_from_openai_usage(body.get("usage"))
        meter["finish_reason"] = self._finish_reason(body)
        # 计量 model 口径：服务端回显实况优先（无回显时 _call 回退请求名）
        meter["model"] = str(body.get("model") or "")
        self._last_meter = meter
        return body, meter

    def _compat_resend_payload(self, payload: dict[str, Any],
                               err: ProviderError) -> dict[str, Any] | None:
        """网关兼容阀（通用实现）：状态码属参数拒绝域且 payload 携带本 provider
        声明的可剥离参数 → 返回剥离后 payload（并留 fallback_note）。"""
        if error_status(err) not in COMPAT_VALVE_STATUS:
            return None
        strip = [k for k in self.gateway_compat_params if k in payload]
        if not strip:
            return None
        self.fallback_note = f"网关不支持参数（{', '.join(strip)}），已剥离重发"
        return {k: v for k, v in payload.items() if k not in strip}


def parse_strict_json(text: str) -> dict[str, Any]:
    """从模型返回文本中解析 JSON 对象；失败抛 JSONParseError。

    兼容 ```json 围栏与前后杂文（截取第一个 { 到最后一个 }）。
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise JSONParseError(f"响应中未找到 JSON 对象: {t[:200]!r}")
    try:
        data = json.loads(t[start : end + 1])
    except json.JSONDecodeError as e:
        raise JSONParseError(f"JSON 解析失败: {e}: {t[:200]!r}") from e
    if not isinstance(data, dict):
        raise JSONParseError("JSON 顶层不是对象")
    return data
