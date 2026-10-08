"""moark rerank 适配器契约：/v1/rerank 请求装配、分批聚合、响应解析与错误语义。

覆盖对象：app/rerank/moark_reranker.py（_rank 分批聚合 + _rank_chunk 单批）。

条款依据（技术书 v1.9 / 产品书 v1.8，溯源见 docs/design-index.md）：
- 模块 docstring 协议要点（V10/V11+EV6 实测链）：POST /v1/rerank
  {model, query, documents: string[], top_n}——top_n 必须显式设为候选数
  （官方默认 3 只回 top3，实测坑在档）；响应 results[] = {index, relevance_score}
  按 index 归还候选、relevance_score ×100 归一化（rerank.base 归一化口径：
  score 0-100）；usage 为 camelCase；25 条/请求上限（26 → 400 实测锚）。
- ADR-8：D-B 请求头（Authorization: Bearer <key> 与 Content-Type: application/json
  ——键名与值形态即条款）；可重试状态语义（429/5xx → RankError 类型化抛出）；
  非 retryable 错误码（≥400）亦须类型化报错不放行。
- 分批语义：_rank 按 max_documents_per_request=25 分批且批间不重不漏，
  criteria 逐批透传（V11 长查询直吃链）。
- 拍板「只用排序不用 band」（M18-M20：官方 band 与 rubric 分带不对齐）：
  排序结论面（id/score）为行为断言面；band 明细值域不在断言面。

红线：全部 httpx MockTransport 打桩，零真实 API 调用。
"""
import json

import httpx

from app.rerank.base import RankCandidate, RankError
from app.rerank.moark_reranker import MoarkRerankerProvider

_REAL_CLIENT = httpx.Client  # 模块导入时绑定：二次 patch 时不叠桩


class _Captured:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.client_kwargs: dict | None = None


def _patch_client(monkeypatch, handler, captured: _Captured):
    def wrapped(request):
        captured.requests.append(request)
        return handler(request)

    def factory(**kwargs):
        captured.client_kwargs = dict(kwargs)
        return _REAL_CLIENT(transport=httpx.MockTransport(wrapped), **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


def _ok_body(doc_count: int) -> dict:
    """按请求 documents 数回 results（index 顺序、分数 0.5）+ camelCase usage。"""
    return {
        "results": [{"index": i, "document": {"text": "t"}, "relevance_score": 0.5}
                    for i in range(doc_count)],
        "usage": {"promptTokens": 10 * doc_count, "totalTokens": 20 * doc_count},
    }


def _cands(n: int) -> list[RankCandidate]:
    return [RankCandidate(id=i, text=f"候选{i}文本") for i in range(n)]


# ---------- 请求装配（payload 四键 + 请求头键名与值形态） ----------

def test_rank_chunk_request_payload_and_headers(db_session, monkeypatch):
    """单批请求体四键逐字（model/query/documents/top_n=候选数）+ Bearer 与
    application/json 两头；结果按 index 归一化 ×100 且 id 归还候选。"""
    captured = _Captured()
    _patch_client(
        monkeypatch, lambda r: httpx.Response(200, json=_ok_body(2)), captured)
    p = MoarkRerankerProvider(db_session, api_key="k-test", model="m-x")
    out = p.rank("方向标准", [RankCandidate(id=7, text="甲文本"),
                             RankCandidate(id=9, text="乙文本")],
                 criteria_key="t1")
    body = json.loads(captured.requests[0].read())
    assert body == {"model": "m-x", "query": "方向标准",
                    "documents": ["甲文本", "乙文本"], "top_n": 2}
    assert captured.requests[0].headers.get("Authorization") == "Bearer k-test"
    assert captured.requests[0].headers.get("Content-Type") == "application/json"
    assert len(out) == 2
    assert [r.id for r in out] == [7, 9]
    assert all(r.score == 50.0 for r in out)  # 0.5 × 100


# ---------- 分批聚合（25 条/请求上限，批间不重不漏，criteria 逐批透传） ----------

def test_rank_splits_into_nonoverlapping_chunks(db_session, monkeypatch):
    """26 候选 → 两个请求（25+1），无重叠无丢失，criteria 逐批透传。"""
    captured = _Captured()
    _patch_client(
        monkeypatch,
        lambda r: httpx.Response(
            200, json=_ok_body(len(json.loads(r.read())["documents"]))),
        captured)
    p = MoarkRerankerProvider(db_session, api_key="k-test")
    out = p.rank("方向标准", _cands(26))
    assert len(captured.requests) == 2
    sizes = [len(json.loads(r.read())["documents"]) for r in captured.requests]
    assert sizes == [25, 1]
    assert all(json.loads(r.read())["query"] == "方向标准" for r in captured.requests)
    assert all(json.loads(r.read())["top_n"] == size
               for r, size in zip(captured.requests, sizes))
    assert len(out) == 26
    assert sorted(r.id for r in out) == list(range(26))  # 不重不漏


# ---------- 响应解析（index 归还/缺分兜底 0/越界 index 跳过不截断） ----------

def test_rank_chunk_response_parsing_edges(db_session, monkeypatch):
    """缺 relevance_score 兜底 0（不虚记满分）；越界/恰边界 index 跳过且不截断其后
    合法结果（失效条目过滤）；score ×100 归一化。"""
    captured = _Captured()
    body = {
        "results": [
            {"index": 0, "relevance_score": 0.9},
            {"index": 2, "relevance_score": 0.5},   # 恰边界（候选仅 2）→ 跳过
            {"index": 5, "relevance_score": 0.5},   # 越界 → 跳过
            {"index": 1},                            # 缺 relevance_score → 兜底 0
        ],
        "usage": {"promptTokens": 1, "totalTokens": 1},
    }
    _patch_client(monkeypatch, lambda r: httpx.Response(200, json=body), captured)
    p = MoarkRerankerProvider(db_session, api_key="k-test")
    out = p.rank("标准", [RankCandidate(id=11, text="甲"),
                          RankCandidate(id=22, text="乙")])
    assert [(r.id, r.score) for r in out] == [(11, 90.0), (22, 0.0)]


# ---------- 错误语义（可重试与致命状态均类型化 RankError） ----------

def test_rank_chunk_retryable_status_raises_rank_error(db_session, monkeypatch):
    """429 → RankError 类型化抛出（错误体语义——类型即契约面；不崩出裸异常）。"""
    captured = _Captured()
    _patch_client(
        monkeypatch, lambda r: httpx.Response(429, text="rate"), captured)
    p = MoarkRerankerProvider(db_session, api_key="k-test")
    try:
        p.rank("标准", _cands(1))
    except RankError:
        pass
    else:
        raise AssertionError("429 必须抛 RankError")


def test_rank_chunk_fatal_status_with_json_body_raises_rank_error(
        db_session, monkeypatch):
    """400（致命域）带合法 JSON 体：仍必须 RankError，不放行为空结果。"""
    captured = _Captured()
    _patch_client(
        monkeypatch,
        lambda r: httpx.Response(400, json={"error": {"code": "1002"}}), captured)
    p = MoarkRerankerProvider(db_session, api_key="k-test")
    try:
        p.rank("标准", _cands(1))
    except RankError:
        pass
    else:
        raise AssertionError("400 必须抛 RankError")
