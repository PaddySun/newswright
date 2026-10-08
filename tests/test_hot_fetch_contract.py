"""热榜拉取契约测试：出网工厂接线（UA 策略 db 透传）、显式超时与跟随语义、
聚合 URL 构造、条目过滤、源间间隔可调用性。

覆盖口径（设计依据见 docs/design-index.md「R9」「能力③」）：
- 出网一律经统一工厂构造（R9：UA 一律取 site_config 策略键）——fetch_platform
  的 db 实参与 http_client 显式参数（timeout 有限值、follow_redirects=True）是
  接线契约（技术书 §4.2 显式超时：timeout=None 即缺陷，数值粒度不钉）；
- 聚合 URL = HOT_AGG_BASE?id=<platform>&latest（平台名进请求）；
- 条目过滤 = items 中 dict 且 title 非空白者保留（全量落库前防垃圾行）；
- 源间礼貌间隔为真实数值调用（sleep(None) 在真实时钟下 TypeError 使整轮悬挂）。

网络纪律：fake http_client 返回脚本化响应，不真联网；生产代码零改动。
"""
import json
from datetime import datetime, timezone

import pytest

import app.hot.service as hot_service
import app.ingest.http as http_mod
from app.models import PipelineTask


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response, log):
        self._response = response
        self.log = log

    def get(self, url, **kw):
        self.log.append({"url": url})
        return self._response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHttpClientFactory:
    """记录 (db, timeout, follow_redirects) 与 get URL 的工厂桩。"""

    def __init__(self, payload):
        self.payload = payload
        self.kwargs_log = []
        self.gets = []

    def __call__(self, db=None, *, timeout=60.0, follow_redirects=True, **kw):
        self.kwargs_log.append({"db": db, "timeout": timeout,
                                "follow_redirects": follow_redirects})
        return FakeClient(FakeResponse(self.payload), self.gets)


WEIBO_PAYLOAD = {"status": "success", "items": [
    {"title": "热搜一", "url": "https://weibo.example/1"},
    {"title": "热搜二", "url": "https://weibo.example/2"},
]}


def test_fetch_platform_wires_db_and_explicit_args(db_session, monkeypatch):
    """出网工厂收到请求级会话与显式有限超时/跟随语义；平台名进聚合 URL。"""
    factory = FakeHttpClientFactory(WEIBO_PAYLOAD)
    monkeypatch.setattr(http_mod, "http_client", factory)
    items = hot_service.fetch_platform("weibo", db=db_session)
    assert len(items) == 2
    call = factory.kwargs_log[-1]
    assert call["db"] is db_session          # R9：UA 策略按站点配置解析
    assert isinstance(call["timeout"], (int, float))  # §4.2 显式有限超时
    assert call["follow_redirects"] is True
    assert factory.gets and "id=weibo" in factory.gets[0]["url"]


def test_fetch_platform_filters_non_dict_and_blank_titles(db_session, monkeypatch):
    """非 dict 与空白标题条目被过滤，正常条目保留（防垃圾行过滤失效=全灭）。"""
    payload = {"items": [
        {"title": "正常条目", "url": "https://x.example/1"},
        {"title": "   ", "url": "https://x.example/2"},
        "非 dict 字符串",
    ]}
    factory = FakeHttpClientFactory(payload)
    monkeypatch.setattr(http_mod, "http_client", factory)
    items = hot_service.fetch_platform("weibo", db=db_session)
    assert len(items) == 1
    assert items[0]["title"] == "正常条目"


def test_hot_round_completes_with_real_sleep(db_session, monkeypatch):
    """热榜轮在真实时钟（不打桩 sleep）下完成：源间间隔必须为数值调用——
    sleep(None) 的 TypeError 使轮悬挂 RUNNING，被本测试拦截。"""
    monkeypatch.setattr(hot_service, "fetch_platform",
                        lambda p, **kw: WEIBO_PAYLOAD["items"])
    monkeypatch.setattr(hot_service, "_extract_keywords",
                        lambda db, topics: (["关键词"], "综述", "fake-model"))
    out = hot_service.run_hot_round(db_session, triggered_by="api")
    assert out["status"] == "DONE"
    task = db_session.get(PipelineTask, out["task_id"])
    assert task.status == "DONE"
