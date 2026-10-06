"""热榜关键词提炼失败的标题分词兜底统计纪律。

兜底语义（hot.service 模块 docstring 钉）：只用真实标题统计、不含任何固定兜底词；
空标题跳过（不截断统计循环）、纯数字段丢弃后继续；ASCII 词原样小写、中文连续段
切 2-gram、去停用词；按出现频次降序取 top-15。
设计依据见 docs/design-index.md「AC-05.6」「R2」。
"""
from app.hot.service import _fallback_keywords_from_titles
from app.models import HotTopic


def _t(title):
    return HotTopic(platform="p", rank=1, title=title)


def test_empty_title_topic_yields_no_tokens():
    """空/无标题条目跳过：不产生任何兜底 token（不含固定兜底词）。"""
    assert _fallback_keywords_from_titles([_t(None), _t("   ")]) == []


def test_stats_continue_past_empty_title_topic():
    """空标题只跳过自身，不截断后续真实标题的统计。"""
    kws = _fallback_keywords_from_titles([_t(None), _t("model model")])
    assert kws == ["model"]


def test_digit_segments_skipped_and_stats_continue():
    """纯数字段丢弃后继续分词（后续词段照常统计）。"""
    kws = _fallback_keywords_from_titles([_t("2024 model")])
    assert kws == ["model"]


def test_ascii_keyword_order_follows_term_frequency():
    """ASCII 词按出现频次降序（频次坍缩为 1 时顺序失真）。"""
    topics = [_t("alpha beta alpha"), _t("beta beta")]
    # beta 3 次 > alpha 2 次
    assert _fallback_keywords_from_titles(topics)[:2] == ["beta", "alpha"]


def test_bigram_keyword_order_follows_term_frequency():
    """中文 2-gram 同按频次降序。"""
    # 人工智能智能 → 人工/工智/智能/智能：智能 2 次居首
    kws = _fallback_keywords_from_titles([_t("人工智能智能")])
    assert kws[0] == "智能"
    assert "人工" in kws
