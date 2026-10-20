"""备聚合源启用形态契约测试（BE-6/AC-2，方向性遗留 hot 部分收口）。

现状定案（任务书 §一.2 亲验）：候选位代码面 C4-3 已建完整——本批仅启用形态
收口：config.py 注释更新（.env 多元素逗号分隔）+ 本契约护栏。

落账口径（以代码为准，任务书已预留「不符以代码为准呈报」）：fetch_platform
每平台每次取用落 HotCallLog **一行终态**（HR-3：中间重试尝试不逐行）——首候选
失败次候选成功的切换形态下，失败侧不落行、落账 provider=胜者 origin；任务书
AC-2 括注「两行（失败行 provider=首候选/胜者行 provider=次候选）」与实现不符，
按 A1 实际口径本测试钉单行形态。

网络纪律：MockTransport 桩注入真传输脊 GET 面（BE-4 判例——真工厂+域名 host
形态），零出网；sleep 打桩记录不真等。
设计依据见 docs/design-index.md「HR-2」「HR-3」「HG-2」。
"""
import httpx
import pytest

import app.config as app_config
import app.hot.service as hot_service
from app.models import HotCallLog
from app.transport import http as transport_http


@pytest.fixture(autouse=True)
def _fresh_client_pool():
    transport_http.reset_client_pool()
    yield
    transport_http.reset_client_pool()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(hot_service.time, "sleep", lambda s: None)


def _wire_real_get_json(monkeypatch, handler):
    """把 hot 域 get_json 打桩面接到真传输脊 GET 面（注入工厂零出网）。"""
    factory = lambda **kwargs: httpx.Client(  # noqa: E731
        transport=httpx.MockTransport(handler), **kwargs)

    def fake_get_json(url, **kw):
        kw.pop("client_factory", None)
        return transport_http.get_json(url, client_factory=factory, **kw)

    monkeypatch.setattr(hot_service, "get_json", fake_get_json)


def test_backup_candidate_enabled_contract(db_session, monkeypatch):
    """备源启用形态契约：多候选按序取用——首候选 5xx 重试耗尽（3 次）换次候选
    （1 次）成功；返回数据来自次候选；落账一行终态（ok=True、provider=胜者
    origin，中间候选失败不逐行）。"""
    counts = {"a": 0, "b": 0}

    def handler(request):
        host = httpx.URL(str(request.url)).host
        counts["a" if host == "a.example" else "b"] += 1
        if host == "a.example":
            return httpx.Response(503, text="a down")
        return httpx.Response(200, json={
            "status": "success",
            "items": [{"title": "备源条目", "url": "https://b.example/i/1"}],
        })

    _wire_real_get_json(monkeypatch, handler)
    monkeypatch.setattr(app_config, "HOT_AGG_CANDIDATES",
                        ["https://a.example/api/s", "https://b.example/api/s"])
    items = hot_service.fetch_platform("weibo", db=db_session)

    assert [it["title"] for it in items] == ["备源条目"]  # 数据来自次候选
    assert counts == {"a": 3, "b": 1}
    rows = db_session.query(HotCallLog).order_by(HotCallLog.id).all()
    assert len(rows) == 1  # 一行终态（HR-3：中间尝试/中间候选不逐行）
    assert rows[0].provider == "https://b.example"
    assert rows[0].ok is True
    assert rows[0].platform == "weibo"


def test_enabled_form_env_candidates_ordered(monkeypatch, db_session):
    """启用形态的取用顺序护栏：三候选时首两个候选全失败按序落到第三候选；
    落账 provider=第三候选（末位胜者）。"""
    def handler(request):
        host = httpx.URL(str(request.url)).host
        if host in ("a.example", "b.example"):
            return httpx.Response(503, text="down")
        return httpx.Response(200, json={
            "status": "success",
            "items": [{"title": "c 候选条目", "url": "https://c.example/i/1"}],
        })

    _wire_real_get_json(monkeypatch, handler)
    monkeypatch.setattr(app_config, "HOT_AGG_CANDIDATES", [
        "https://a.example/api/s", "https://b.example/api/s",
        "https://c.example/api/s"])
    items = hot_service.fetch_platform("zhihu", db=db_session)
    assert [it["title"] for it in items] == ["c 候选条目"]
    row = db_session.query(HotCallLog).one()
    assert row.provider == "https://c.example" and row.ok is True
