"""C1-4 变异分诊批次 5 补强测试（ingest.rss 主带 + rules/sanitize/fingerprint 小模块
+ C1-1 十三条 D 转 C，共 111 条新增 C 类断言；另有 18 条 C 已由既有测试关闭）。

断言全部来自设计书条款：
- 技术书 v1.6 ADR-8 两补条款（D-A/D-B 拍板）：base_url 尾斜杠兼容（rstrip("/") 拼
  接、无论带否尾斜杠最终请求 URL 唯一）；OpenAI 兼容请求头 Authorization: Bearer
  <key> 与 Content-Type: application/json——键名与值形态即条款；
- 产品书 AC-05.1（账目分桶：feed_entries = inserted + dup_blocked + rule_rejected +
  failed + archived；inserted 含 DUP 行；dup_blocked=(source_id,guid) 拦截及同 feed
  内重复 guid，均不落行；failed 不落行仅计数；无静默缺条）；
- AC-05.2（D15：方向内同 URL 指纹 → DUP + duplicate_of 同方向引用 + 全文照存 +
  零打分；归一化 URL 指纹 F 的折叠语义）+ 技术书模块表 fingerprint 行（B4：tag:/urn:
  型 guid 跳过归一化、URL 型归一化）；
- AC-04.6（源级间隔依赖 last_fetched_at 记账）+ DT-1/AC-04.3（304/not_modified 轮
  是 suspect 豁免判据输入）+ AC-04.2（last_error 证据纪律）；
- 技术书模块表 ingest/rss 硬约束①（304 判定先于 raise_for_status）+ ⑤（etag 原样
  存取，截断会让 304 永不命中）+ §4.2（外部调用一律显式超时，httpx timeout 必填）；
- 产品书 rules 口径（正文长度 < 阈值〔默认 200〕拒；黑名单命中标题或正文拒；发布
  时间距今 > N 天〔默认 30〕拒；缺发布时间不拒——「默认」措辞即参数可覆写）；
- §4.1 item 行（fetch_status 枚举、rule_reject_reason、sanitize 三列、title/url/
  published_at 落值）+ AC-06.1/06.2/06.3（sanitize PASSED/REJECTED 值与 reason 钉死、
  keyword_deny 全链记账、REJECTED 全文照存、被过滤 ≠ 抓取失败）。

网络纪律：全部经 fake httpx.Client / MockTransport，不真联网。
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import app.config as cfg
import app.ingest.rss as rss_mod
from app.ingest.fingerprint import canonical_url, url_fingerprint
from app.ingest.rss import fetch_source, normalize_guid
from app.ingest.rules import apply_rules
from app.models import Direction, Item, Source

_LONG = "正文内容足够长以通过规则初筛。" * 20  # 300 字符 > RULE_MIN_BODY_CHARS


class RecordingClient:
    """伪 httpx.Client：记录构造 kwargs 与每次 get 的 url/headers（不联网）。"""
    init_kwargs: dict = {}
    calls: list = []
    responses: list = []

    def __init__(self, **kw):
        RecordingClient.init_kwargs = dict(kw)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        RecordingClient.calls.append({"url": url, "headers": dict(headers or {})})
        return RecordingClient.responses.pop(0)


class FakeResp:
    def __init__(self, content, status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})

    def raise_for_status(self):
        # 与真实 httpx 对齐：≥300 一律抛（模块表硬约束①的实测坑——304 判定必须
        # 先于 raise_for_status，否则 304 被当失败记账）
        if self.status_code >= 300:
            raise httpx.HTTPStatusError(f"{self.status_code}", request=None, response=None)  # type: ignore


def _patch(monkeypatch, *responses):
    RecordingClient.responses = list(responses)
    RecordingClient.calls = []
    RecordingClient.init_kwargs = {}
    monkeypatch.setattr(rss_mod.httpx, "Client", RecordingClient)


def _feed(*items: str) -> bytes:
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
        + "".join(items)
        + "</channel></rss>"
    ).encode("utf-8")


def _item(guid: str, link: str | None, title: str, body: str = _LONG,
          pub: str | None = None) -> str:
    link_tag = f"<link>{link}</link>" if link is not None else ""
    pub_tag = f"<pubDate>{pub}</pubDate>" if pub else ""
    return (f"<item><guid>{guid}</guid>{link_tag}<title>{title}</title>{pub_tag}"
            f"<description>{body}</description></item>")


def _mk_source(db_session, url: str = "https://feeds.example/a.xml", **kw):
    d = Direction(name="DR", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url=url, type="rss", **kw)
    db_session.add(src)
    db_session.commit()
    return d, src


# ---------- ADR-8 两补条款（C1-1 十三条 D 转 C：HTTPProvider.__init__ m3-m15） ----------


class _DummyProvider:
    """最小 HTTPProvider 具体化：_post 直走 _post_json（捕获真实构造的请求）。"""


_REAL_HTTPX_CLIENT = httpx.Client  # 模块级绑定真实类（patch 后自引用防护）


def _capture_provider(monkeypatch, base_url: str, db_session):
    from app.providers.base import HTTPProvider

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"},
                                                      "finish_reason": "stop"}]})

    class CapturingClient:
        def __init__(self, **kw):
            self._c = _REAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))

        def __enter__(self):
            return self._c

        def __exit__(self, *a):
            self._c.close()
            return False

    monkeypatch.setattr("app.providers.base.httpx.Client", CapturingClient)

    class Dummy(HTTPProvider):
        name = "dummy"

        def _post(self, payload):
            resp = self._post_json("/chat/completions", payload)
            return resp.json(), {}

    p = Dummy(db_session, base_url=base_url, api_key="test-key-123")
    return p, captured


def test_provider_base_url_trailing_slash_contract(db_session, monkeypatch):
    """ADR-8 补条款（D-A 拍板）：base_url 与端点路径拼接必须兼容尾斜杠有无——
    去尾斜杠后拼接，用户配置无论带否尾斜杠，最终请求 URL 唯一。"""
    urls = set()
    for base in ("https://api.example.com/v1", "https://api.example.com/v1/",
                 "https://api.example.com/vX", "https://api.example.com/vX/"):
        p, captured = _capture_provider(monkeypatch, base, db_session)
        p._post({"model": "m", "messages": []})
        assert len(captured) == 1
        urls.add(str(captured[0].url))
    assert urls == {"https://api.example.com/v1/chat/completions",
                    "https://api.example.com/vX/chat/completions"}


def test_provider_openai_headers_wire_contract(db_session, monkeypatch):
    """ADR-8 补条款（D-B 拍板）：OpenAI 兼容 HTTP 调用构造 Authorization: Bearer <key>
    与 Content-Type: application/json 两请求头——键名与值形态即条款。"""
    p, captured = _capture_provider(monkeypatch, "https://api.example.com/v1", db_session)
    p._post({"model": "m", "messages": []})
    headers = captured[0].headers
    assert headers.get("Authorization") == "Bearer test-key-123"
    assert headers.get("Content-Type") == "application/json"
    # 键名形态即条款：不允许变形键（捕获 httpx.Request 的原始头名——小写线缆形态）
    raw_names = [k for k, _ in headers.items()]
    assert "authorization" in raw_names and "content-type" in raw_names
    assert not any(k.startswith("xx") for k in raw_names)


# ---------- fingerprint：归一化折叠（AC-05.2）+ 指纹命中精确性 ----------


def test_fingerprint_normalization_scheme_case_and_no_scheme():
    """AC-05.2「归一化 URL 指纹」折叠语义：scheme 大小写必须折叠（否则同文异形
    URL 指纹分裂、AC-05.2 去重失效）；无 scheme 的 link 归一化不崩（B4 归一化 link）。"""
    assert canonical_url("HTTPS://EX.com/post") == "https://ex.com/post"
    assert url_fingerprint("HTTPS://ex.com/post") == url_fingerprint("https://ex.com/post")
    assert canonical_url("www.x.com/a") == "www.x.com/a"
    fp = url_fingerprint("www.x.com/a")
    assert fp is not None and len(fp) == 64


def test_normalize_guid_b4_url_form_and_skip(db_session):
    """技术书模块表 fingerprint 行（B4）：URL 型 guid 归一化（剔跟踪参数）；tag: 型
    （非 http/https URL 型）跳过归一化原样保留。"""
    assert normalize_guid({"id": "http://x/1?utm_source=f"}) == "http://x/1"
    assert normalize_guid({"id": "TAG:Example:1"}) == "TAG:Example:1"
    assert normalize_guid({"id": "urn:uuid:1234"}) == "urn:uuid:1234"


# ---------- rules：阈值/天数参数覆写 + 过期边界（产品书 rules 口径） ----------


def test_rules_threshold_params_override_defaults():
    """产品书 rules 口径「默认 200/默认 30」——显式参数必须覆写默认值；
    「正文长度 < 阈值拒」字面边界：恰等于阈值放行。"""
    r = apply_rules(title="t", content_text="短", min_chars=10, published_at=None)
    assert r.passed is False and r.reason == "too_short:1<10"
    r = apply_rules(title="t", content_text="x" * 10, min_chars=10, published_at=None)
    assert r.passed is True  # 恰在边界：< 阈值才拒
    now = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)
    r = apply_rules(title="t", content_text="x" * 300,
                    published_at=now - timedelta(days=10), max_age_days=5, now=now)
    assert r.passed is False and r.reason == "expired:10d>5d"


def test_rules_expiry_day_boundary_is_strictly_greater():
    """产品书 rules 口径「距今 > N 天拒」：恰 30 天不拒；30 天 + 5 秒必拒。"""
    now = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)
    r = apply_rules(title="t", content_text="x" * 300,
                    published_at=now - timedelta(days=30), max_age_days=30, now=now)
    assert r.passed is True
    r = apply_rules(title="t", content_text="x" * 300,
                    published_at=now - timedelta(days=30, seconds=5),
                    max_age_days=30, now=now)
    assert r.passed is False


# ---------- parse/guid：AC-05.1 无静默缺条 + §4.1 title 列 ----------


def test_parse_feed_entries_skips_only_guidless_and_keeps_titles():
    """AC-05.1（无静默缺条）：无 guid 条目跳过后其余条目必须继续解析；
    §4.1 title 列：有标题落值、缺标题为空串。"""
    xml = _feed(
        "<item><description>无 guid 无 link 条目</description></item>",
        _item("g1", "https://ex/1", "First"),
        _item("tag:2026:x9", None, ""),  # 有 guid 无 link 无标题
    )
    entries = rss_mod.parse_feed_entries(xml)
    assert len(entries) == 2
    assert entries[0].guid == "g1"
    assert entries[0].title == "First"
    assert entries[1].guid == "tag:2026:x9"


# ---------- fetch_source：请求契约 / 304 / 失败记账 / etag 回写 ----------


def test_fetch_request_contract_headers_and_stats_attribution(db_session, monkeypatch):
    """§4.2 显式超时 + 目标=源 URL + 条件请求头 If-None-Match 原样回传（模块表
    硬约束⑤：变形/缺失会让 304 永不命中）+ AC-05.1 stats 源归因。"""
    d, src = _mk_source(db_session, etag='W/"v9"', last_modified="Tue, 01 Jan 2026 00:00:00 GMT")
    _patch(monkeypatch, FakeResp(_feed(_item("g1", "https://ex/1", "T1"))))

    s = fetch_source(db_session, src)

    assert "timeout" in RecordingClient.init_kwargs
    assert RecordingClient.init_kwargs["timeout"] is not None
    assert len(RecordingClient.calls) == 1
    assert RecordingClient.calls[0]["url"] == "https://feeds.example/a.xml"
    headers = RecordingClient.calls[0]["headers"]
    assert headers.get("If-None-Match") == 'W/"v9"'
    # stats 归因（AC-05.1 每源账目）
    assert s.source_id == src.id and s.url == "https://feeds.example/a.xml"


def test_fetch_304_shortcircuit_before_raise_for_status(db_session, monkeypatch):
    """模块表硬约束①：304 判定先于 raise_for_status（httpx 对一切 3xx 抛异常）——
    304 必须 not_modified=true 且零落行（DT-1/AC-04.3 的 304 轮豁免判据输入），
    并照常刷新 last_fetched_at（AC-04.6 源级间隔记账）。"""
    d, src = _mk_source(db_session, etag='W/"v1"')
    _patch(monkeypatch, FakeResp(b"", status_code=304, headers={"ETag": 'W/"v1"'}))

    s = fetch_source(db_session, src)

    assert s.not_modified is True
    assert s.inserted == 0 and s.error is None
    assert src.last_fetched_at is not None
    assert db_session.query(Item).filter_by(source_id=src.id).count() == 0


def test_fetch_http_error_records_error_evidence(db_session, monkeypatch):
    """AC-04.2 last_error 证据纪律：抓取异常必须如实落账（异常类型名: 消息）。"""
    d, src = _mk_source(db_session)

    class ErrClient(RecordingClient):
        def get(self, url, headers=None):
            raise httpx.ConnectError("boom")

    ErrClient.responses = []
    ErrClient.calls = []
    ErrClient.init_kwargs = {}
    monkeypatch.setattr(rss_mod.httpx, "Client", ErrClient)

    s = fetch_source(db_session, src)
    assert s.error == "ConnectError: boom"
    assert s.inserted == 0
    assert db_session.query(Item).filter_by(source_id=src.id).count() == 0


def test_fetch_etag_writeback_preserved_verbatim(db_session, monkeypatch):
    """模块表硬约束⑤：etag 原样存取（含引号与 W/ 前缀）——截断/变形会让 304 永不命中。"""
    d, src = _mk_source(db_session)
    etag = 'W/"abc-123", "xyz"'
    _patch(monkeypatch, FakeResp(_feed(_item("g1", "https://ex/1", "T1")),
                                 headers={"ETag": etag}))

    fetch_source(db_session, src)
    assert src.etag == etag


# ---------- fetch_source：AC-05.1 账目分桶（等式 + 两类 dup_blocked） ----------


def test_fetch_bucket_equation_feed_internal_guid_collisions(db_session, monkeypatch):
    """AC-05.1：feed 内重复 guid → guid_collisions 计数且计入 dup_blocked（不落行）；
    等式 feed_entries = inserted + dup_blocked + rule_rejected + failed 成立；
    单条失败不中断整源（无静默缺条）。"""
    d, src = _mk_source(db_session)
    _patch(monkeypatch, FakeResp(_feed(
        _item("G1", "https://ex/g1", "T1"),
        _item("G1", "https://ex/g1", "T1-again"),
        _item("G1", "https://ex/g1", "T1-third"),
        _item("G2", "https://ex/g2", "T2"),
    )))

    s = fetch_source(db_session, src)

    assert s.feed_entries == 4
    assert s.inserted == 2  # G1 首条 + G2
    assert s.guid_collisions == 2 and s.dup_blocked == 2
    assert s.rule_rejected == 0 and s.failed == 0
    assert 4 == s.inserted + s.dup_blocked + s.rule_rejected + s.failed
    assert src.last_fetched_at is not None
    g2 = db_session.query(Item).filter_by(source_id=src.id, guid="G2").one()
    assert g2.fetch_status == "FETCHED"


def test_fetch_db_dup_scope_is_per_source(db_session, monkeypatch):
    """AC-05.1：dup_blocked=(source_id,guid) 作用域——本源已存在才拦；他源同 guid
    照常插入。db 命中路径与 feed 内碰撞路径叠加时等式不失平。"""
    d, src_a = _mk_source(db_session, url="https://feeds.example/a.xml")
    src_b = Source(direction_id=d.id, url="https://feeds.example/b.xml", type="rss")
    db_session.add(src_b)
    db_session.commit()
    # 源 B 本源已有 G4；源 A 有 GX（他源）
    db_session.add(Item(source_id=src_b.id, guid="G4", url="https://x/g4",
                        title="t", content_text=_LONG, fetch_status="FETCHED",
                        sanitize_status="PASSED", direction_id=d.id))
    db_session.add(Item(source_id=src_a.id, guid="GX", url="https://x/gx",
                        title="t", content_text=_LONG, fetch_status="FETCHED",
                        sanitize_status="PASSED", direction_id=d.id))
    db_session.commit()

    _patch(monkeypatch, FakeResp(_feed(
        _item("G4", "https://ex/g4", "T4-dup"),
        _item("G5", "https://ex/g5", "T5-new"),
        _item("GX", "https://ex/gx", "TX-cross"),
        _item("G6", "https://ex/g6", "T6"),
        _item("G6", "https://ex/g6", "T6-again"),
        _item("G6", "https://ex/g6", "T6-third"),
    )))
    s = fetch_source(db_session, src_b)

    assert s.feed_entries == 6
    assert s.inserted == 3  # G5 / GX（他源同 guid 不拦）/ G6 首条
    assert s.dup_blocked == 3  # G4 本源 db 拦截 + G6 两次 feed 内碰撞
    assert s.guid_collisions == 2 and s.failed == 0
    assert 6 == s.inserted + s.dup_blocked + s.rule_rejected + s.failed
    assert s.source_id == src_b.id


# ---------- fetch_source：规则链落值（§4.1 + AC-05.1 rule_rejected 桶） ----------


def test_fetch_rules_chain_expired_blacklist_and_row_values(db_session, monkeypatch):
    """rules 口径（黑名单命中标题拒 / 过期拒——max_age_days 参数覆写生效）+
    §4.1 行落值（title/url/published_at/rule_reject_reason/fetch_status 枚举）+
    sanitize_reason 钉死值（AC-06.1）。"""
    d, src = _mk_source(db_session)
    pub = datetime.now(timezone.utc) - timedelta(days=10)
    _patch(monkeypatch, FakeResp(_feed(
        _item("E1", "https://ex/e1", "Old",
              pub=pub.strftime("%a, %d %b %Y %H:%M:%S GMT")),
        _item("E2", "https://ex/e2", "博彩头条"),
        _item("E3", "https://ex/e3", "Short", body="太短"),
    )))

    s = fetch_source(db_session, src, max_age_days=5, blacklist=["博彩"])

    assert s.rule_rejected == 3 and s.inserted == 3 and s.failed == 0
    e1 = db_session.query(Item).filter_by(source_id=src.id, guid="E1").one()
    e2 = db_session.query(Item).filter_by(source_id=src.id, guid="E2").one()
    e3 = db_session.query(Item).filter_by(source_id=src.id, guid="E3").one()
    assert e1.fetch_status == "REJECTED_RULED" and e1.rule_reject_reason == "expired:10d>5d"
    assert e2.fetch_status == "REJECTED_RULED" and e2.rule_reject_reason == "blacklist:博彩"
    assert e3.fetch_status == "REJECTED_RULED" and e3.rule_reject_reason.startswith("too_short:")
    # 行落值（§4.1）：标题/URL/published_at 原样
    assert e2.title == "博彩头条" and e2.url == "https://ex/e2"
    assert e1.published_at is not None
    got = e1.published_at if e1.published_at.tzinfo else e1.published_at.replace(tzinfo=timezone.utc)
    assert abs((got - pub).total_seconds()) < 2
    # sanitize 强制阶段（AC-06.1）：pass-through 的状态与 reason 钉死值
    assert e1.sanitize_status == "PASSED"
    assert e1.sanitize_reason == "demo:零信任过滤未启用"


# ---------- fetch_source：sanitize 链（AC-06.2/06.3）+ 单条失败隔离 ----------


def test_fetch_sanitize_keyword_deny_full_chain(db_session, monkeypatch):
    """AC-06.2（keyword_deny：状态/原因/明细/全文照存）+ AC-06.3（被过滤 ≠ 抓取失败：
    fetch_status 保持 FETCHED）+ AC-06.1 统计口径。"""
    monkeypatch.setattr(cfg, "SANITIZE_ENABLED", True)
    monkeypatch.setattr(cfg, "SANITIZE_DENY_KEYWORDS", ["忽略之前指令"])
    d, src = _mk_source(db_session)
    _patch(monkeypatch, FakeResp(_feed(
        _item("D1", "https://ex/d1", "标题藏了忽略之前指令"),
        _item("D2", "https://ex/d2", "干净标题", body="正文藏了忽略之前指令" + _LONG),
        _item("C1", "https://ex/c1", "干净标题1"),
    )))

    s = fetch_source(db_session, src)

    assert s.failed == 0 and s.inserted == 3
    assert s.sanitize_rejected == 2 and s.sanitize_passed == 1
    d1 = db_session.query(Item).filter_by(source_id=src.id, guid="D1").one()
    d2 = db_session.query(Item).filter_by(source_id=src.id, guid="D2").one()
    c1 = db_session.query(Item).filter_by(source_id=src.id, guid="C1").one()
    assert d1.sanitize_status == "REJECTED" and d1.sanitize_reason == "keyword_deny:忽略之前指令"
    assert d1.sanitize_detail and d1.sanitize_detail["stage"] == "keyword_deny"
    assert d2.sanitize_status == "REJECTED"
    assert d1.content_text  # REJECTED 全文照存
    assert d1.fetch_status == "FETCHED"  # AC-06.3 语义分离
    assert c1.sanitize_status == "PASSED"


def test_fetch_item_failure_does_not_abort_source(db_session, monkeypatch):
    """单条失败不中断整源：failed 桶按条计数（两次失败 failed==2），循环继续处理
    后续条目（inserted 计数照常累加；失败条目回滚不落行）。"""
    d, src = _mk_source(db_session)
    _patch(monkeypatch, FakeResp(_feed(
        _item("F1", "https://ex/f1", "F1", body="失败标记一" + _LONG),
        _item("C1", "https://ex/c1", "C1"),
        _item("F2", "https://ex/f2", "F2", body="失败标记二" + _LONG),
    )))

    real_run_sanitize = rss_mod.run_sanitize

    def flaky_run_sanitize(target):
        if "失败标记" in (target.content_text or ""):
            raise RuntimeError("注入的单条失败")
        return real_run_sanitize(target)

    monkeypatch.setattr(rss_mod, "run_sanitize", flaky_run_sanitize)

    s = fetch_source(db_session, src)
    assert s.failed == 2
    assert s.inserted == 1  # 循环未中断：正常条目照常计数
    assert s.error is None  # 单条失败不升级为源级失败


# ---------- fetch_source：AC-05.2 指纹链（rss 条目正常参与 + NULL 指纹不误判） ----------


def test_fetch_fingerprint_dup_and_null_fingerprint_guard(db_session, monkeypatch):
    """AC-05.2（D15）：同方向跨源同 URL → DUP + duplicate_of 指向指纹命中的那条
    （不得误指无指纹行）；指纹链只比对非空指纹——无 link 条目（fp=NULL）不得经
    NULL 指纹被误判为重复。"""
    d, src_a = _mk_source(db_session, url="https://feeds.example/a.xml")
    src_b = Source(direction_id=d.id, url="https://feeds.example/b.xml", type="rss")
    db_session.add(src_b)
    db_session.commit()
    # 先插一条 fp=NULL 的行（如 web 单页版本条目，G1 豁免先例）——id 更小
    db_session.add(Item(source_id=src_a.id, guid="gw", url="https://x/webpage",
                        title="w", content_text=_LONG, fetch_status="FETCHED",
                        sanitize_status="PASSED", direction_id=d.id, fingerprint=None))
    db_session.commit()
    # 指纹命中的原条目（url 归一化后与抓取条目折叠同指纹）
    fp = url_fingerprint("https://ex.com/post?utm_source=feedA")
    origin = Item(source_id=src_a.id, guid="gA", url="https://ex.com/post?utm_source=feedA",
                  title="Origin", content_text="全文A" * 100, fetch_status="FETCHED",
                  sanitize_status="PASSED", direction_id=d.id, fingerprint=fp)
    db_session.add(origin)
    db_session.commit()

    # E2 用 isPermaLink="false" 的 guid（feedparser 不回填 link）→ url 为空 → fp=None，
    # 才能触达「空指纹不参与指纹链」守卫
    _patch(monkeypatch, FakeResp(_feed(
        _item("gB1", "https://EX.com/post?utm_source=rss#frag", "Dup Entry"),
        '<item><guid isPermaLink="false">tag:2026:x1</guid><title>NoLink</title>'
        f"<description>{_LONG}</description></item>",
    )))
    s = fetch_source(db_session, src_b)

    assert s.inserted == 2 and s.dup_blocked == 0
    e1 = db_session.query(Item).filter_by(source_id=src_b.id, guid="gB1").one()
    assert e1.fetch_status == "DUP" and e1.duplicate_of == origin.id
    assert e1.content_text == _LONG  # 全文照存
    assert e1.fingerprint == fp and e1.direction_id == d.id
    e2 = db_session.query(Item).filter_by(source_id=src_b.id, guid="tag:2026:x1").one()
    assert e2.fetch_status == "FETCHED" and e2.duplicate_of is None  # fp=NULL 不误判


# ---------- F1⑩ 残余复核补测：计数器与账本逐条累积语义 ----------

def test_fetch_second_round_db_dup_accounting(db_session, monkeypatch):
    """同一源二次抓取全部命中库内已有 guid：dup_blocked 逐条累积（本轮 2 条 → 2）。
    计数器必须自增而非覆盖赋值——覆盖会让多条拦截只剩最后一条的计数。"""
    d, src = _mk_source(db_session)
    resp = FakeResp(_feed(_item("G1", "https://ex/g1", "T1"), _item("G2", "https://ex/g2", "T2")))
    _patch(monkeypatch, resp, resp)

    s1 = fetch_source(db_session, src)
    assert s1.inserted == 2 and s1.dup_blocked == 0
    s2 = fetch_source(db_session, src)
    assert s2.inserted == 0
    assert s2.dup_blocked == 2


def test_fetch_sanitize_passed_counts_each_entry(db_session, monkeypatch):
    """多条目同轮通过零信任过滤：sanitize_passed 逐条累积（2 条 → 2），
    覆盖赋值会让多条同轮计数只剩 1。"""
    d, src = _mk_source(db_session)
    _patch(monkeypatch, FakeResp(_feed(
        _item("G1", "https://ex/g1", "T1"), _item("G2", "https://ex/g2", "T2"))))

    s = fetch_source(db_session, src)
    assert s.sanitize_passed == 2 and s.sanitize_rejected == 0
