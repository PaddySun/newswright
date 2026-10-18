"""热榜条目数据卫生与排序分数精度契约（C5-3 D 类四条站长裁定转 C 落地，2026-10-18）。

- 热榜聚合响应仅保留 dict 且 title 非空白的条目——空标题/空白标题/缺键
  条目必须剔除（数据卫生：热榜面板条目恒有可呈现标题）。杀灭把过滤兜底
  空串改为恒真字面量的变异（无标题条目漏进库）。
  设计依据见 docs/design-index.md「HR-5」。
- moark 重排分数精度=round(×100, 1) 一位小数——与 bocha_reranker 同形态
  的归一化口径子类声明（score 有生产消费方：rank_score 存档与
  rank_exclude_below 阈值边界，整数化会漂移 75.51→76 类边界）。杀灭把
  round 精度变异（整数化/两位化）的三条同族变异。
  依据：rerank 归一化口径子类声明（app/rerank/base.py 模块口径 +
  C5-3 D 类站长裁定转 C，2026-10-18）。
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.rerank.base import RankCandidate
from app.rerank.moark_reranker import MoarkRerankerProvider


class _StubResp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_hot_fetch_drops_blank_title_entries(monkeypatch, db_session: Session):
    """空标题/空白标题/缺 title 键/非 dict 聚合条目全部剔除，仅留可呈现条目。"""
    from app.hot import service as hot

    body = {"items": [
        {"title": "正常条目", "url": "https://a"},
        {"title": "", "url": "https://b"},
        {"title": "   ", "url": "https://c"},
        {"url": "https://d"},
        "not-a-dict",
    ]}
    monkeypatch.setattr(hot, "get_json", lambda url, **kw: _StubResp(body))
    kept = hot.fetch_platform("weibo", db=db_session)
    assert [it["title"] for it in kept] == ["正常条目"]


def test_rerank_score_one_decimal_precision(monkeypatch, db_session: Session):
    """score=round(×100,1) 一位小数：75.51 不得整数化（76）也不得两位化（75.51）。"""
    from app.rerank import moark_reranker as mr

    body = {"results": [{"index": 0, "relevance_score": 0.7551}],
            "usage": {"promptTokens": 3, "totalTokens": 5}, "model": "stub"}
    monkeypatch.setattr(mr, "post_json", lambda *a, **kw: _StubResp(body))
    provider = MoarkRerankerProvider(db_session)
    results = provider.rank("方向标准", [RankCandidate(id=1, text="候选文本")])
    assert len(results) == 1
    assert results[0].score == 75.5
