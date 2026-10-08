"""搜索通道装配契约：provider 解析会话归因、全文兜底空值保真、sanitize 标题入链。

覆盖对象：app/search/pipeline.py fetch_search_source 的输入装配三处。

条款依据（技术书 v1.9 / 产品书 v1.8，溯源见 docs/design-index.md）：
- 构造/解析全参透传先例族（C1-8 构造透传、C3-4 default_provider/db 归因断裂判 C）：
  registry.get_provider(name, db) 的 db 为 provider 出网 UA 策略读取面——会话归因断裂
  即策略失联（R9）。
- pipeline docstring 全文口径：item 全文 = content（缺则 snippet）——双缺时兜底为空串，
  不得注入占位文本（落行全文照存保真，AC-06.3 同源语义）。
- AC-06.1 零信任过滤强制阶段：SanitizeTarget 三字段（title/content_text/url）为
  sanitize 链输入快照——标题承载关键词拒绝与注入特征检测的扫描面，缺标题即漏检。
- AC-05.1 账目分桶（F2 W3 统一口径）为断言背景（rule_rejected/sanitize_rejected 桶）。

红线：provider 全打桩（registry.get_provider 打桩或桩类），零真实 API 调用；
零生产代码改动。
"""
from app.models import Item
from app.search.base import SearchResult

import app.search.pipeline as search_pipeline
import app.search.registry as search_registry


def _mk_source(db, name, cfg_extra=None):
    from app.models import Direction, Source

    d = Direction(name=f"ASM-{name}", prompt="p", threshold=60)
    db.add(d)
    db.flush()
    cfg_ = {"keyword": f"词{name}", "provider": "fakeprov", "group": "g1", "count": 3}
    cfg_.update(cfg_extra or {})
    src = Source(direction_id=d.id, url=f"search://fakeprov/{name}", type="search",
                 source_config=cfg_)
    db.add(src)
    db.commit()
    return src


def _patch_provider(monkeypatch, results=None, capture=None):
    class P:
        name = "fakeprov"

        def search(self, q, count=10, **kw):
            return list(results or [])

    def factory(name, db=None):
        if capture is not None:
            capture.append((name, db))
        return P()

    monkeypatch.setattr(search_registry, "get_provider", factory)


def _result(content="", snippet=""):
    return SearchResult(title="标题", url="https://ex.com/a", snippet=snippet,
                        content=content,
                        raw={"k": 1})


def test_fetch_search_source_passes_db_to_registry(db_session, monkeypatch):
    """registry.get_provider 收到会话（UA 策略读取面归因——db 断裂即策略失联）。"""
    src = _mk_source(db_session, "DB1")
    seen = []
    _patch_provider(monkeypatch, results=[], capture=seen)
    search_pipeline.fetch_search_source(db_session, src)
    assert len(seen) == 1
    assert seen[0][0] == "fakeprov"
    assert seen[0][1] is db_session


def test_fetch_search_source_empty_fulltext_stays_empty(db_session, monkeypatch):
    """content 与 snippet 双缺：item 全文兜底为空串（不注入占位文本；too_short
    规则拒绝照常落行，落行全文照存保真）。"""
    src = _mk_source(db_session, "FT1")
    _patch_provider(monkeypatch, results=[_result(content="", snippet="")])
    stats = search_pipeline.fetch_search_source(db_session, src)
    it = db_session.query(Item).filter_by(source_id=src.id).one()
    assert it.content_text == ""
    assert it.fetch_status == "REJECTED_RULED"  # 空正文过不了 too_short
    assert stats.rule_rejected == 1 and stats.inserted == 0


def test_fetch_search_source_sanitize_scans_title(db_session, monkeypatch):
    """sanitize 链输入含标题：deny 关键词命中标题即拒（标题缺失即漏检）。"""
    monkeypatch.setattr(search_pipeline.config, "SANITIZE_ENABLED", True)
    monkeypatch.setattr(search_pipeline.config, "SANITIZE_DENY_KEYWORDS", ["禁词"])
    src = _mk_source(db_session, "ST1")
    r = SearchResult(title="禁词标题", url="https://ex.com/b",
                     snippet="摘要" * 150, content="全文" * 200, raw={})
    _patch_provider(monkeypatch, results=[r])
    stats = search_pipeline.fetch_search_source(db_session, src)
    it = db_session.query(Item).filter_by(source_id=src.id).one()
    assert it.sanitize_status == "REJECTED"
    assert it.sanitize_reason == "keyword_deny:禁词"
    assert stats.sanitize_rejected == 1 and stats.sanitize_passed == 0
