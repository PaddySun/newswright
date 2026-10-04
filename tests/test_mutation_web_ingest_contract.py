"""C1-3 变异分诊批次 4 补强测试（app.ingest.web 132 条 C 类）。

> 追溯注记：本文件原名 tests/test_mutation_c1_3.py（原批次代号见文件名），按对象重命名于 F1⑫治理批。

缺口根源：fetch_web_source 主链（变更检测记账 / 304 短跳 / 条目落库全列 / LLM 抽取
通道 / 富化成本边界 / sanitize 记账）此前只有 4 个覆盖测试。断言全部来自设计书
v1.5 条款：
- 产品书 AC-05.3（guid=<归一化配置URL>#v-<H2前12位>、URL 分量=配置 URL 非最终
  重定向 URL（B7）、change_type=content_changed、无变更 not_modified=true 且
  inserted=0）+ AC-05.3 括号明示的 follow_redirects 语义；
- 技术书模块表 ingest/web 硬约束（304 判定先于 raise_for_status；etag 原样回传
  含引号/W/ 前缀——截断会让 304 永不命中）+ §4.1 source/item 行（etag/content_hash、
  fetch_status、direction_id+fingerprint 索引、rule_reject_reason、sanitize 三列）；
- AC-05.1 分桶口径（inserted=落行含 DUP；dup_blocked=(source_id,guid) 拦截；failed
  不落行；rule_rejected 落行——每源账目）+ AC-05.2（D15 方向内 DUP + duplicate_of +
  全文照存）+ AC-06.1/06.2（sanitize PASSED/REJECTED + keyword_deny 原因 + detail
  + 全文照存）；
- AC-04.8（富化：成本只花在被拒条目上——too_short 边界即规则边界；
  「条目 URL=页面 URL 不富化」护栏依赖 page_url 传递）；
- 技术书 §4.2「外部调用一律显式超时」（httpx.Client 显式 timeout）；
- G1 追认先例：web 单页版本条目豁免指纹链（apply_fp=False，B7 全量保存语义）。

网络纪律：全部经 fake httpx.Client（沿用 tests/test_web_monitor.py 形态）+ mock
llm_extract_entries/_enrich_entry_content，不真联网。
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import app.config as cfg
import app.ingest.web as web
from app.ingest.fingerprint import url_fingerprint
from app.ingest.web import fetch_web_source
from app.models import Direction, Item, Source

HTML_A = "<html><head><title>News A</title></head><body>" + "<p>" + "内容A" * 100 + "</p></body></html>"
HTML_B = "<html><head><title>News B</title></head><body>" + "<p>" + "内容B变化" * 100 + "</p></body></html>"
# 带旧发布日期的页面（htmldate 可抽取；2020 年 → 过期规则 30 天必拒）
HTML_OLD = (
    '<html><head><title>Old</title>'
    '<meta property="article:published_time" content="2020-01-01T08:00:00Z"></head>'
    "<body><article>" + "<p>这是一段足够长的历史正文内容。</p>" * 40 + "</article></body></html>"
)


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
    def __init__(self, text, status_code=200, headers=None):
        self.text = text
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})

    def raise_for_status(self):
        # 与真实 httpx 对齐：3xx/4xx/5xx 一律抛（设计书模块表硬约束①的实测坑——
        # 304 判定必须先于 raise_for_status，否则 304 被当失败记账）
        if self.status_code >= 300:
            raise httpx.HTTPStatusError(f"{self.status_code}", request=None, response=None)  # type: ignore


def _patch(monkeypatch, *responses):
    RecordingClient.responses = list(responses)
    RecordingClient.calls = []
    RecordingClient.init_kwargs = {}
    monkeypatch.setattr(web.httpx, "Client", RecordingClient)


def _mk_source(db_session, **config):
    d = Direction(name="DW", prompt="p", threshold=60)
    db_session.add(d)
    db_session.commit()
    src = Source(direction_id=d.id, url="https://ex/page", type="web",
                 source_config=(config or None))
    db_session.add(src)
    db_session.commit()
    return src


def _long_text(n_chars=300, mark="正文"):
    return (mark * ((n_chars // len(mark)) + 1))[:n_chars]


# ---------- 单页主链：请求契约 + 条目全列 + 源记账 ----------


def test_first_fetch_request_contract_item_row_and_source_bookkeeping(db_session, monkeypatch):
    src = _mk_source(db_session)
    _patch(monkeypatch, FakeResp(HTML_A))

    s = fetch_web_source(db_session, src)

    # 请求契约：显式超时（§4.2）+ 重定向跟随（AC-05.3 B7 括号）+ 目标=配置 URL
    assert "timeout" in RecordingClient.init_kwargs and RecordingClient.init_kwargs["timeout"] is not None
    assert RecordingClient.init_kwargs.get("follow_redirects") is True
    assert len(RecordingClient.calls) == 1
    assert RecordingClient.calls[0]["url"] == "https://ex/page"

    # stats 记账归因 + 变更类型（AC-05.1 每源账目 / AC-05.3）
    assert s.source_id == src.id and s.url == "https://ex/page"
    assert s.inserted == 1 and s.not_modified is False and s.error is None
    assert s.extra["change_type"] == "first_fetch"

    # 条目全列：URL 分量=配置 URL（AC-05.3 B7）、FETCHED（§4.1 fetch_status）、
    # 正文=抽取结果（模块表 trafilatura 抽取）、direction_id（D15 作用域）、
    # 单页版本条目豁免指纹链（G1 先例，fingerprint=None）
    it = db_session.query(Item).filter_by(source_id=src.id).one()
    assert it.url == "https://ex/page"
    assert it.fetch_status == "FETCHED"
    assert it.content_text == web.extract_page_markdown(HTML_A) and it.content_text
    assert it.direction_id == src.direction_id
    assert it.fingerprint is None
    assert it.sanitize_status == "PASSED"

    # 源记账：content_hash=内容 sha256（§4.1 source 行）、last_fetched_at 落账
    import hashlib
    assert src.content_hash == hashlib.sha256(HTML_A.encode("utf-8")).hexdigest()
    assert src.last_fetched_at is not None


def test_304_shortcircuit_conditional_headers_and_bookkeeping(db_session, monkeypatch):
    src = _mk_source(db_session)
    _patch(monkeypatch, FakeResp(HTML_A, headers={"ETag": 'W/"v1"', "Last-Modified": "Tue, 01 Jan 2026 00:00:00 GMT"}))
    assert fetch_web_source(db_session, src).inserted == 1

    # 二轮：条件请求头原样回传 etag（模块表硬约束：截断/变形会让 304 永不命中）
    src2 = db_session.merge(src)
    _patch(monkeypatch, FakeResp(HTML_A, status_code=304, headers={"ETag": 'W/"v1"'}))
    s2 = fetch_web_source(db_session, src2)
    assert RecordingClient.calls[0]["headers"].get("If-None-Match") == 'W/"v1"'
    assert s2.not_modified is True and s2.inserted == 0 and s2.error is None
    assert s2.extra.get("change_type") is None
    assert src2.last_fetched_at is not None

    # 三轮：服务端 200 但 etag 未变 → not_modified 短跳；源记账不得被清掉
    # （content_hash/etag 保持，否则下一轮会误判 first_fetch 重入库，AC-05.3）
    src3 = db_session.merge(src)
    _patch(monkeypatch, FakeResp(HTML_A, headers={"ETag": 'W/"v1"'}))
    s3 = fetch_web_source(db_session, src3)
    assert s3.not_modified is True and s3.inserted == 0
    assert src3.content_hash is not None
    assert src3.last_fetched_at is not None


def test_etag_change_with_content_change_is_detected(db_session, monkeypatch):
    """etag 变了即内容变更：不得因旧 etag 存在而误判 not_modified（AC-05.3）。"""
    src = _mk_source(db_session)
    _patch(monkeypatch, FakeResp(HTML_A, headers={"ETag": 'W/"v1"'}))
    fetch_web_source(db_session, src)

    src2 = db_session.merge(src)
    _patch(monkeypatch, FakeResp(HTML_B, headers={"ETag": 'W/"v2"'}))
    s2 = fetch_web_source(db_session, src2)
    assert s2.not_modified is False
    assert s2.inserted == 1 and s2.extra["change_type"] == "content_changed"


# ---------- 规则链：过期判定依赖页面日期（_published_date 主链） ----------


def test_expired_page_date_rejected_with_reason(db_session, monkeypatch):
    """模块表 rules「过期（缺日期不拒）」+ §4.1 rule_reject_reason：页面旧日期
    必须被抽取（_published_date）并传给规则链（apply_rules）——断链即漏拒。"""
    src = _mk_source(db_session)
    _patch(monkeypatch, FakeResp(HTML_OLD))
    s = fetch_web_source(db_session, src)

    it = db_session.query(Item).filter_by(source_id=src.id).one()
    assert it.fetch_status == "REJECTED_RULED"
    assert it.rule_reject_reason and it.rule_reject_reason.startswith("expired:")
    assert it.published_at is not None and it.published_at.year == 2020
    assert s.rule_rejected == 1
    # REJECTED 条目全文照存（sanitize 全量保存原则）
    assert it.content_text


# ---------- LLM 抽取通道：调用契约 + 指纹/DUP + 记账（AC-05.2/D15、§4.1 llm_extract） ----------


def _mock_llm(monkeypatch, entries):
    calls = []

    def fake_llm_extract(db, *, page_url, content_text, extraction_prompt):
        calls.append({"db": db, "page_url": page_url, "content_text": content_text,
                      "extraction_prompt": extraction_prompt})
        return entries if entries is None else list(entries)

    monkeypatch.setattr(web, "llm_extract_entries", fake_llm_extract)
    return calls


def test_llm_path_call_contract_fingerprint_and_dup(db_session, monkeypatch):
    src = _mk_source(db_session, llm_extract=True, extraction_prompt="抽取列表")
    d_id = src.direction_id
    # 同方向源 B 已有 item：URL 与 e1 相同（AC-05.2 D15：方向内同 URL 指纹 → DUP）
    src_b = Source(direction_id=d_id, url="https://ex/other", type="rss")
    db_session.add(src_b)
    db_session.commit()
    from app.ingest.rss import normalize_url
    dup_url = normalize_url("https://ex/article-1?utm_source=x")
    b_item = Item(source_id=src_b.id, guid="g-b", url=dup_url, title="t",
                  content_text=_long_text(), direction_id=d_id,
                  fingerprint=url_fingerprint(dup_url))
    db_session.add(b_item)
    db_session.commit()

    entries = [
        web.WebPayload(guid="g1", url=dup_url, title="E1", published_at=None,
                       content_text=_long_text()),
        web.WebPayload(guid="g2", url="https://ex/article-2", title="E2", published_at=None,
                       content_text=_long_text()),
        # 两条过期条目（40 天前）：验证规则链收到 published_at（模块表 rules 过期）
        web.WebPayload(guid="g3", url="https://ex/article-3", title="E3",
                       published_at=datetime.now(timezone.utc) - timedelta(days=40),
                       content_text=_long_text()),
        web.WebPayload(guid="g4", url="https://ex/article-4", title="E4",
                       published_at=datetime.now(timezone.utc) - timedelta(days=41),
                       content_text=_long_text()),
    ]
    calls = _mock_llm(monkeypatch, entries)
    _patch(monkeypatch, FakeResp(HTML_A))

    s = fetch_web_source(db_session, src)

    # 调用契约：llm_extract 开关生效（§4.1 source_config.llm_extract）、
    # page_url=配置 URL（AC-05.3 B7）、正文/抽取提示词透传（模块表 LLM 抽取）
    assert len(calls) == 1
    assert calls[0]["db"] is db_session
    assert calls[0]["page_url"] == "https://ex/page"
    assert calls[0]["content_text"] == web.extract_page_markdown(HTML_A)
    assert calls[0]["extraction_prompt"] == "抽取列表"

    e1 = db_session.query(Item).filter_by(source_id=src.id, guid="g1").one()
    e2 = db_session.query(Item).filter_by(source_id=src.id, guid="g2").one()
    # D15：同方向同 URL 指纹 → DUP + duplicate_of + 全文照存 + 指纹列落值
    assert e1.fetch_status == "DUP" and e1.duplicate_of == b_item.id
    assert e1.content_text == entries[0].content_text
    assert e1.fingerprint == url_fingerprint(dup_url)
    assert e1.direction_id == d_id
    assert e2.fetch_status == "FETCHED"
    assert e2.fingerprint == url_fingerprint("https://ex/article-2")
    # 过期两条被拒（落行 + 计数，AC-05.1 rule_rejected 桶）
    e3 = db_session.query(Item).filter_by(source_id=src.id, guid="g3").one()
    assert e3.fetch_status == "REJECTED_RULED" and e3.rule_reject_reason.startswith("expired:")

    assert s.inserted == 4 and s.failed == 0 and s.error is None
    assert s.rule_rejected == 2
    assert s.sanitize_passed == 4


def test_llm_after_single_page_no_null_fingerprint_false_dup(db_session, monkeypatch):
    """D15 边界：指纹链只比对非空指纹——单页版本条目（fp=NULL，G1 豁免）不得被
    后续 LLM 条目经 NULL 指纹误判为重复。"""
    src = _mk_source(db_session)
    _patch(monkeypatch, FakeResp(HTML_A))
    fetch_web_source(db_session, src)  # 单页条目：fp=NULL（G1 先例）

    src2 = db_session.merge(src)
    src2.source_config = {"llm_extract": True}
    db_session.commit()
    entries = [web.WebPayload(guid="g9", url="https://ex/unique-9", title="E9",
                              published_at=None, content_text=_long_text())]
    _mock_llm(monkeypatch, entries)
    _patch(monkeypatch, FakeResp(HTML_B))

    s = fetch_web_source(db_session, src2)
    it = db_session.query(Item).filter_by(source_id=src.id, guid="g9").one()
    assert it.fetch_status == "FETCHED"
    assert it.fingerprint == url_fingerprint("https://ex/unique-9")
    assert s.inserted == 1


def test_llm_double_failure_accounting(db_session, monkeypatch):
    """llm_extract_entries 返回 None（两次失败）→ failed 落账 + error 留痕、不落行
    （AC-05.1 failed 桶不落行；失败原因如实记录——AC-04.2 last_error 证据纪律）。"""
    src = _mk_source(db_session, llm_extract=True)
    calls = _mock_llm(monkeypatch, None)  # 两次抽取均失败
    _patch(monkeypatch, FakeResp(HTML_A), FakeResp(HTML_B))

    s1 = fetch_web_source(db_session, src)
    assert s1.failed == 1 and s1.inserted == 0 and s1.error

    src2 = db_session.merge(src)
    s2 = fetch_web_source(db_session, src2)
    assert s2.failed == 1  # failed 桶按轮记账（每轮独立 stats）
    assert len(db_session.query(Item).filter_by(source_id=src.id).all()) == 0


def test_llm_duplicate_guid_within_round_counts_collisions(db_session, monkeypatch):
    """AC-05.1：同一轮内重复 guid → guid_collisions 计数（不落行、不计 dup_blocked）。"""
    src = _mk_source(db_session, llm_extract=True)
    ent = [web.WebPayload(guid="g-same", url=f"https://ex/a{i}", title=f"E{i}",
                          published_at=None, content_text=_long_text()) for i in range(3)]
    _mock_llm(monkeypatch, ent)
    _patch(monkeypatch, FakeResp(HTML_A))

    s = fetch_web_source(db_session, src)
    assert s.inserted == 1
    assert s.guid_collisions == 2
    assert s.dup_blocked == 0


def test_llm_existing_guids_blocked_per_source_scope(db_session, monkeypatch):
    """AC-05.1：dup_blocked=(source_id,guid) 拦截——作用域=本源；他源同 guid 不拦
    （照常插入），本源已存在才计 dup_blocked。"""
    src = _mk_source(db_session, llm_extract=True)
    d_id = src.direction_id
    src_b = Source(direction_id=d_id, url="https://ex/other", type="rss")
    db_session.add(src_b)
    db_session.commit()
    db_session.add(Item(source_id=src_b.id, guid="G1", url="https://x/1",
                        title="t", content_text=_long_text()))
    for g in ("G2", "G3"):
        db_session.add(Item(source_id=src.id, guid=g, url=f"https://x/{g}",
                            title="t", content_text=_long_text()))
    db_session.commit()

    ent = [web.WebPayload(guid=g, url=f"https://ex/{g}", title=g,
                          published_at=None, content_text=_long_text())
           for g in ("G1", "G2", "G3")]
    _mock_llm(monkeypatch, ent)
    _patch(monkeypatch, FakeResp(HTML_A))

    s = fetch_web_source(db_session, src)
    assert s.inserted == 1  # 仅 G1（他源同 guid 不拦）
    assert s.dup_blocked == 2  # G2/G3 本源已存在
    assert db_session.query(Item).filter_by(source_id=src.id, guid="G1").one() is not None


# ---------- 富化：成本边界（AC-04.8）与调用契约 ----------


def test_enrich_boundary_only_for_rule_rejected_length(db_session, monkeypatch):
    """AC-04.8：富化成本只花在被拒条目上——触发边界与 too_short 规则一致
    （len < RULE_MIN_BODY_CHARS 才富化；恰在边界的不富化）。page_url 必须传
    配置 URL（「条目 URL=页面 URL 不富化」护栏依赖它）。"""
    min_chars = cfg.RULE_MIN_BODY_CHARS
    src = _mk_source(db_session, llm_extract=True)
    entries = [
        web.WebPayload(guid="ok", url="https://ex/article-ok", title="OK",
                       published_at=None, content_text="x" * min_chars),  # 恰在边界：规则放行
        web.WebPayload(guid="short", url="https://ex/article-short", title="S",
                       published_at=None, content_text="y" * (min_chars - 1)),  # 拒：富化
    ]
    _mock_llm(monkeypatch, entries)
    enrich_calls = []

    def fake_enrich(entry, *, page_url):
        enrich_calls.append({"entry": entry, "page_url": page_url})
        return "富化后的全文" + _long_text(300)

    monkeypatch.setattr(web, "_enrich_entry_content", fake_enrich)
    _patch(monkeypatch, FakeResp(HTML_A))

    s = fetch_web_source(db_session, src)

    assert len(enrich_calls) == 1
    assert enrich_calls[0]["entry"] is entries[1]
    assert enrich_calls[0]["page_url"] == "https://ex/page"
    ok_item = db_session.query(Item).filter_by(source_id=src.id, guid="ok").one()
    short_item = db_session.query(Item).filter_by(source_id=src.id, guid="short").one()
    assert ok_item.content_text == "x" * min_chars  # 边界条目未被富化改写
    assert short_item.content_text.startswith("富化后的全文")  # 富化结果入库
    assert s.inserted == 2


# ---------- sanitize 链：KeywordDeny 全链记账（AC-06.1/06.2） ----------


def test_sanitize_keyword_deny_rejects_and_accounts(db_session, monkeypatch):
    monkeypatch.setattr(cfg, "SANITIZE_ENABLED", True)
    monkeypatch.setattr(cfg, "SANITIZE_DENY_KEYWORDS", ["禁词"])
    src = _mk_source(db_session, llm_extract=True)
    entries = [
        web.WebPayload(guid="d1", url="https://ex/d1", title="标题含禁词了",
                       published_at=None, content_text=_long_text()),
        web.WebPayload(guid="d2", url="https://ex/d2", title="干净标题",
                       published_at=None, content_text="正文藏了禁词在内容里" + _long_text()),
        web.WebPayload(guid="c1", url="https://ex/c1", title="干净标题1",
                       published_at=None, content_text=_long_text()),
        web.WebPayload(guid="c2", url="https://ex/c2", title="干净标题2",
                       published_at=None, content_text=_long_text()),
    ]
    _mock_llm(monkeypatch, entries)
    _patch(monkeypatch, FakeResp(HTML_A))

    s = fetch_web_source(db_session, src)

    d1 = db_session.query(Item).filter_by(source_id=src.id, guid="d1").one()
    d2 = db_session.query(Item).filter_by(source_id=src.id, guid="d2").one()
    assert d1.sanitize_status == "REJECTED" and d1.sanitize_reason == "keyword_deny:禁词"
    assert d1.sanitize_detail and d1.sanitize_detail["matched_in"] == "title"
    assert d2.sanitize_status == "REJECTED" and d2.sanitize_reason == "keyword_deny:禁词"
    assert d2.sanitize_detail["matched_in"] == "content"
    # REJECTED 全文照存（AC-06.2）
    assert d1.content_text == entries[0].content_text
    c1 = db_session.query(Item).filter_by(source_id=src.id, guid="c1").one()
    assert c1.sanitize_status == "PASSED"
    assert s.sanitize_rejected == 2 and s.sanitize_passed == 2


# ---------- F1⑩ 残余复核补测：单页条目标题 / 版本条目豁免指纹链的 DUP 边界 ----------

def test_web_first_fetch_item_title_from_page(db_session, monkeypatch):
    """单页条目标题取自页面 <title> 抽取结果——标题链路任一环丢失（页 title 抽取
    或 payload 装配）都会让条目落空标题。"""
    src = _mk_source(db_session)
    _patch(monkeypatch, FakeResp(HTML_A))

    fetch_web_source(db_session, src)

    it = db_session.query(Item).filter_by(source_id=src.id).one()
    assert it.title == "News A"


def test_web_content_change_creates_fetched_entry_not_dup(db_session, monkeypatch):
    """监测页内容变化 → 新版本条目照常入库：版本条目豁免指纹链（fingerprint=None），
    不得与库内任何 NULL 指纹行做指纹比对判 DUP——B7 全量保存语义要求新条目
    fetch_status=FETCHED、duplicate_of 为空。"""
    src = _mk_source(db_session)
    _patch(monkeypatch, FakeResp(HTML_A))
    fetch_web_source(db_session, src)
    _patch(monkeypatch, FakeResp(HTML_B))
    fetch_web_source(db_session, src)

    items = db_session.query(Item).filter_by(source_id=src.id).order_by(Item.id).all()
    assert len(items) == 2
    assert items[1].fetch_status == "FETCHED"
    assert items[1].duplicate_of is None
