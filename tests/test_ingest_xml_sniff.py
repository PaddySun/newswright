"""内容嗅探双重判定测试（_looks_like_xml）：从宽口径——任一命中即放行。

条款依据：技术书模块表 ingest/rss 硬约束③（v1.9 从宽口径：正文起始 XML 标记与
Content-Type 声明 xml 双侧任一命中即视为 XML，双侧皆非才判 non_xml_response——
Content-Type 配置错误但正文合法的真源不误杀；WAF 挑战页 HTML 正文+HTML 头双侧
皆不中、正确拦截）；产品书 B1（200+非 XML 挑战页内容嗅探走失败列）。
嗅探前的 UTF-8 BOM 剥离与前导空白剥离是实现「正文起始」判定的组成部分：
BOM/空白后的 XML 标记即正文起始，真源不得因头部装饰被误杀。
设计依据见 docs/design-index.md「B1」。
"""
from app.ingest.rss import _looks_like_xml

_CHALLENGE_BODY = b"<html><body>access denied</body></html>"  # 无任何 XML 标记
_FEED_BODY = b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'


def test_bom_prefixed_xml_body_accepted_despite_html_content_type():
    """UTF-8 BOM 前缀的真源：剥 BOM 后正文起始标记命中即放行（头部错配不误杀）。"""
    assert _looks_like_xml(b"\xef\xbb\xbf" + _FEED_BODY, "text/html") is True


def test_leading_whitespace_xml_body_accepted_despite_html_content_type():
    """正文起始带前导空白的真源（PHP feed 常见）：起始标记嗅探先剥前导空白。"""
    assert _looks_like_xml(b"\n\n   " + _FEED_BODY, "text/html") is True


def test_xml_content_type_declared_body_accepted():
    """Content-Type 声明 xml 即放行：正文起始无标记但头部声明合法的真源。"""
    assert _looks_like_xml(_CHALLENGE_BODY, "application/xml; charset=utf-8") is True


def test_challenge_page_double_miss_rejected():
    """挑战页防御面保持：正文与头部双侧皆不中 → 判非 XML。"""
    assert _looks_like_xml(_CHALLENGE_BODY, "text/html") is False
