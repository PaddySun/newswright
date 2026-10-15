"""热榜拉取契约测试：传输脊 GET 面接线（UA 策略 db 透传）、显式超时与跟随语义、
聚合 URL 构造、条目过滤、源间间隔可调用性。

覆盖口径（设计依据见 docs/design-index.md「R9」「能力③」「HR-1」）：
- 出网一律经传输脊 GET 面 get_json（R9：UA 按站点策略键解析 + HR-1：分类
  单点不分叉）——fetch_platform 的 db 实参与 get_json 显式参数（timeout 有限值、
  follow_redirects=True）是接线契约（技术书 §4.2 显式超时：timeout=None 即缺陷，
  数值粒度不钉；跟随语义=采集通道既有行为零变）；
- 聚合 URL = HOT_AGG_BASE?id=<platform>&latest（平台名进请求）；
- 条目过滤 = items 中 dict 且 title 非空白者保留（全量落库前防垃圾行）；
- 源间礼貌间隔为真实数值调用（sleep(None) 在真实时钟下 TypeError 使整轮悬挂）。

网络纪律：fake get_json 返回脚本化响应，不真联网；生产代码零改动。
（热榜治理批随动：打桩面自 ingest.http_client 换 transport get_json——
被测契约断言逐条保持。）
"""
import app.hot.service as hot_service
from app.models import PipelineTask


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeGetJson:
    """记录 (url, timeout, db, follow_redirects) 的传输脊 GET 面桩。"""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.calls = []

    def __call__(self, url, *, timeout, db=None, follow_redirects=True, **kw):
        self.calls.append({"url": url, "timeout": timeout, "db": db,
                           "follow_redirects": follow_redirects})
        return FakeResponse(self.payload, self.status_code)


WEIBO_PAYLOAD = {"status": "success", "items": [
    {"title": "热搜一", "url": "https://weibo.example/1"},
    {"title": "热搜二", "url": "https://weibo.example/2"},
]}


def test_fetch_platform_wires_db_and_explicit_args(db_session, monkeypatch):
    """传输脊 GET 面收到请求级会话与显式有限超时/跟随语义；平台名进聚合 URL。"""
    fake = FakeGetJson(WEIBO_PAYLOAD)
    monkeypatch.setattr(hot_service, "get_json", fake)
    items = hot_service.fetch_platform("weibo", db=db_session)
    assert len(items) == 2
    call = fake.calls[-1]
    assert call["db"] is db_session          # R9：UA 策略按站点配置解析
    assert isinstance(call["timeout"], (int, float))  # §4.2 显式有限超时
    assert call["follow_redirects"] is True  # 采集通道既有跟随语义零变
    assert "id=weibo" in call["url"]


def test_fetch_platform_filters_non_dict_and_blank_titles(db_session, monkeypatch):
    """非 dict 与空白标题条目被过滤，正常条目保留（防垃圾行过滤失效=全灭）。"""
    payload = {"items": [
        {"title": "正常条目", "url": "https://x.example/1"},
        {"title": "   ", "url": "https://x.example/2"},
        "非 dict 字符串",
    ]}
    fake = FakeGetJson(payload)
    monkeypatch.setattr(hot_service, "get_json", fake)
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
