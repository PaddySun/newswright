"""extract_page_markdown 剥标签兜底测试（BE-5/RG-5）：trafilatura 双段失败后
非空兜底 + _WEB_BODY_MAX_CHARS 截断——P2-3.1 文档-代码背离修正（docstring
「再失败回退剥标签」自此与实现相符），与 RSS 面 _html_to_text 同款失败语义
（两通道一致）。markdown/纯文本抽取成功时兜底不触达（优先级不回退）。

设计依据见 docs/design-index.md「RG-5」（BE-5 增补）。
网络纪律：monkeypatch trafilatura.extract（函数内 import 的属性查找即桩），
零出网。
"""
import app.ingest.web as web_mod
from app.ingest.web import _WEB_BODY_MAX_CHARS, extract_page_markdown


def test_double_extract_failure_falls_back_to_strip(monkeypatch):
    """trafilatura 双段失败（返回 None）→ 剥标签兜底非空、无残留标签。"""
    monkeypatch.setattr("trafilatura.extract", lambda *a, **k: None)
    html = "<html><body><p>第一段正文。</p><p>第二段<b>加粗</b>内容。</p></body></html>"
    out = extract_page_markdown(html)
    assert out.strip()
    assert "第一段正文。" in out and "加粗" in out
    assert "<p>" not in out and "<b>" not in out


def test_extract_exception_falls_back_to_strip(monkeypatch):
    """trafilatura 抛异常（第一形态）同样落兜底——异常与空结果两形同轨。"""
    def boom(*a, **k):
        raise RuntimeError("extract broken")

    monkeypatch.setattr("trafilatura.extract", boom)
    out = extract_page_markdown("<p>仅一段</p>")
    assert out == "仅一段"


def test_strip_fallback_whitespace_normalized(monkeypatch):
    """空白归一：标签置换为空格后连续空白折叠为单空格（同 rss 形态）。"""
    monkeypatch.setattr("trafilatura.extract", lambda *a, **k: None)
    out = extract_page_markdown("<p>a</p>\n\n   <p>b</p>")
    assert out == "a b"


def test_strip_fallback_truncated_to_body_max(monkeypatch):
    """兜底同样受 _WEB_BODY_MAX_CHARS 截断（超长正文截 100KB——与前两段一致）。"""
    monkeypatch.setattr("trafilatura.extract", lambda *a, **k: None)
    huge = "字" * (_WEB_BODY_MAX_CHARS + 5000)
    out = extract_page_markdown(f"<p>{huge}</p>")
    assert len(out) == _WEB_BODY_MAX_CHARS


def test_markdown_success_still_preferred(monkeypatch):
    """markdown 抽取成功直返（兜底不触达——成功路径优先级不回退）。"""
    monkeypatch.setattr("trafilatura.extract",
                        lambda *a, **k: "# 标题\nmarkdown 正文")
    out = extract_page_markdown("<p>x</p>")
    assert out.startswith("# 标题")
