"""SSRF 三件套（BE-4/TG-1）：私网判定函数 + GET-only 拒绝 hook + 放行口。

威胁模型：采集条目 URL 来自不可信页面/LLM 抽取（enrich 面）——`http://127.0.0.1:8000`
（打回自己）与 `169.254.169.254`（云元数据）类目标必须拒。方案照官方 MCP fetch
三件套移植（同款 httpx，request event hook 原样可用）：每跳请求发送前过检，
重定向天然逐跳覆盖；拒绝抛 PrivateAddressError(httpx.TransportError)——既有
`except httpx.HTTPError` 捕获面（enrich 全吞/rss/web/stats）零改收编。

GET-only 是设计而非遗漏：POST 面全部是自有 API 域名（池化 JSON API 与腾讯
硬编码 host），无不可信 URL 源。

已知局限（接受并注记）：check-then-connect 存在 DNS rebinding 窗口——威胁
模型是被抓目标不可信而非主动攻击者，足够；配置 proxy 出网时判定的是目标域
解析地址而实际连接走代理（有代理时风险由代理承担）。
设计依据见 docs/design-index.md「TG-1」（BE-4 增补）。
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Callable, Iterable

import httpx
from sqlalchemy.orm import Session

from ..siteconfig import get_config

log = logging.getLogger(__name__)


class PrivateAddressError(httpx.TransportError):
    """SSRF 拒绝：目标 host 非公共地址。继承 httpx.TransportError——被既有
    `except httpx.HTTPError` 捕获面零改收编（错误分类仍由调用方）。"""


# IANA IPv4 特殊用途地址注册表（现行表落全）：本特殊网/私网三段/环回/链路本地
# （含云元数据 169.254.169.254）/CGNAT 100.64/10/IETF 协议分配/文档段三件/
# 基准测试段/组播 224/4/保留 240/4（含受限广播 255.255.255.255）。
_V4_RESERVED = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
    "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
    "224.0.0.0/4", "240.0.0.0/4",
))
# IPv6 侧关键段钉桩（未做全特殊段穷举——黑名单段全命中即可证语义）：
# 未指定/环回/唯一本地 fc00::/7/链路本地/组播/文档段。
_V6_RESERVED = tuple(ipaddress.ip_network(n) for n in (
    "::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8", "2001:db8::/32",
))


def _default_resolver(host: str) -> list[str]:
    """真实解析（getaddrinfo 全地址去重）——仅生产路径；测试一律注入替代。"""
    out: list[str] = []
    for info in socket.getaddrinfo(host, None):
        addr = info[4][0]
        if addr not in out:
            out.append(addr)
    return out


def _address_is_public(addr: ipaddress._BaseAddress) -> bool:
    """单地址判定：IPv4-mapped IPv6 先归一（IPv6Address.ipv4_mapped），再查
    IANA 保留网段黑名单，兜底 is_global and not is_multicast。"""
    if isinstance(addr, ipaddress.IPv6Address):
        mapped = addr.ipv4_mapped
        if mapped is not None:
            addr = mapped
    reserved = _V4_RESERVED if isinstance(addr, ipaddress.IPv4Address) else _V6_RESERVED
    if any(addr in net for net in reserved):
        return False
    return addr.is_global and not addr.is_multicast


def is_public_host(
    host: str | None,
    *,
    resolver: Callable[[str], Iterable[str]] | None = None,
) -> bool:
    """判定 host 是否公共可抓地址。

    IP 字面量（ipaddress 解析——原生覆盖 IPv4 简写 `127.1`/十进制 `2130706433`）
    直接判；否则 resolver 解析**全部地址**逐个判（多记录夹带任一私网地址即
    整体拒绝——DNS rebinding 多记录形态）。resolver 抛错/空结果/非法地址值
    一律 False（fail-closed：宁可误拒不放过）。resolver 可注入=测试零 DNS。
    """
    text = (host or "").strip().rstrip(".")
    if not text:
        return False
    try:
        literal = ipaddress.ip_address(text)
    except ValueError:
        pass
    else:
        return _address_is_public(literal)
    resolve = resolver or _default_resolver
    try:
        addrs = list(resolve(text))
    except Exception:  # noqa: BLE001  解析失败 fail-closed（拒绝是安全缺省）
        return False
    if not addrs:
        return False
    try:
        return all(_address_is_public(ipaddress.ip_address(a)) for a in addrs)
    except (TypeError, ValueError):
        return False


def refuse_private_destination(
    request: httpx.Request,
    *,
    db: Session | None = None,
    resolver: Callable[[str], Iterable[str]] | None = None,
) -> None:
    """采集 GET 面 SSRF 拒绝 hook（httpx event hook：每跳请求发送前执行，
    重定向逐跳天然过检）。非 GET 一律放行——POST 面全部是自有 API 域名，
    零设防是设计而非遗漏。

    放行口 site_config fetch_allow_private（缺省 False）：True 时对私网直接
    放行并 log.info 一条（站长确认存在内网源场景后才开）。工厂经
    functools.partial 预绑定 db（测试注入 resolver 零 DNS）。
    错误消息点名 host 与开关名——被抓站管理员/站长可自查自解。
    """
    if request.method != "GET":
        return
    host = request.url.host
    if is_public_host(host, resolver=resolver):
        return
    if db is not None and bool(get_config(db, "fetch_allow_private")):
        log.info("SSRF 放行口生效：私网目标 %s 被允许（site_config fetch_allow_private=true）",
                 host)
        return
    raise PrivateAddressError(
        f"SSRF 拒绝：目标 {host} 非公共地址（采集 GET 面防护）。"
        f"如确需抓取内网源，请设置 site_config fetch_allow_private=true")
