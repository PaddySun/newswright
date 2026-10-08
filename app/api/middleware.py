"""响应头契约中间件（P2-4 三段式全域落地，设计依据见 docs/design-index.md
「ADR-5」「P2-4」）：按请求路径把 Cache-Control 划入三段判定域——

- ``no-store``：API 与状态端点（/api/*、/feedback、/healthz）——响应含会话/身份/
  实时状态，任何一层缓存都会造成跨用户串数据或"假活"（morningdeck JA4 事故
  的直接教训）；
- ``immutable``：静态资源（/static/*）——内容由部署版本锚定，页面侧以版本
  query 引用（``?v=<deploy 摘要>``），可永久缓存；
- ``no-cache, must-revalidate``：HTML 页与 SEO 文件（公开页/登录页/sitemap/
  robots/feed）——内容随公开模式配置即时变化，禁止陈旧渲染但允许复验。

路径判定是纯函数（``cache_policy_for``），可脱离 ASGI 单测；配错缓存策略
"只伤性能不伤正确性"（ADR-5③）：no-store 段永不放宽，immutable 段内容由
版本锚定，HTML 段最坏情形是多一次回源。
"""
from __future__ import annotations

# 三段判定域的缓存策略字面值（测试与实现共用同一常量，防漂移）
POLICY_NO_STORE = "no-store"
POLICY_IMMUTABLE = "public, max-age=31536000, immutable"
POLICY_NO_CACHE = "no-cache, must-revalidate"

# 状态端点前缀/路径：API 族 + 匿名反馈 + 健康自省（healthz 处理器自带同款
# 头，中间件仅在缺失时补写，不覆盖既有值——R2 契约以端点为第一责任方）
_NO_STORE_PREFIXES = ("/api/", "/feedback", "/healthz")
_NO_STORE_EXACT = ("/api", "/feedback", "/healthz")
# 静态资源判定域：全部经 StaticFiles 托管于 /static，引用侧带版本 query
_IMMUTABLE_PREFIX = "/static/"


def cache_policy_for(path: str) -> str:
    """路径 → 缓存策略（纯函数）。判定次序：静态 → 状态端点 → 其余（HTML/SEO
    文件）——越具体的域越先判，兜底取最保守的 no-cache 而非可缓存。"""
    if path.startswith(_IMMUTABLE_PREFIX):
        return POLICY_IMMUTABLE
    if path.startswith(_NO_STORE_PREFIXES) or path in _NO_STORE_EXACT:
        return POLICY_NO_STORE
    return POLICY_NO_CACHE


async def cache_header_middleware(request, call_next):
    """ASGI 中间件：为缺失 Cache-Control 的响应补上路径判定域对应的策略。

    只补缺不覆盖：healthz 等自带契约头的端点保持第一责任方语义；后续若新增
    自带头端点，行为同理。
    """
    response = await call_next(request)
    if "cache-control" not in response.headers:
        response.headers["Cache-Control"] = cache_policy_for(request.url.path)
    return response
