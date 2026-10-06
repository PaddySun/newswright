"""author.json route.passes[] 条目校验：type 枚举与 params 类型的报错路径。

校验纪律（schema 模块 docstring）：缺字段/类型错/非法枚举值全部报错（含字段路径），
返回全部错误不短路。本文件钉 passes 条目两域的路径与不崩溃面：
- type 非法枚举 → 错误含 route.passes[i].type 路径且不抛裸异常；
- params 非 object → 错误含 route.passes[i].params 路径且不抛裸异常。
设计依据见 docs/design-index.md「AC-10.1」。
"""
from app.authors.schema import _validate_pass_entry


def _errors_of(entry) -> list[str]:
    errors: list[str] = []
    _validate_pass_entry(entry, 0, errors)
    return errors


def test_valid_pass_entry_no_errors():
    """合法条目（type 命中枚举、params 缺省）零错误。"""
    assert _errors_of({"type": "prune"}) == []
    assert _errors_of({"type": "rhythm", "params": {"x": 1}}) == []


def test_pass_entry_must_be_object():
    """非 object 条目报类型错误（路径含 route.passes[i]）。"""
    errs = _errors_of("oops")
    assert len(errs) == 1 and "route.passes[0]" in errs[0]


def test_invalid_pass_type_reported_with_path():
    """type 非法枚举 → 返回错误清单（非崩溃），路径含 route.passes[i].type。"""
    errs = _errors_of({"type": "bogus"})
    assert len(errs) == 1
    assert "route.passes[0].type" in errs[0]


def test_invalid_pass_params_type_reported():
    """params 非 object → 返回错误清单（非崩溃），路径含 route.passes[i].params。"""
    errs = _errors_of({"type": "prune", "params": "oops"})
    assert len(errs) == 1
    assert "route.passes[0].params" in errs[0]
