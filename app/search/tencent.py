"""腾讯云联网搜索（wsa / SearchPro），TC3-HMAC-SHA256 签名。

签名严格按官方示例（项目文档（外层）API文档/腾讯-网页搜索/http请求示例代码.py）实现：
拼接规范请求串（canonical_headers 结尾 \\n 后再加一个显式 \\n）→ 派生签名密钥
（TC3+SecretKey → date → service → tc3_request）→ Authorization 头。

实测要点（2026-09-28 连通实测）：
- Action=SearchPro、Version=2025-05-08、host wsa.tencentcloudapi.com、Region 不需要；
- Cnt 只接受 10/20/30/40/50（小于 10 报 InvalidParameter: illegal Cnt）→ 就近向上取档；
- Pages 为 JSON 字符串数组（每条需二次 json.loads）；
- lite 版：content（动态摘要）为空，passage（标准摘要）可用；score 0-1；
- HTTP 200 不代表成功：错误在 Response.Error（AuthFailure/InvalidParameter 等）。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .. import config
from .base import SearchError, SearchProvider, SearchResult, _parse_dt

_TENCENT_HOSTS = ("wsa.tencentcloudapi.com",)


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _tc3_headers(secret_id: str, secret_key: str, service: str, host: str,
                 action: str, version: str, payload: str) -> dict[str, str]:
    algorithm = "TC3-HMAC-SHA256"
    timestamp = int(time.time())
    date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    ct = "application/json; charset=utf-8"
    canonical_headers = f"content-type:{ct}\nhost:{host}\nx-tc-action:{action.lower()}\n"
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    # 官方示例口径：canonical_headers 末尾自带 \n 之后，还有显式 \n 分隔
    canonical_request = (
        "POST\n" + "/\n" + "" + "\n" + canonical_headers + "\n" + signed_headers + "\n" + hashed_payload
    )
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = (
        algorithm + "\n" + str(timestamp) + "\n" + credential_scope + "\n"
        + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    )
    secret_date = _sign(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _sign(secret_date, service)
    secret_signing = _sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        algorithm + " Credential=" + secret_id + "/" + credential_scope
        + ", SignedHeaders=" + signed_headers + ", Signature=" + signature
    )
    return {
        "Authorization": authorization, "Content-Type": ct, "Host": host,
        "X-TC-Action": action, "X-TC-Timestamp": str(timestamp), "X-TC-Version": version,
    }


class TencentSearchProvider(SearchProvider):
    name = "tencent"

    def __init__(self, *, secret_id: str | None = None, secret_key: str | None = None,
                 timeout: float = 30.0) -> None:
        self._secret_id = secret_id or config.TENCENT_SECRET_ID
        self._secret_key = secret_key or config.TENCENT_SECRET_KEY
        self._host = config.TENCENT_WSA_HOST
        self._action = config.TENCENT_WSA_ACTION
        self._version = config.TENCENT_WSA_VERSION
        self._timeout = timeout
        if not (self._secret_id and self._secret_key):
            raise SearchError("tencent provider 缺少凭据（.env tencentSecretId/tencentSecretKey）")

    def _search(self, query: str, count: int, opts: dict[str, Any]) -> list[SearchResult]:
        # Cnt 档位：10/20/30/40/50 → 就近向上取
        cnt = next((n for n in (10, 20, 30, 40, 50) if n >= max(1, int(count))), 50)
        body_obj: dict[str, Any] = {"Query": query, "Cnt": cnt}
        if opts.get("freshness"):
            body_obj["Freshness"] = opts["freshness"]  # d7/m3/y2 或日期区间
        payload = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":"))
        headers = _tc3_headers(self._secret_id, self._secret_key, "wsa", self._host,
                               self._action, self._version, payload)
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(f"https://{self._host}", headers=headers,
                               content=payload.encode("utf-8"))
        if resp.status_code >= 500:
            e = SearchError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            e.retryable = True  # type: ignore[attr-defined]
            raise e
        if resp.status_code >= 400:
            raise SearchError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        r = body.get("Response") or {}
        if "Error" in r:
            err = r["Error"]
            raise SearchError(f"{err.get('Code')}: {err.get('Message')}")
        pages_raw = r.get("Pages") or []
        out: list[SearchResult] = []
        for p in pages_raw:
            try:
                v = json.loads(p) if isinstance(p, str) else p
            except json.JSONDecodeError:
                continue
            if not isinstance(v, dict):
                continue
            out.append(SearchResult(
                title=str(v.get("title") or "").strip(),
                url=str(v.get("url") or "").strip(),
                snippet=str(v.get("passage") or "").strip(),
                content=str(v.get("content") or "").strip(),  # lite 版为空
                published_at=_parse_dt(v.get("date")),
                raw=v,
            ))
        return out
