"""写作管线提供方全冷却降级终态契约（authors.pipeline）：FAILED + 错误原因落库。

一面（选源层降级链在写作域的终态面）：
- 全部 LLM 候选冷却（选源返回 None）时，写作 run 落 FAILED 终态且
  error 落库错误原因——终态值必须是 FAILED 枚举（不得漂移/置空），
  错误原因必须非空可观测（「无可用 LLM 提供方」的结构性失败不得
  静默或伪装成功）。
设计依据见 docs/design-index.md「LR-3」。
"""
import app.authors.pipeline as pl
from app.authors.importer import import_author_json
from app.authors.schema import default_author_config


def _author(db):
    cfg = default_author_config("degrade_probe", "降级终态测试作者")
    return import_author_json(db, cfg, model="test-model")


def test_all_candidates_cooldown_fails_run_with_reason(db_session, monkeypatch):
    """全部候选冷却：run.status=FAILED 且 run.error 非空——选源降级链的
    写作域终态（FAILED 终态 + 错误原因落库）。"""
    author = _author(db_session)
    monkeypatch.setattr(pl, "resolve_chat", lambda _db: None)
    run = pl.run_pipeline_write(db_session, author, triggered_by="test")
    assert run.status == "FAILED"
    assert run.error
