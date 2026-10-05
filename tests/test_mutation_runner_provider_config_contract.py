"""C1-9a 分诊批次 11（收官补扫）：pipeline.runner / providers.deepseek / config 幸存变异体闭合。

> 追溯注记：本文件原名 tests/test_mutation_c1_9a.py（原批次代号见文件名），按对象重命名于 F1⑫治理批。

条款依据（技术书 v1.7 / 产品书 v1.6，引用见各测试 docstring）：
- §4.2 状态机：PENDING/RUNNING/DONE/FAILED 枚举、CAS 终态迁移（WHERE id+status，迟到写拒绝）、
  P0-1 回收 30/60/120 分档（"超"=严格大于）、任务状态一律落库（DB 即队列）。
- 模块 docstring：fetch_round 逐源 kind=fetch 任务、防重叠同 kind、幂等打分
  （只对 FETCHED+PASSED 且无 OK 分的条目调 LLM，FAILED 下轮续跑）、单条异常不中断整轮。
- ADR-8：重试 ≤2（max_retries=2）、计量旁路（_post 写 _last_meter）、thinking 档位路由
  （思考档不吃 JSON mode、max_tokens 缺省 64K 不硬设）、finish_reason 语义、D-B Bearer 构造契约。
- AC-05.1 账目分桶（_fetch_stats_dict 九字段=DT-5 payload.stats）；AC-20.2 回收；AC-20.3 退避
  （成功清零/失败+1、每 BACKOFF_PROBE_EVERY 轮放行探测）；AC-07.x 打分幂等/统计吻合/
  部分成功仍 DONE 下轮续跑/JSONParseError 分账。
- D18 凭据纪律（_require 缺失 SystemExit）；G0 C3 自包含（.env 双形态容错解析、env 读取、布尔口径）。
- 归因先例（W5/C1-8）：summary/payload/skipped 键面按设计钉死口径断言。

红线：provider/抓取器/打分器全部打桩，零真实 API 调用；零生产代码改动。
"""
from datetime import datetime, timedelta, timezone

import pytest

import app.config as cfg
import app.pipeline.runner as runner_mod
import app.scoring.service as scoring_service
import app.search.pipeline as search_pipeline
from app.config import _get, _get_bool, _require, _tolerant_env_parse
from app.models import Direction, Item, PipelineTask, ScoreResult, Source
from app.pipeline.runner import (
    _fetch_one,
    _fetch_stats_dict,
    _finish,
    _update_source_health,
    enqueue_fetch_round,
    fetch_round,
    process_fetch_round,
    reclaim_stale_tasks,
    round_busy,
    score_round,
)
from app.providers.base import ProviderError
from app.providers.deepseek import DeepSeekProvider


# ---------- 共享工厂 / 桩体 ----------

_FIXED_NOW = datetime(2026, 10, 4, 8, 0, 0, tzinfo=timezone.utc)


class _FixedDatetime(datetime):
    """enqueue/score 边界测试内部 now 钉死，零时钟竞态。"""

    @classmethod
    def now(cls, tz=None):  # noqa: ARG002
        return _FIXED_NOW


def _mk_direction(db, name="DS") -> Direction:
    d = Direction(name=name, prompt="p", threshold=60)
    db.add(d)
    db.commit()
    return d


def _mk_source(db, d, url="https://ex/f", **kw) -> Source:
    src = Source(direction_id=d.id, url=url, type=kw.pop("type", "rss"), **kw)
    db.add(src)
    db.commit()
    return src


def _mk_item(db, src, guid="g1", **kw) -> Item:
    it = Item(source_id=src.id, guid=guid, url=f"https://ex/{guid}", title=guid,
              fetch_status=kw.pop("fetch_status", "FETCHED"),
              sanitize_status=kw.pop("sanitize_status", "PASSED"))
    db.add(it)
    db.commit()
    return it


class FakeStats:
    """抓取统计桩（字段面 = _fetch_stats_dict 契约 + error）。"""

    def __init__(self, **kw):
        self.feed_entries = kw.get("feed_entries", 1)
        self.inserted = kw.get("inserted", 1)
        self.dup_blocked = kw.get("dup_blocked", 2)
        self.rule_rejected = kw.get("rule_rejected", 3)
        self.failed = kw.get("failed", 0)
        self.guid_collisions = kw.get("guid_collisions", 0)
        self.not_modified = kw.get("not_modified", False)
        self.sanitize_passed = kw.get("sanitize_passed", 1)
        self.sanitize_rejected = kw.get("sanitize_rejected", 0)
        self.error = kw.get("error")


class FakeScoreResult:
    def __init__(self, status="OK", passed=True, error=None):
        self.status = status
        self.passed = passed
        self.error = error


def _patch_score(monkeypatch, script):
    """打桩 score_item：script 逐条消费——Exception 抛出、callable 调用后返回、其余原样返回。"""
    calls = []

    def fake(db, item, d):
        calls.append({"item_id": item.id, "direction_id": d.id})
        out = script.pop(0)
        if isinstance(out, Exception):
            raise out
        if callable(out):
            return out(db, item, d)
        return out

    monkeypatch.setattr(scoring_service, "score_item", fake)
    return calls


def _db_rows(db):
    db.expire_all()
    return db.query(PipelineTask).all()


# ---------- config：D18 凭据纪律 + G0 C3 自包含 ----------

def test_config_get_reads_env_skips_blank(monkeypatch):
    """_get：读 env 返回去空白值；空白值视同缺失尝试后续名；全缺失返回 None
    （G0 C3 env 读取口径 + D18 读取链）。"""
    monkeypatch.setenv("C19A_K1", "  v1  ")
    assert _get("C19A_K1") == "v1"
    monkeypatch.setenv("C19A_K1", "   ")
    assert _get("C19A_K1", "C19A_K2") is None
    assert _get("C19A_NOPE_1", "C19A_NOPE_2") is None


def test_config_require_env_or_system_exit(monkeypatch):
    """D18/AC-01.1：_require 命中 env 返回值；缺失写提示并 SystemExit 拒绝启动。"""
    monkeypatch.setenv("C19A_REQ", "secret")
    assert _require("C19A_REQ") == "secret"
    monkeypatch.delenv("C19A_REQ", raising=False)
    with pytest.raises(SystemExit):
        _require("C19A_REQ")


def test_config_get_bool_truthy_tokens(monkeypatch):
    """C3 布尔口径：未配置回缺省；配置 true（含空白/大小写）为真。"""
    assert _get_bool("C19A_NOPE", True) is True
    assert _get_bool("C19A_NOPE", False) is False
    monkeypatch.setenv("C19A_FLAG", "true")
    assert _get_bool("C19A_FLAG", False) is True
    monkeypatch.setenv("C19A_FLAG", "  TRUE  ")
    assert _get_bool("C19A_FLAG", False) is True


def test_tolerant_env_parse_two_forms(tmp_path):
    """G0 C3 容错口径：KEY=value 与「KEY value（空格分隔）」双形态；跳过注释/空行/残行
    （只收双段非空）；按首个分隔符切分（maxsplit=1）；无分隔行不产出不炸。"""
    f = tmp_path / "e.env"
    f.write_text(
        "# comment line\n"
        "KEY_A=v1\n"
        "KEY_B spaced value\n"
        "KEY_C: colon-val\n"
        "\n"
        "BAD = \n"
        "=nokey\n"
        "JUSTKEY\n",
        encoding="utf-8",
    )
    out = _tolerant_env_parse(f)
    assert out == {"KEY_A": "v1", "KEY_B": "spaced value", "KEY_C": "colon-val"}


def test_tolerant_env_parse_missing_file(tmp_path):
    """C3 容错：env 文件缺失返回空 dict，不抛异常。"""
    assert _tolerant_env_parse(tmp_path / "nope.env") == {}


# ---------- providers.deepseek：构造 / _post 计量旁路 / tier / chat（ADR-8 + M 实测） ----------

@pytest.fixture()
def dp(db_session):
    """DeepSeekProvider：_call 打桩（记录 payload+kwargs，_responses 出队）。"""
    p = DeepSeekProvider(db_session)
    calls: list[dict] = []

    def fake_call(payload, **kw):
        calls.append({"payload": payload, **kw})
        body = p._responses.pop(0)
        meter = p._meter_from_openai_usage(body.get("usage"))
        meter["finish_reason"] = p._finish_reason(body)
        p._last_meter = meter
        return body

    p._call = fake_call  # type: ignore[method-assign]
    p.calls = calls
    p._responses = []
    return p


def _body(model="deepseek-flash", finish="stop", content="ok",
          usage=None, with_model=True):
    b = {"choices": [{"message": {"content": content}, "finish_reason": finish}],
         "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5}}
    if with_model:
        b["model"] = model
    return b


def test_deepseek_construction_bearer(db_session):
    """ADR-8 D-B 构造契约：api_key 注入 Bearer 头（None/缺失即破坏契约）。"""
    p = DeepSeekProvider(db_session)
    assert p._headers["Authorization"] == f"Bearer {cfg.DEEPSEEK_API_KEY}"
    assert p.base_url == cfg.DEEPSEEK_BASE_URL


def test_post_real_metering_and_path(db_session, monkeypatch):
    """ADR-8 计量旁路：_post 走 /chat/completions；_meter_from_openai_usage 消费
    body.usage；finish_reason 入 meter（_finish_reason 收 body）；_last_meter 同步。"""
    p = DeepSeekProvider(db_session)
    seen = {}

    def fake_post_json(path, payload):
        seen["path"], seen["payload"] = path, payload

        class R:
            def json(self):
                return _body(model="deepseek-v4-pro", finish="length",
                             usage={"prompt_tokens": 77, "completion_tokens": 8})

        return R()

    monkeypatch.setattr(p, "_post_json", fake_post_json)
    seen_finish = {}
    orig_finish = p._finish_reason

    def recording_finish(body):
        seen_finish["body"] = body
        return orig_finish(body)

    monkeypatch.setattr(p, "_finish_reason", recording_finish)
    payload = {"model": "m"}
    body, meter = p._post(payload)
    assert seen["path"] == "/chat/completions"
    assert seen["payload"] is payload
    assert body["model"] == "deepseek-v4-pro"
    assert meter["prompt_tokens"] == 77 and meter["completion_tokens"] == 8
    assert meter["finish_reason"] == "length"
    assert seen_finish["body"]["model"] == "deepseek-v4-pro"
    assert p._last_meter == meter


def test_tier_reasoner_strips_response_format(db_session):
    """ADR-8/M 实测：思考档不吃 JSON mode——tier_request 剥离 response_format。"""
    p = DeepSeekProvider(db_session)
    out = p.tier_request({"model": "m", "messages": [],
                          "response_format": {"type": "json_object"}}, model_tier="reasoner")
    assert "response_format" not in out
    assert out["thinking"] == {"type": "enabled"}


def test_chat_payload_shape_and_retry_cap(dp):
    """ADR-8：payload 键面 model/messages/temperature；非 JSON 模式不带 response_format；
    max_tokens 未设置不下发；_call 收到 max_retries=2（重试 ≤2）与计量归因实参。"""
    dp._responses = [_body()]
    content, _ = dp.chat([{"role": "user", "content": "x"}], call_point="scoring",
                         temperature=0.7, ref_type="item", ref_id=42)
    sent = dp.calls[0]
    assert sent["payload"]["messages"] == [{"role": "user", "content": "x"}]
    assert sent["payload"]["temperature"] == 0.7
    assert "response_format" not in sent["payload"]
    assert "max_tokens" not in sent["payload"]  # 未设置不下发（非思考缺省 8K 由服务端定）
    assert sent["max_retries"] == 2  # ADR-8 重试 ≤2
    assert sent["call_point"] == "scoring"
    assert sent["ref_type"] == "item" and sent["ref_id"] == 42
    assert content == "ok"


def test_chat_max_tokens_passthrough_chat_tier(dp):
    """ADR-8/M 实测：非思考档 max_tokens 按调用方约束透传（键名与值）。"""
    dp._responses = [_body()]
    dp.chat([{"role": "user", "content": "x"}], call_point="scoring", max_tokens=500)
    assert dp.calls[0]["payload"]["max_tokens"] == 500


def test_chat_reasoner_tier_official_params(dp):
    """ADR-8/M 实测：思考档 thinking enabled；max_tokens 缺省不硬设（官方思考默认 64K）。"""
    dp._responses = [_body()]
    dp.chat([{"role": "user", "content": "x"}], call_point="w_draft", model_tier="reasoner",
            max_tokens=500)
    sent = dp.calls[0]["payload"]
    assert sent["thinking"] == {"type": "enabled"}
    assert "max_tokens" not in sent
    assert dp.reasoner_available is True


def test_chat_400_valve_resend_does_not_poison_reasoner_flag(db_session):
    """ADR-8 兼容阀 + 探测状态纪律：chat 档 400 → 阀剥离档位参数重发一次后抛错；
    reasoner_available 不得被 chat 档失败污染（探测状态只在 reasoner 首探落笔）。"""
    p = DeepSeekProvider(db_session)
    n = {"c": 0}

    def always_400(payload, **kw):
        n["c"] += 1
        raise ProviderError("HTTP 400: bad request")

    p._call = always_400  # type: ignore[method-assign]
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "x"}], call_point="scoring")
    assert p.reasoner_available is None  # chat 档失败不落探测标记
    assert n["c"] == 2  # 阀剥离重发一次（共 2 次），无 reasoner 回退重试
    assert "剥离" in (p.fallback_note or "")  # note 记阀行为而非 reasoner 回退


def test_chat_reasoner_probe_failure_fallback_note_keeps_cause(db_session):
    """ADR-8/M 实测：思考档首探失败（非参数类错误，阀不触发）→
    reasoner_available=False、fallback_note 留因（含错误文本）、回退 chat 重发成功。"""
    p = DeepSeekProvider(db_session)
    calls: list[dict] = []

    def flaky(payload, **kw):
        calls.append(payload)
        if (payload.get("thinking") or {}).get("type") == "enabled":
            raise ProviderError("HTTP 500: probe-boom")
        return _body(content="chat-fallback")

    p._call = flaky  # type: ignore[method-assign]
    content, _ = p.chat([{"role": "user", "content": "x"}], call_point="w_draft",
                        model_tier="reasoner")
    assert content == "chat-fallback"
    assert p.reasoner_available is False
    assert "probe-boom" in (p.fallback_note or "")


def test_chat_reasoner_pre_unavailable_fallback_note(db_session):
    """ADR-8/M 实测：reasoner 档此前实测不可用（available=False）→ 后续 reasoner 请求
    直接回退 chat，fallback_note 留因。"""
    p = DeepSeekProvider(db_session)
    calls: list[dict] = []

    def flaky(payload, **kw):
        calls.append(payload)
        return _body(content="chat-again")

    p._call = flaky  # type: ignore[method-assign]
    p.reasoner_available = False
    content, _ = p.chat([{"role": "user", "content": "x"}], call_point="w_draft",
                        model_tier="reasoner")
    assert content == "chat-again"
    assert (p.fallback_note or "") != ""  # 留因
    assert calls[0].get("thinking") == {"type": "disabled"}  # 直接走 chat 档


def test_chat_compat_valve_strips_both_tier_params(db_session):
    """ADR-8 兼容阀：网关 400 拒档位参数 → 剥离 thinking 与 reasoning_effort 全部重发；
    重发实参（call_point/ref_type/ref_id/max_retries）保持；fallback_note 留因。"""
    p = DeepSeekProvider(db_session)
    calls: list[dict] = []
    kwargs: list[dict] = []

    def flaky(payload, **kw):
        calls.append(payload)
        kwargs.append(kw)
        if "thinking" in payload or "reasoning_effort" in payload:
            raise ProviderError("HTTP 400: unknown field")
        return _body(content="stripped-ok")

    p._call = flaky  # type: ignore[method-assign]
    content, _ = p.chat([{"role": "user", "content": "x"}], call_point="w_draft",
                        model_tier="reasoner", ref_type="author", ref_id=7)
    assert content == "stripped-ok"
    stripped = calls[1]
    assert "thinking" not in stripped and "reasoning_effort" not in stripped
    assert kwargs[1]["call_point"] == "w_draft"
    assert kwargs[1]["ref_type"] == "author" and kwargs[1]["ref_id"] == 7
    assert kwargs[1]["max_retries"] == 2
    assert "剥离" in (p.fallback_note or "")


def test_chat_compat_valve_422_also_strips(db_session):
    """ADR-8 兼容阀（422 同款）：非官方网关 422 拒档位参数 → 剥离重发成功。"""
    p = DeepSeekProvider(db_session)
    calls: list[dict] = []

    def flaky(payload, **kw):
        calls.append(payload)
        if "reasoning_effort" in payload or "thinking" in payload:
            raise ProviderError("HTTP 422: unprocessable field")
        return _body(content="ok-422")

    p._call = flaky  # type: ignore[method-assign]
    content, _ = p.chat([{"role": "user", "content": "x"}], call_point="scoring",
                        model_tier="reasoner")
    assert content == "ok-422"
    assert "thinking" not in calls[1]


def test_chat_retryable_finish_resends_same_payload(dp):
    """ADR-8/M 实测：服务端中断 finish_reason（aborted）→ 同 payload 重发一次，
    last_usage 以重发响应计量为准。"""
    dp._responses = [_body(finish="aborted", content=""),
                     _body(finish="stop", content="recovered")]
    content, _ = dp.chat([{"role": "user", "content": "x"}], call_point="w_draft")
    assert content == "recovered"
    assert dp.calls[1]["payload"] == dp.calls[0]["payload"]
    assert dp.last_usage["finish_reason"] == "stop"


def test_chat_actual_model_prefers_body(dp):
    """ADR-8/M 实测（响应实报）：model 以响应体为准；响应缺 model 回落请求 model；
    空 content 返回空串。"""
    dp._responses = [_body(model="deepseek-v4-pro")]
    _, model = dp.chat([{"role": "user", "content": "x"}], call_point="scoring")
    assert model == "deepseek-v4-pro"

    dp._responses = [_body(with_model=False)]
    _, model2 = dp.chat([{"role": "user", "content": "x"}], call_point="scoring")
    assert model2 == dp.calls[-1]["payload"]["model"]

    dp._responses = [_body(content=None)]
    content, _ = dp.chat([{"role": "user", "content": "x"}], call_point="scoring")
    assert content == ""


# ---------- runner：_fetch_one 分发 / _fetch_stats_dict 账目 / _finish CAS ----------

def test_fetch_one_dispatch_by_type(db_session, monkeypatch):
    """模块 docstring（provider 接口化）：rss→fetch_source、web→fetch_web_source、
    search→fetch_search_source，(db, src) 全实参透传。"""
    d = _mk_direction(db_session)
    seen = {}

    def mk(tag):
        def f(db, src):
            seen[tag] = (db, src)
            return f"stats-{tag}"
        return f

    monkeypatch.setattr(runner_mod, "fetch_source", mk("rss"))
    monkeypatch.setattr(runner_mod, "fetch_web_source", mk("web"))
    monkeypatch.setattr(search_pipeline, "fetch_search_source", mk("search"))

    s_rss = _mk_source(db_session, d, "https://ex/a", type="rss")
    s_web = _mk_source(db_session, d, "https://ex/b", type="web")
    s_search = _mk_source(db_session, d, "https://ex/c", type="search")

    assert _fetch_one(db_session, s_rss) == "stats-rss"
    assert _fetch_one(db_session, s_web) == "stats-web"
    assert _fetch_one(db_session, s_search) == "stats-search"
    assert seen["rss"] == (db_session, s_rss)
    assert seen["web"] == (db_session, s_web)
    assert seen["search"] == (db_session, s_search)


def test_fetch_stats_dict_full_keys():
    """AC-05.1 账目分桶 + DT-5 payload.stats：九字段键名与值逐项保真。"""
    d = _fetch_stats_dict(FakeStats(feed_entries=11, inserted=12, dup_blocked=13,
                                    rule_rejected=14, failed=15, guid_collisions=16,
                                    not_modified=True, sanitize_passed=17,
                                    sanitize_rejected=18))
    assert d == {"feed_entries": 11, "inserted": 12, "dup_blocked": 13,
                 "rule_rejected": 14, "failed": 15, "guid_collisions": 16,
                 "not_modified": True, "sanitize_passed": 17, "sanitize_rejected": 18}


def test_finish_cas_scopes_to_task_id(db_session):
    """§4.2 CAS：_finish 的 UPDATE WHERE id+status——只终结目标任务，他任务不受牵连。"""
    t1 = PipelineTask(kind="fetch", status="RUNNING", payload={})
    t2 = PipelineTask(kind="fetch", status="RUNNING", payload={})
    db_session.add_all([t1, t2])
    db_session.commit()
    _finish(db_session, t1, status="DONE", stats={"inserted": 1})
    by_id = {t.id: t.status for t in _db_rows(db_session)}
    assert by_id[t1.id] == "DONE"
    assert by_id[t2.id] == "RUNNING"  # CAS 隔离：他人任务不被误终结


def test_finish_payload_extra_and_stats_merge(db_session):
    """DT-5 + write_task 契约：payload_extra 顶层合并、stats 并入 payload.stats、
    last_error 留痕、内存对象同步。"""
    t = PipelineTask(kind="write", status="RUNNING", payload={"author_id": 1})
    db_session.add(t)
    db_session.commit()
    _finish(db_session, t, status="FAILED",
            payload_extra={"write_run_id": 9, "decision": "not_write"},
            stats={"candidates": 3}, error="boom")
    db_session.expire_all()
    row = db_session.get(PipelineTask, t.id)
    assert row.status == "FAILED"
    assert row.payload["author_id"] == 1  # 原有键保留
    assert row.payload["write_run_id"] == 9 and row.payload["decision"] == "not_write"
    assert row.payload["stats"] == {"candidates": 3}
    assert row.last_error == "boom"
    assert t.payload["stats"] == {"candidates": 3}  # 内存同步（调用方读 task 不失真）


def _health_stats(*, failed: bool):
    """构造源健康更新所需的最小抓取统计（failed=True 模拟错误轮，False 模拟成功轮）。"""
    from types import SimpleNamespace

    return SimpleNamespace(
        error="HTTPStatusError: boom" if failed else None,
        feed_entries=0 if failed else 3,
        inserted=0 if failed else 3,
        not_modified=False,
        rate_limited=False,
        retry_after=None,
        extra={},
    )


def test_update_backoff_counts(db_session):
    """AC-20.3 退避计数：失败 +1（含从 0 起计）；成功清零（failures/skips）。"""
    d = _mk_direction(db_session)
    hot = _mk_source(db_session, d, "https://ex/hot", backoff_failures=2)
    fresh = _mk_source(db_session, d, "https://ex/fresh")
    _update_source_health(db_session, hot, _health_stats(failed=True))
    _update_source_health(db_session, fresh, _health_stats(failed=True))
    db_session.expire_all()
    assert db_session.get(Source, hot.id).backoff_failures == 3
    assert db_session.get(Source, fresh.id).backoff_failures == 1
    _update_source_health(db_session, hot, _health_stats(failed=False))
    db_session.expire_all()
    assert db_session.get(Source, hot.id).backoff_failures == 0
    assert db_session.get(Source, hot.id).backoff_skips == 0


def test_round_busy_kind_scoped(db_session):
    """模块 docstring 防重叠：同 kind 的 RUNNING/PENDING 未清空才阻塞；他 kind 不阻塞。"""
    db_session.add(PipelineTask(kind="write", status="RUNNING", payload={}))
    db_session.commit()
    assert round_busy(db_session, "fetch_round") is False  # 他 kind 不阻塞

    db_session.add(PipelineTask(kind="fetch_round", status="RUNNING", payload={}))
    db_session.commit()
    assert round_busy(db_session, "fetch_round") is True  # 同 kind RUNNING 阻塞
    assert round_busy(db_session, "hot_round") is False


# ---------- runner：enqueue（间隔 / 退避 / 探测 / payload 键面） ----------

def test_enqueue_interval_not_due_and_skip_entry(db_session, monkeypatch):
    """调度入队侧判定（模块注释）：interval_minutes 未到期跳过
    （reason=interval_not_due:Nm，键面 source_id/url）；到期源与无间隔源照常入队；
    间隔源缺 last_fetched_at 不判到期（首抓即入队）。"""
    d = _mk_direction(db_session)
    due = _mk_source(db_session, d, "https://ex/due")
    not_due = _mk_source(db_session, d, "https://ex/slow",
                         source_config={"interval_minutes": 60},
                         last_fetched_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    no_interval = _mk_source(db_session, d, "https://ex/first",
                             last_fetched_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    assert rt is not None
    assert rt.payload["triggered_by"] == "test"
    skipped = rt.payload["skipped_backoff"]
    assert len(skipped) == 1
    assert skipped[0]["source_id"] == not_due.id
    assert skipped[0]["url"] == "https://ex/slow"
    assert skipped[0]["reason"] == "interval_not_due:60m"
    sub = [t for t in _db_rows(db_session) if t.kind == "fetch" and t.status == "PENDING"]
    assert len(sub) == 2
    by_src = {t.payload["source_id"]: t for t in sub}
    assert set(by_src) == {due.id, no_interval.id}
    assert by_src[due.id].payload["url"] == "https://ex/due"


def test_enqueue_interval_boundary_exactly_due(db_session, monkeypatch):
    """「未到期跳过」边界：耗时恰等于 interval（==interval*60 秒）已到期 → 入队
    （"未到期" = 严格小于 interval 才跳）。"""
    monkeypatch.setattr(runner_mod, "datetime", _FixedDatetime)
    d = _mk_direction(db_session)
    src = _mk_source(db_session, d, "https://ex/b",
                     source_config={"interval_minutes": 30},
                     last_fetched_at=_FIXED_NOW - timedelta(minutes=30))
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    assert rt is not None
    sub = [t for t in _db_rows(db_session) if t.kind == "fetch"]
    assert len(sub) == 1 and sub[0].payload["source_id"] == src.id


def test_enqueue_probe_every_four_rounds(db_session, monkeypatch):
    """AC-20.3 探测节奏：达到阈值后每 BACKOFF_PROBE_EVERY 轮放行一次——skips=4→5 时放行
    （探测轮不进 skipped_backoff、正常入队）。"""
    monkeypatch.setattr(runner_mod, "datetime", _FixedDatetime)
    d = _mk_direction(db_session)
    _mk_source(db_session, d, backoff_failures=cfg.BACKOFF_FAIL_THRESHOLD, backoff_skips=4)
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    assert rt is not None
    assert rt.payload["skipped_backoff"] == []
    sub = [t for t in _db_rows(db_session) if t.kind == "fetch"]
    assert len(sub) == 1


def test_enqueue_backoff_skip_entry_and_continues(db_session):
    """AC-20.3：退避源跳过（连续失败计数/跳过轮数入账），后续源不受影响逐个入队。"""
    d = _mk_direction(db_session)
    bad = _mk_source(db_session, d, "https://ex/bad",
                     backoff_failures=cfg.BACKOFF_FAIL_THRESHOLD, backoff_skips=1)
    good = _mk_source(db_session, d, "https://ex/good")
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    assert rt is not None
    skipped = rt.payload["skipped_backoff"]
    assert len(skipped) == 1
    assert skipped[0]["source_id"] == bad.id
    assert skipped[0]["url"] == "https://ex/bad"
    assert skipped[0]["consecutive_failures"] == cfg.BACKOFF_FAIL_THRESHOLD
    assert skipped[0]["skips"] == 2
    sub = [t for t in _db_rows(db_session) if t.kind == "fetch" and t.status == "PENDING"]
    assert {t.payload["source_id"] for t in sub} == {good.id}


# ---------- runner：fetch_round（行为面：终态落库 / 账目 / 退避 / 失败留痕） ----------

def test_fetch_round_success_full_shape(db_session, monkeypatch):
    """模块 docstring + §4.2：逐源 kind=fetch 任务、payload source_id/url、DONE 终态落库、
    summary 归因键面 + payload.stats 分桶字段透传、退避清零。"""
    d = _mk_direction(db_session)
    src = _mk_source(db_session, d, "https://ex/f", backoff_failures=2)
    monkeypatch.setattr(runner_mod, "fetch_source", lambda db, s: FakeStats())
    summary = fetch_round(db_session, triggered_by="test")
    assert summary["triggered_by"] == "test"
    (entry,) = summary["sources"]
    assert entry["source_id"] == src.id and entry["url"] == "https://ex/f"
    assert entry["status"] == "DONE" and entry["error"] is None
    assert entry["inserted"] == 1 and entry["dup_blocked"] == 2
    tasks = _db_rows(db_session)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.kind == "fetch" and t.status == "DONE"  # 终态落库（DB 即队列）
    assert t.payload["source_id"] == src.id and t.payload["url"] == "https://ex/f"
    assert t.payload["stats"]["inserted"] == 1
    db_session.expire_all()
    assert db_session.get(Source, src.id).backoff_failures == 0  # 成功清零


def test_fetch_round_failure_records_error_and_backoff(db_session, monkeypatch):
    """AC-20.3 + 失败留痕：stats.error → FAILED 终态 + last_error 如实 + backoff_failures+1。"""
    d = _mk_direction(db_session)
    src = _mk_source(db_session, d)
    monkeypatch.setattr(runner_mod, "fetch_source", lambda db, s: FakeStats(error="boom"))
    summary = fetch_round(db_session, triggered_by="test")
    (entry,) = summary["sources"]
    assert entry["status"] == "FAILED" and entry["error"] == "boom"
    tasks = _db_rows(db_session)
    assert tasks[0].status == "FAILED" and tasks[0].last_error == "boom"
    db_session.expire_all()
    assert db_session.get(Source, src.id).backoff_failures == 1


def test_fetch_round_exception_lands_failed_with_backoff(db_session, monkeypatch):
    """P1-1（G1）行为面：异常先回滚再落 FAILED 终态（毒行不入库），失败计入退避。"""
    d = _mk_direction(db_session)
    src = _mk_source(db_session, d)

    def corrupting(db, s):
        db.add(Item(source_id=s.id, guid=None, title="poison"))
        raise RuntimeError("模拟会话损坏")

    monkeypatch.setattr(runner_mod, "fetch_source", corrupting)
    summary = fetch_round(db_session, triggered_by="test")
    (entry,) = summary["sources"]
    assert entry["status"] == "FAILED" and "RuntimeError" in entry["error"]
    assert _db_rows(db_session)[0].status == "FAILED"
    assert db_session.query(Item).count() == 0  # 毒行被回滚
    db_session.expire_all()
    assert db_session.get(Source, src.id).backoff_failures == 1


# ---------- runner：process_fetch_round（worker 路径） ----------

def test_process_round_skipped_shape(db_session):
    """P0-1/CAS：已终结轮次再 process → 幂等跳过，返回键面 round_task_id/status/skipped。"""
    d = _mk_direction(db_session)
    _mk_source(db_session, d)
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    for t in db_session.query(PipelineTask).all():
        t.status = "DONE"
    db_session.commit()
    result = process_fetch_round(db_session, rt)
    assert result["skipped"] is True
    assert result["round_task_id"] == rt.id
    assert result["status"] == "DONE"


def test_process_round_only_claims_fetch_kind(db_session, monkeypatch):
    """DB 即队列（§4.2）：worker 只认领 kind=fetch 的 PENDING 任务，他 kind 不动。"""
    d = _mk_direction(db_session)
    src = _mk_source(db_session, d)
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    other = PipelineTask(kind="score", status="PENDING",
                         payload={"round_task_id": rt.id})
    db_session.add(other)
    db_session.commit()
    monkeypatch.setattr(runner_mod, "fetch_source", lambda db, s: FakeStats())
    summary = process_fetch_round(db_session, rt)
    assert summary["status"] == "DONE"
    db_session.expire_all()
    assert db_session.get(PipelineTask, other.id).status == "PENDING"  # 未被牵连
    fetch_tasks = [t for t in db_session.query(PipelineTask).all() if t.kind == "fetch"]
    assert all(t.status == "DONE" for t in fetch_tasks)


def test_process_round_missing_source_two_ghosts(db_session, monkeypatch):
    """P0-1/P1-1 行为面：source 缺失任务逐个 FAILED（error 留痕）不中断后续任务；
    任一失败 → 轮次 FAILED；缺失任务不进 summary（账实分离由 last_error 承载）。"""
    d = _mk_direction(db_session)
    src = _mk_source(db_session, d, "https://ex/good")
    rt = enqueue_fetch_round(db_session, triggered_by="test")
    ghost1 = PipelineTask(kind="fetch", status="PENDING",
                          payload={"source_id": 999999, "url": "https://ex/g1",
                                   "round_task_id": rt.id})
    ghost2 = PipelineTask(kind="fetch", status="PENDING",
                          payload={"source_id": 888888, "url": "https://ex/g2",
                                   "round_task_id": rt.id})
    db_session.add_all([ghost1, ghost2])
    db_session.commit()
    monkeypatch.setattr(runner_mod, "fetch_source", lambda db, s: FakeStats())
    summary = process_fetch_round(db_session, rt)
    assert summary["status"] == "FAILED"  # 幽灵任务计失败
    assert len(summary["sources"]) == 1
    assert summary["sources"][0]["source_id"] == src.id
    assert summary["sources"][0]["status"] == "DONE"
    db_session.expire_all()
    g1 = db_session.get(PipelineTask, ghost1.id)
    g2 = db_session.get(PipelineTask, ghost2.id)
    assert g1.status == "FAILED" and g1.last_error is not None  # 失败留痕
    assert g2.status == "FAILED"  # 幽灵 2 不被中断（break 变异即在此暴露）


def test_process_round_mixed_ok_error(db_session, monkeypatch):
    """AC-20.3 + §4.2：ok/失败混合轮——失败源退避+1、成功源清零；轮次 FAILED；
    summary 键面 + stats 字段透传。"""
    d = _mk_direction(db_session)
    ok_src = _mk_source(db_session, d, "https://ex/ok")
    bad_src = _mk_source(db_session, d, "https://ex/bad", backoff_failures=1)
    rt = enqueue_fetch_round(db_session, triggered_by="test")

    def fetch(db, s):
        if s.id == bad_src.id:
            return FakeStats(error="net-down")
        return FakeStats()

    monkeypatch.setattr(runner_mod, "fetch_source", fetch)
    summary = process_fetch_round(db_session, rt)
    assert summary["round_task_id"] == rt.id
    assert summary["status"] == "FAILED"
    entries = {e["source_id"]: e for e in summary["sources"]}
    assert entries[ok_src.id]["status"] == "DONE" and entries[ok_src.id]["error"] is None
    assert entries[bad_src.id]["status"] == "FAILED"
    assert entries[bad_src.id]["error"] == "net-down"
    assert entries[ok_src.id]["inserted"] == 1
    db_session.expire_all()
    assert db_session.get(Source, ok_src.id).backoff_failures == 0
    assert db_session.get(Source, bad_src.id).backoff_failures == 2
    assert db_session.get(PipelineTask, rt.id).status == "FAILED"  # 轮次终态落库


def test_process_round_exception_lands_failed_with_backoff(db_session, monkeypatch):
    """P1-1 worker 路径：异常回滚落 FAILED + 退避计入；轮次 FAILED。"""
    d = _mk_direction(db_session)
    src = _mk_source(db_session, d)
    rt = enqueue_fetch_round(db_session, triggered_by="test")

    def corrupting(db, s):
        db.add(Item(source_id=s.id, guid=None, title="poison"))
        raise RuntimeError("worker 会话损坏")

    monkeypatch.setattr(runner_mod, "fetch_source", corrupting)
    summary = process_fetch_round(db_session, rt)
    assert summary["status"] == "FAILED"
    (entry,) = summary["sources"]
    assert entry["status"] == "FAILED" and "RuntimeError" in entry["error"]
    assert db_session.query(Item).count() == 0
    db_session.expire_all()
    assert db_session.get(Source, src.id).backoff_failures == 1


# ---------- runner：P0-1 回收边界 ----------

def test_reclaim_only_touches_running(db_session):
    """AC-20.2/P0-1：回收只置 RUNNING 僵死任务为 FAILED；DONE 终态不回收。"""
    stale_running = PipelineTask(kind="fetch", status="RUNNING", payload={},
                                 updated_at=_FIXED_NOW - timedelta(minutes=31))
    done_old = PipelineTask(kind="fetch", status="DONE", payload={},
                            updated_at=_FIXED_NOW - timedelta(days=2))
    db_session.add_all([stale_running, done_old])
    db_session.commit()
    assert reclaim_stale_tasks(db_session, now=_FIXED_NOW) == 1
    db_session.expire_all()
    assert db_session.get(PipelineTask, stale_running.id).status == "FAILED"
    assert db_session.get(PipelineTask, done_old.id).status == "DONE"  # 终态不回收


def test_reclaim_threshold_boundary_strict(db_session):
    """技术书 §4.2「超 30/60/120min」：updated_at 恰等于 cutoff（30min 整）未"超"→ 不回收。"""
    edge = PipelineTask(kind="fetch", status="RUNNING", payload={},
                        updated_at=_FIXED_NOW - timedelta(minutes=30))
    db_session.add(edge)
    db_session.commit()
    assert reclaim_stale_tasks(db_session, now=_FIXED_NOW) == 0
    db_session.expire_all()
    assert db_session.get(PipelineTask, edge.id).status == "RUNNING"


# ---------- runner：score_round（幂等 outerjoin / 圈定 / 统计 / 分账 / 终态） ----------

def _mk_score_world(db, *, n_items=1, prefix="i"):
    d = _mk_direction(db)
    src = _mk_source(db, d)
    items = [_mk_item(db, src, guid=f"{prefix}{k}") for k in range(n_items)]
    return d, src, items


def test_score_round_idempotent_outerjoin(db_session, monkeypatch):
    """模块 docstring 幂等（AC-07.x）：只对无 OK 分条目调 LLM——
    同方向已有 OK 分的条目绝不重复打分；只有 FAILED 分的条目下轮续跑；
    他方向 OK 分不阻断本方向打分（幂等键 = item×direction×OK）。"""
    d, src, items = _mk_score_world(db_session, n_items=3, prefix="idem")
    db_session.add(ScoreResult(item_id=items[0].id, direction_id=d.id, model="m",
                               status="OK", passed=True))
    other_d = _mk_direction(db_session, name="OTHER")
    db_session.add(ScoreResult(item_id=items[1].id, direction_id=other_d.id, model="m",
                               status="OK", passed=True))
    db_session.add(ScoreResult(item_id=items[2].id, direction_id=d.id, model="m",
                               status="FAILED", passed=False, error="boom"))
    db_session.commit()
    calls = _patch_score(monkeypatch, [FakeScoreResult(status="OK", passed=True),
                                       FakeScoreResult(status="OK", passed=False)])
    score_round(db_session, direction_id=d.id)
    scored_ids = {c["item_id"] for c in calls}
    assert items[0].id not in scored_ids  # 已有 OK 分 → 不重复烧 LLM
    assert scored_ids == {items[1].id, items[2].id}  # 续跑 + 他方向 OK 不阻断


def test_score_round_direction_scoping(db_session, monkeypatch):
    """AC-07.x 逐方向线性：每方向只打自己启用源的条目；停用源不打分；
    direction_id 过滤只跑指定方向。"""
    d1 = _mk_direction(db_session, "D1")
    d2 = _mk_direction(db_session, "D2")
    s1 = _mk_source(db_session, d1, "https://ex/s1")
    s2 = _mk_source(db_session, d2, "https://ex/s2")
    s1_off = _mk_source(db_session, d1, "https://ex/s1off", enabled=False)
    i1 = _mk_item(db_session, s1, guid="d1i")
    i2 = _mk_item(db_session, s2, guid="d2i")
    i_off = _mk_item(db_session, s1_off, guid="d1off")
    calls = _patch_score(monkeypatch, [FakeScoreResult()])
    score_round(db_session, direction_id=d1.id)
    assert {(c["item_id"], c["direction_id"]) for c in calls} == {(i1.id, d1.id)}

    calls2 = _patch_score(monkeypatch, [FakeScoreResult(), FakeScoreResult()])
    score_round(db_session)  # 全部启用方向
    assert {(c["item_id"], c["direction_id"]) for c in calls2} == {(i1.id, d1.id),
                                                                   (i2.id, d2.id)}
    assert i_off.id not in {c["item_id"] for c in calls2}  # 停用源不打分


def test_score_round_stats_accounting_full(db_session, monkeypatch):
    """AC-07.x 统计吻合 + JSONParseError 分账 + 单条异常不中断整轮 + DT-5 payload.stats：
    7 条目 = 异常×2 + OK(passed) + OK(not passed) + 解析失败×2 + 调用失败 →
    candidates=7/scored=2/passed=1/call_failed=3/parse_failed=2；部分成功仍 DONE；
    last_error 留痕；task payload 带 direction_id/prompt_version；summary 键面完整。"""
    d = _mk_direction(db_session)
    d.prompt_version = 7
    db_session.commit()
    src = _mk_source(db_session, d)
    for k in range(7):
        _mk_item(db_session, src, guid=f"acc{k}")
    script = [
        RuntimeError("llm down"),                      # 异常（计 call_failed）
        RuntimeError("llm down again"),                # 异常（累计：非清零/非单发）
        FakeScoreResult(status="OK", passed=True),     # scored+1, passed+1
        FakeScoreResult(status="OK", passed=False),    # scored+1, passed+0
        FakeScoreResult(status="FAILED", passed=False, error="JSONParseError: bad json"),
        FakeScoreResult(status="FAILED", passed=False, error="JSONParseError: worse"),
        FakeScoreResult(status="FAILED", passed=False, error="ProviderError: quota"),
    ]
    calls = _patch_score(monkeypatch, script)
    summary = score_round(db_session, triggered_by="test")
    assert len(calls) == 7  # 异常在首位仍逐条跑完（不中断整轮）
    (entry,) = summary["directions"]
    assert entry["direction_id"] == d.id and entry["name"] == "DS"
    assert entry["status"] == "DONE"  # 部分成功仍 DONE（失败条目下轮续跑）
    assert entry["candidates"] == 7 and entry["scored"] == 2 and entry["passed"] == 1
    assert entry["call_failed"] == 3 and entry["parse_failed"] == 2
    assert entry["error"] is not None  # 失败留痕
    assert summary["triggered_by"] == "test"
    score_tasks = [t for t in _db_rows(db_session) if t.kind == "score"]
    assert len(score_tasks) == 1
    t = score_tasks[0]
    assert entry["task_id"] == t.id  # summary 归因指向落库任务行
    assert t.status == "DONE"  # 终态落库
    assert t.payload["direction_id"] == d.id
    assert t.payload["prompt_version"] == 7
    assert t.payload["stats"]["candidates"] == 7
    assert t.payload["stats"]["parse_failed"] == 2


def test_score_round_all_failed_lands_failed(db_session, monkeypatch):
    """§4.2/AC-07.x：全部失败（异常+解析失败）且零成功 → 任务 FAILED + error 留痕。"""
    d, src, items = _mk_score_world(db_session, n_items=2, prefix="af")
    _patch_score(monkeypatch, [
        RuntimeError("down"),
        FakeScoreResult(status="FAILED", passed=False, error="JSONParseError: x"),
    ])
    (entry,) = score_round(db_session)["directions"]
    assert entry["status"] == "FAILED"
    assert entry["error"] is not None
    assert entry["call_failed"] == 1 and entry["parse_failed"] == 1 and entry["scored"] == 0
    db_session.expire_all()
    t = [t for t in db_session.query(PipelineTask).all() if t.kind == "score"][0]
    assert t.status == "FAILED" and t.last_error is not None


def test_score_round_single_fail_with_ok_still_done(db_session, monkeypatch):
    """AC-07.x：有成功即 DONE（失败条目下轮续跑），error 留痕不缺失。"""
    d, src, items = _mk_score_world(db_session, n_items=2, prefix="sf")
    _patch_score(monkeypatch, [
        FakeScoreResult(status="OK", passed=True),
        RuntimeError("one down"),
    ])
    (entry,) = score_round(db_session)["directions"]
    assert entry["status"] == "DONE"
    assert entry["scored"] == 1 and entry["call_failed"] == 1
    assert entry["error"] is not None


def test_score_round_parse_fail_only_keeps_error(db_session, monkeypatch):
    """JSONParseError 分账：仅解析失败（零成功）→ FAILED 且 last_error 留痕。"""
    d, src, items = _mk_score_world(db_session, n_items=1, prefix="po")
    _patch_score(monkeypatch, [
        FakeScoreResult(status="FAILED", passed=False, error="JSONParseError: y"),
    ])
    (entry,) = score_round(db_session)["directions"]
    assert entry["status"] == "FAILED"
    assert entry["parse_failed"] == 1 and entry["call_failed"] == 0
    assert entry["error"] is not None


def test_score_round_empty_direction_done(db_session, monkeypatch):
    """零候选（无待打分条目）→ DONE、error 为空、统计全零——不误标 FAILED。"""
    d, src, items = _mk_score_world(db_session, n_items=1, prefix="never")
    items[0].fetch_status = "FAILED"  # 不进打分圈
    db_session.commit()
    _patch_score(monkeypatch, [])
    (entry,) = score_round(db_session)["directions"]
    assert entry["status"] == "DONE" and entry["error"] is None
    assert entry["candidates"] == 0 and entry["scored"] == 0


def test_score_round_all_ok_clean_done(db_session, monkeypatch):
    """全成功 → DONE、error 为空、scored/passed 累计。"""
    d, src, items = _mk_score_world(db_session, n_items=2, prefix="ok")
    _patch_score(monkeypatch, [FakeScoreResult(status="OK", passed=True),
                               FakeScoreResult(status="OK", passed=True)])
    (entry,) = score_round(db_session)["directions"]
    assert entry["status"] == "DONE" and entry["error"] is None
    assert entry["scored"] == 2 and entry["passed"] == 2


def test_score_round_outer_exception_lands_failed(db_session, monkeypatch):
    """P1-1 行为面（score 同款）：会话毒行致终态提交失败 → 回滚后落 FAILED，
    error 含异常类型名（如实留痕）。"""
    d = _mk_direction(db_session)
    src = _mk_source(db_session, d)
    _mk_item(db_session, src, guid="victim")

    def poison_then_raise(db, it, dd):
        db.add(Item(source_id=src.id, guid=None, title="poison"))  # 终态提交 flush 即炸
        return FakeScoreResult()

    _patch_score(monkeypatch, [poison_then_raise])
    summary = score_round(db_session)
    (entry,) = summary["directions"]
    assert entry["status"] == "FAILED"
    assert (entry["error"] or "").startswith("IntegrityError")  # 异常类型名如实留痕
    db_session.expire_all()
    t = [t for t in db_session.query(PipelineTask).all() if t.kind == "score"][0]
    assert t.status == "FAILED"
    assert (t.last_error or "").startswith("IntegrityError")
