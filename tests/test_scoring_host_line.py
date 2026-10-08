"""打分提示词来源域名行契约测试。

覆盖口径（设计依据见 docs/design-index.md「US-06 打分域」——模块 docstring
语境即锚）：正常 URL 的条目在打分提示词的【来源域名】行承载真实域名，
不得退化为「未知」占位（域名行是打分 prompt 宿主上下文的功能性组成——
or→and 变异使正常 URL 的域名行恒「未知」，宿主上下文功能整体失效）。

纯函数断言，零出网；生产代码零改动。
"""
from types import SimpleNamespace

from app.scoring.service import _host


def _item(url):
    return SimpleNamespace(url=url)


def test_host_extracts_domain_from_normal_url():
    """正常 http(s) URL：来源域名行=netloc 原文。"""
    assert _host(_item("https://news.example.com/a/story")) == "news.example.com"
    assert _host(_item("http://another.example.org/path?x=1")) == "another.example.org"


def test_host_falls_back_only_for_missing_url():
    """「未知」占位仅属于 URL 缺失/无域名形态——正常 URL 不得落入。"""
    assert _host(_item(None)) == "未知"
    assert _host(_item("")) == "未知"
