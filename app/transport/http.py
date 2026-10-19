"""传输脊柱 HTTP 出口：统一出网客户端 + 非 2xx 全入错的 JSON 出网单点。

定位（外部服务治理批后）：全部 JSON API 出网经 post_json/get_json——
2xx 返回原始 httpx.Response（调用方自行 .json()，与迁移前
HTTPProvider._post_json 契约一致）；非 2xx 一律入错：3xx=可重试
TransportError 带 location（网关 302 营销站漏网成「成功空响应」的实锤教训）、
429/5xx=可重试 TransportError（挂载 Retry-After 双形态解析值）、其余 >=400=
不可重试 SemanticError（官方错误码语义映射）。重试节奏协商统一走
retry_delay_ms。

两面差异（热榜治理批增 GET 面）：post_json 是 JSON API POST 单点（池客户端
不跟随重定向——3xx 须在本层拦截入错）；get_json 是采集型 JSON GET 单点
（热榜聚合 API 等，follow_redirects 缺省 True 维持采集通道既有行为——「非
2xx 入错」以重定向终态为准），并把 httpx 原生异常包装为可重试 TransportError
后上抛（裸 httpx 异常零逃逸；POST 面保持既有形态，LLM/搜索域重试模板自行
捕获）。非 2xx 分类是两面共用的单一实现。重定向策略进池键。

采集 GET 通道的客户端工厂（http_client，UA 策略 + proxy 参数位）自
ingest/http.py 原位上提至此；进程级客户端池按（源、鉴权头、超时、生效 UA、
客户端工厂、重定向策略）复用连接——UA 值入键：site_config 运行时切 UA 即
新客户端，否则管理员切 UA 不生效。工厂身份入键：同进程内工厂替换（测试桩）
不串台，生产路径工厂恒为 httpx.Client 同对象、池稳定复用。
设计依据见 docs/design-index.md「TR-1」「TR-2」「TR-3」「TR-4」「TR-6」「HR-1」「R9」。
"""
from __future__ import annotations

import random
import threading
from datetime import datetime, timezone
from functools import partial
from typing import Any, Callable

import httpx
from sqlalchemy.orm import Session

from .. import config
from ..config import PROXY_ENV_KEY  # noqa: F401  采集通道经本模块取 env 键名
from ..siteconfig import get_config
from .errors import SemanticError, TransportError
from .ssrf import refuse_private_destination
from .throttle import throttle_request

PRODUCT_NAME = "newswright"

# 可重试状态域：429 限流与 5xx 网关/服务端瞬断（重试有意义）；
# 官方错误码语义（2026-10 文档）：402 余额不足、401 认证失败、400/422 参数
# 错误——全部不可重试（重试只会烧日志）。
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
FATAL_STATUS_MESSAGE = {
    400: "请求体格式错误（400）",
    401: "API key 认证失败（401）",
    402: "账户余额不足（402）——请充值后重试",
    422: "请求参数错误（422）",
}

# Retry-After 采纳区间：[0, 60s) 开区间夹逼——服务端值超大时不无限等待。
RETRY_AFTER_MAX_MS = 60_000

# 退避抖动因子区间：2**attempt × uniform(0.5, 1.5)——确定性退避的同步踩踏
# 形态治理（RNG 断言纪律：测试只断言区间与分布形态，禁依赖具体随机序列）。
JITTER_FACTOR_RANGE = (0.5, 1.5)


def _scrub(text: str) -> str:
    """兜底脱敏：日志与报错里不该出现任何 key 形态的字符串。"""
    return text.replace("sk-", "sk-***") if text else text


def parse_retry_after(value: str | None, *, now: datetime) -> float | None:
    """Retry-After 双形态解析：delta-seconds 秒数与 HTTP-date 两种形态；
    解析失败返回 None（调用方退回降频档位对应缺省间隔）。负值钳为 0。"""
    if not value or not value.strip():
        return None
    text = value.strip()
    if text.isdigit():
        return float(text)
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - now).total_seconds())
    except (TypeError, ValueError):
        return None


# ---------- 出网 UA 策略与 proxy 参数位（自 ingest/http.py 上提） ----------


def honest_user_agent(contact_email: str | None,
                      contact_url: str | None = None) -> str:
    """诚实 UA 模板：产品名 + 联系邮箱位 + 站点链接位（P1-1：contact_url
    非空→`+{url}` 替换 `+https://localhost` 占位——UA 是被抓站管理员唯一
    申诉/识别通道，占位符是「无主爬虫」信号；未配则占位形态保留）。"""
    site = str(contact_url).strip() if contact_url else ""
    base = f"Mozilla/5.0 (compatible; {PRODUCT_NAME}/1.0; +{site or 'https://localhost'})"
    if contact_email and str(contact_email).strip():
        return f"{base[:-1]}; contact: {str(contact_email).strip()})"
    return base


def _public_site_url(db: Session) -> str | None:
    """public_base_url（复用 sitemap 既有键，不加新键）：strip 后非空才返回。"""
    raw = get_config(db, "public_base_url")
    text = str(raw).strip() if raw else ""
    return text or None


def effective_user_agent(db: Session | None = None) -> str:
    """实际出网 UA（读 site_config 策略键）：honest=诚实模板；custom=自配串
    （空串回退 honest——空 UA 是更强的拦截指纹）。db 为空时按 honest 无邮箱形态。"""
    if db is None:
        return honest_user_agent(None)
    strategy = str(get_config(db, "ua_strategy") or "honest")
    if strategy == "custom":
        custom = str(get_config(db, "ua_custom") or "").strip()
        return custom or honest_user_agent(get_config(db, "contact_email"),
                                           contact_url=_public_site_url(db))
    return honest_user_agent(get_config(db, "contact_email"),
                             contact_url=_public_site_url(db))


def proxy_url() -> str | None:
    """proxy 参数位读取（归口 config.httpx_proxy_url——调用时读取；仅对**新
    构造**客户端生效：池化客户端复用构造时配置，proxy 不在六元池键（入键会
    致缓存分裂，此为声明式取舍而非遗漏）；未配置返回 None=行为不变）。"""
    return config.httpx_proxy_url()


def http_client(db: Session | None = None, *, timeout: float = 60.0,
                follow_redirects: bool = True, **kwargs: Any) -> httpx.Client:
    """采集 GET 通道的统一出网客户端：默认 UA 按策略键解析 + proxy 参数位 +
    SSRF/节流双 request hook（GET-only 出网收口，见 TG-1/TG-2——POST 面全部
    是自有 API 域名，双 hook 对非 GET 一律放行是设计而非遗漏）；其余构造参数
    透传（timeout/follow_redirects/transport 等）。请求级 headers 与本客户端
    默认 headers 按 httpx 语义合并（请求级覆盖同名头）。错误分类仍由调用方
    （hook 抛 PrivateAddressError/ThrottledError 均继承 httpx.TransportError，
    既有 except 捕获面零改收编）。池化合并不做——采集低频+UA 可变（注记）。"""
    client_kwargs: dict[str, Any] = {
        "timeout": timeout,
        "follow_redirects": follow_redirects,
        "headers": {"User-Agent": effective_user_agent(db)},
        # 双 hook 均 GET-only；SSRF 在前（先拒后等，不为将被拒的请求排队）
        "event_hooks": {"request": [partial(refuse_private_destination, db=db),
                                    partial(throttle_request, db=db)]},
        **kwargs,
    }
    proxy = proxy_url()
    if proxy:
        client_kwargs["proxy"] = proxy
    return httpx.Client(**client_kwargs)


# ---------- 进程级客户端池（JSON API 出网） ----------

_client_pool: dict[tuple, httpx.Client] = {}
_pool_lock = threading.Lock()


def reset_client_pool() -> None:
    """清空客户端池（测试复位位；生产不调用——池随进程生命周期存活）。"""
    with _pool_lock:
        _client_pool.clear()


def _origin_of(url: str) -> str:
    """URL 源（scheme://netloc）。httpx.URL.netloc 是 bytes——解码为 str
    （GET 面把它用作落账的聚合器 origin 字段，不能带 b'' 形态）。"""
    u = httpx.URL(url)
    netloc = u.netloc.decode("ascii") if isinstance(u.netloc, bytes) else str(u.netloc)
    return f"{u.scheme}://{netloc}"


def _pooled_client(
    key: tuple,
    factory: Callable[..., httpx.Client],
    *,
    timeout: float,
    user_agent: str,
    follow_redirects: bool,
) -> httpx.Client:
    """池取用（双检锁线程安全）：同键复用、命中失败重建、构造参数=池键成分。"""
    client = _client_pool.get(key)
    if client is not None:
        return client
    with _pool_lock:
        client = _client_pool.get(key)
        if client is not None:
            return client
        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "headers": {"User-Agent": user_agent},
            # 重定向策略是池键成分：JSON API POST 面不跟随（3xx 必须在本层
            # 拦截入错——网关 302 营销站漏网=「成功空响应」形态的实锤教训）；
            # 采集 GET 面跟随（既有行为零变，「非 2xx 入错」以终态为准）。
            "follow_redirects": follow_redirects,
        }
        proxy = proxy_url()
        if proxy:
            client_kwargs["proxy"] = proxy
        client = factory(**client_kwargs)
        _client_pool[key] = client
        return client


def _non_2xx_error(resp: httpx.Response) -> Exception:
    """非 2xx 响应 → 分类错误对象（POST/GET 两面共用的分类单点，不分叉）。"""
    retry_after = parse_retry_after(
        resp.headers.get("retry-after"), now=datetime.now(timezone.utc))
    if 300 <= resp.status_code < 400:
        location = resp.headers.get("location")
        head = (f"HTTP {resp.status_code}: 重定向至 {location}" if location
                else f"HTTP {resp.status_code}: 重定向（无 location 头）")
        return TransportError(
            f"{head}: {_scrub(resp.text[:300])}",
            retryable=True, status=resp.status_code,
            location=location, retry_after=retry_after,
        )
    if resp.status_code in RETRYABLE_STATUS:
        return TransportError(
            f"HTTP {resp.status_code}: {_scrub(resp.text[:300])}",
            retryable=True, status=resp.status_code, retry_after=retry_after,
        )
    msg = FATAL_STATUS_MESSAGE.get(resp.status_code, f"HTTP {resp.status_code}")
    return SemanticError(f"{msg}: {_scrub(resp.text[:300])}", status=resp.status_code)


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout: float,
    db: Session | None = None,
    client_factory: Callable[..., httpx.Client] | None = None,
) -> httpx.Response:
    """单次 JSON POST（全部 JSON API POST 出网的统一单点；重试循环在能力域）。

    2xx 返回原始 httpx.Response（调用方自行 .json()）；非 2xx 抛
    transport.errors 分类异常（3xx/429/5xx=可重试 TransportError，
    其余 >=400=SemanticError），错误消息脱敏。客户端经进程级池复用。
    """
    user_agent = effective_user_agent(db)
    factory = client_factory if client_factory is not None else httpx.Client
    key = (_origin_of(url), headers.get("Authorization", ""), float(timeout),
           user_agent, factory, False)
    client = _pooled_client(key, factory, timeout=timeout, user_agent=user_agent,
                            follow_redirects=False)
    resp = client.post(url, json=payload, headers=headers)

    if 200 <= resp.status_code < 300:
        return resp
    raise _non_2xx_error(resp)


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float,
    db: Session | None = None,
    follow_redirects: bool = True,
    client_factory: Callable[..., httpx.Client] | None = None,
) -> httpx.Response:
    """单次 JSON GET（采集型 JSON GET 出网的统一单点：热榜聚合 API 等）。

    与 post_json 共用客户端池（重定向策略进池键）与非 2xx 分类单点；
    面差异两点：
    - follow_redirects 缺省 True（采集通道既有行为零变）——「非 2xx 入错」
      以重定向终态为准：正常重定向链落到 2xx 不入错，终态 3xx（裸 302 无
      location 等）按可重试 TransportError 入错，超限链以 TooManyRedirects
      包装入错；
    - httpx 原生异常（读超时/连接失败等 HTTPError 族）在本面包装为可重试
      TransportError 再上抛——裸 httpx 异常零逃逸（POST 面不越权改动：
      LLM/搜索域重试模板自行捕获 httpx 异常）。
    """
    user_agent = effective_user_agent(db)
    factory = client_factory if client_factory is not None else httpx.Client
    key = (_origin_of(url), (headers or {}).get("Authorization", ""), float(timeout),
           user_agent, factory, follow_redirects)
    client = _pooled_client(key, factory, timeout=timeout, user_agent=user_agent,
                            follow_redirects=follow_redirects)
    try:
        resp = client.get(url, params=params, headers=headers)
    except httpx.HTTPError as e:
        raise TransportError(f"{type(e).__name__}: {e}", retryable=True) from e
    if 200 <= resp.status_code < 300:
        return resp
    raise _non_2xx_error(resp)


# ---------- 重试节奏协商 ----------


def retry_delay_ms(err: BaseException, attempt: int) -> int:
    """下一次重试的等待毫秒数：服务端 Retry-After 优先（夹逼 [0, 60s)），
    否则随机化指数退避 2**attempt × uniform(0.5, 1.5) 秒。"""
    retry_after = getattr(err, "retry_after", None)
    if retry_after is not None:
        return int(min(max(retry_after * 1000.0, 0.0), RETRY_AFTER_MAX_MS - 1))
    base_ms = float(2 ** attempt) * 1000.0
    return int(base_ms * random.uniform(*JITTER_FACTOR_RANGE))
