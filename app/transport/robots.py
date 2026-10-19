"""robots.txt 分级遵守（BE-5/RG-1）：采集出网礼仪——按 origin 缓存的分级裁决。

分级辨析（任务书定案，勿回退）：
- RSS feed 拉取=feed 语义行业惯例，不查（etag 协商已是礼貌实践）；
- 列表页主抓=管理员显式配置等同授权，不查（但节流器采信 Crawl-delay 缓存）；
- enrich 二次 URL 抓取=URL 来自不可信页面/LLM 抽取、「没人授权过」——必查
  （Disallow 即放弃富化保留原摘要；消费方 enrich_entry_text 唯一，RG-2）。

分级语义（对齐 RFC 9309，5xx 勿 fail-open）：
- 2xx → RobotFileParser.parse 按最终响应判（follow_redirects 后的落地内容；
  缓存键=请求 origin；重定向跨域以落地规则为准——注记，不递归查落地域）；
- 404 与 DNS 解析不可得（NXDOMAIN 形态：异常链 gaierror）→ 放行（allow-all，
  成功 TTL）——域名不存在则无政策可违，且随后主抓同样解析失败；
- 5xx、其余非 2xx（401/403 照 RFC 9309=完全拒绝）与网络/解析异常 →
  fail-closed（disallow-all，短 TTL 300s 后重试——5xx 错误页解析出的空
  规则集实质 fail-open，与「连接失败保守拒」矛盾，勿采）。

robots.txt 自身抓取经 http_client 工厂（SSRF+节流钩子天然覆盖=零额外接线，
timeout=10 小文件快进 fail-closed 不拖富化）；UA 走工厂缺省策略；
can_fetch/crawl_delay 的 UA token=产品名 newswright（诚实爬虫身份，站点可
按 User-agent: newswright 定向立规）。stdlib 语义注记：CPython robotparser
的 can_fetch/crawl_delay 均为「文件序首匹配组生效」（特定组存在时 * 组不
叠加，非 RFC 9309 最特定组语义）——两 API 同用 stdlib 同一语义。

进程级缓存 origin(scheme://netloc) → (fetched_at, parser|None, crawl_delay_s)
+threading.Lock；monotonic 时钟可注入（_now，测试假时钟判例）。parser=None
⇒ fail-closed 标记；404/NXDOMAIN 为 allow_all parser。并发首抓双发可接受
（幂等，后写覆盖；锁外抓取不阻塞其他 origin）。

依赖方向（robots 归属 transport 层的定案）：throttle→robots（读 delay 缓存，
RG-3）与 robots→http（抓取）并存会让 http→throttle→robots→http 成环，故
本模块对 http_client 的导入延迟到抓取时点——模块级只依赖 stdlib。

设计依据见 docs/design-index.md「RG-1」（BE-5 增补）。
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable
from urllib import robotparser
from urllib.parse import urlparse

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# 诚实爬虫身份：robots 裁决的 UA token（产品名——与出网 UA 模板同源）
ROBOTS_UA_TOKEN = "newswright"

# 缓存 TTL：成功（2xx/404/NXDOMAIN 放行）1 小时；失败（fail-closed）短 300s
# 后自动重试（服务恢复即放行）
ROBOTS_CACHE_TTL_S = 3600.0
ROBOTS_FAIL_TTL_S = 300.0

# 进程级缓存：origin → (fetched_at, parser|None, crawl_delay_s)
_cache: dict[str, tuple[float, robotparser.RobotFileParser | None, float | None]] = {}
_lock = threading.Lock()

# monotonic 时钟（测试注入假时钟——判例：robots 测试一律零真 sleep）
_now: Callable[[], float] = time.monotonic


def _reset_for_tests() -> None:
    """复位进程级缓存（判例纪律：每测试文件 fixture 复位）。"""
    with _lock:
        _cache.clear()


def _allow_all_parser() -> robotparser.RobotFileParser:
    p = robotparser.RobotFileParser()
    p.allow_all = True
    return p


def _dns_unavailable(exc: BaseException | None) -> bool:
    """异常链是否 DNS 解析不可得（gaierror——NXDOMAIN 形态）。errno 细分
    （EAI_NONAME vs EAI_AGAIN）不可移植，不细分：DNS 不可得时主抓同样解析
    失败、放行裁决不产生实际抓取，后果有界。"""
    seen = 0
    while exc is not None and seen < 10:
        if isinstance(exc, socket.gaierror):
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


def _fetch_robots(
    origin: str, *, db: Session | None = None
) -> tuple[robotparser.RobotFileParser | None, float | None]:
    """抓 {origin}/robots.txt 并按分级语义归一为 (parser, crawl_delay)。

    parser=None ⇒ fail-closed；allow_all parser ⇒ 404/NXDOMAIN 放行。
    follow_redirects=True 按最终响应判（跨域重定向以落地规则为准，缓存键
    仍为请求 origin——任务书定形）。测试注入面：本函数（整桩）或
    transport.http.http_client（MockTransport）。
    """
    from .http import http_client  # 惰性导入：破 transport 内环（见模块 docstring）

    try:
        with http_client(db, timeout=10.0, follow_redirects=True) as client:
            resp = client.get(f"{origin}/robots.txt")
    except Exception as e:  # noqa: BLE001  网络异常分级：DNS 不可得放行，其余 fail-closed
        if _dns_unavailable(e):
            return _allow_all_parser(), None
        log.info("robots 不可得（fail-closed）origin=%s: %s", origin, e)
        return None, None
    if resp.status_code == 404:
        return _allow_all_parser(), None
    if not 200 <= resp.status_code < 300:
        log.info("robots 响应 %s（fail-closed）origin=%s", resp.status_code, origin)
        return None, None
    parser = robotparser.RobotFileParser()
    try:
        parser.parse(resp.text.splitlines())
    except Exception:  # noqa: BLE001  解析异常 fail-closed
        log.info("robots 解析失败（fail-closed）origin=%s", origin)
        return None, None
    delay = parser.crawl_delay(ROBOTS_UA_TOKEN)
    return parser, (float(delay) if delay is not None else None)


def _origin_of(url: str) -> str | None:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        return None  # 非 HTTP(S) 无 robots 语义
    return f"{u.scheme}://{u.netloc}"


def allowed(url: str, *, db: Session | None = None) -> bool:
    """URL 是否被源站 robots 允许抓取（enrich 唯一消费方，RG-2）。

    缓存 TTL 内直接判；过期/未缓存则抓取（分级语义见模块 docstring）后判。
    UA token=ROBOTS_UA_TOKEN；抓取异常在 _fetch_robots 内分级归一，本函数
    不再抛错。
    """
    origin = _origin_of(url)
    if origin is None:
        return True
    now = _now()
    with _lock:
        entry = _cache.get(origin)
    if entry is not None:
        fetched_at, parser, _delay = entry
        ttl = ROBOTS_FAIL_TTL_S if parser is None else ROBOTS_CACHE_TTL_S
        if now - fetched_at < ttl:
            return parser is not None and parser.can_fetch(ROBOTS_UA_TOKEN, url)
    parser, delay = _fetch_robots(origin, db=db)
    with _lock:
        _cache[origin] = (_now(), parser, delay)
    return parser is not None and parser.can_fetch(ROBOTS_UA_TOKEN, url)


def denial_reason(url: str) -> str:
    """最近裁决的拒绝原因域（供 enrich 放弃日志）：Disallow=规则拒绝 /
    robots 不可得=fail-closed / 空串=无缓存或该 URL 实为允许。纯缓存读取。"""
    origin = _origin_of(url)
    if origin is None:
        return ""
    with _lock:
        entry = _cache.get(origin)
    if entry is None:
        return ""
    _fetched_at, parser, _delay = entry
    if parser is None:
        return "robots 不可得"
    return "" if parser.can_fetch(ROBOTS_UA_TOKEN, url) else "Disallow"


def crawl_delay_cached(netloc: str) -> float | None:
    """该 netloc 已缓存的 Crawl-delay 秒值（纯缓存读取零网络，RG-3）。

    2xx 解析时顺带记 parser.crawl_delay(ROBOTS_UA_TOKEN)；未抓过/无记录/
    fail-closed 缓存 → None。TTL 过期的旧值仍返回——礼貌侧宁可采信可能过期
    的 delay 也不丢分量（重取由 allowed 的下次裁决驱动）。throttle.
    _min_interval_for 第三分量消费。host[:port] 小写精确比对（带端口 origin
    与无端口查询不互认——罕见形态注记）。
    """
    if not netloc:
        return None
    want = netloc.lower()
    with _lock:
        for key, (_t, _parser, delay) in _cache.items():
            key_netloc = key.split("://", 1)[1]
            if key_netloc.lower() == want:
                return delay
    return None
