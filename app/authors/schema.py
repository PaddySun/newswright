"""author.JSON schema 校验器（任务书 §3 核心交付物）。

分层原则（用户已确认 2026-09-28）：author.json = 作者全量身份与管线配置；模型不在
JSON 中（DB Author.model / 后台作者配置页绑定运行时模型）。字段可增不可减——
缺字段/类型错/非法枚举值全部报错（含字段路径），导入即失败。

校验纪律：返回全部错误（不短路），便于一次修完；无错返回空列表。
"""
from __future__ import annotations

DRAFT_MODES = ("single", "rolling", "incubate", "dictate")
OUTLINE_TEMPLATES = ("pyramid", "variation", "sectional", "formula", "none")
PASS_TYPES = ("prune", "rhythm", "distort", "callback", "selfrev")
REWRITE_MODES = ("gated_retry", "zero_revision")
GATE_FAIL_ACTIONS = ("revise", "record")
THINK_TIERS = ("chat", "reasoner")
SELECTIONS = ("round_robin", "recency", "relevant")
POSITIONS = ("head", "tail", "u")
TEMPLATES = ("single", "custom")  # lab:<人格> 为前缀形，见 _validate_template

GATE_KEYS = {"length", "fingerprint", "echo_check", "citation", "copyright",
             "topic_dedup", "custom"}


def _err(errors: list[str], path: str, msg: str) -> None:
    errors.append(f"{path}: {msg}")


def _type_err(errors: list[str], path: str, value: object, expect: str) -> None:
    _err(errors, path, f"类型错误，期望 {expect}，实得 {type(value).__name__}")


def _require_dict(data: dict, key: str, path: str, errors: list[str]) -> dict | None:
    v = data.get(key)
    if v is None:
        _err(errors, f"{path}.{key}", "缺失必填字段")
        return None
    if not isinstance(v, dict):
        _type_err(errors, f"{path}.{key}", v, "object")
        return None
    return v


def _require_str(data: dict, key: str, path: str, errors: list[str]) -> str | None:
    v = data.get(key)
    if v is None:
        _err(errors, f"{path}.{key}", "缺失必填字段")
        return None
    if not isinstance(v, str) or not v.strip():
        _err(errors, f"{path}.{key}", f"必须为非空字符串，实得 {v!r}")
        return None
    return v


def _int_field(data: dict, key: str, path: str, errors: list[str], *,
               required: bool = True, default: int | None = None,
               lo: int | None = None, hi: int | None = None) -> int | None:
    v = data.get(key)
    if v is None:
        if required:
            _err(errors, f"{path}.{key}", "缺失必填字段")
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _type_err(errors, f"{path}.{key}", v, "int")
        return default
    if lo is not None and v < lo:
        _err(errors, f"{path}.{key}", f"须 ≥{lo}，实得 {v}")
    if hi is not None and v > hi:
        _err(errors, f"{path}.{key}", f"须 ≤{hi}，实得 {v}")
    return v


def _float_field(data: dict, key: str, path: str, errors: list[str], *,
                 required: bool = False, default: float | None = None) -> float | None:
    v = data.get(key)
    if v is None:
        if required:
            _err(errors, f"{path}.{key}", "缺失必填字段")
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _type_err(errors, f"{path}.{key}", v, "number")
        return default
    return float(v)


def _bool_field(data: dict, key: str, path: str, errors: list[str], *,
                required: bool = True, default: bool | None = None) -> bool | None:
    v = data.get(key)
    if v is None:
        if required:
            _err(errors, f"{path}.{key}", "缺失必填字段")
        return default
    if not isinstance(v, bool):
        _type_err(errors, f"{path}.{key}", v, "bool")
        return default
    return v


def _enum_field(data: dict, key: str, path: str, errors: list[str],
                allowed: tuple[str, ...], *, required: bool = True,
                default: str | None = None) -> str | None:
    v = data.get(key)
    if v is None:
        if required:
            _err(errors, f"{path}.{key}", "缺失必填字段")
        return default
    if not isinstance(v, str) or v not in allowed:
        _err(errors, f"{path}.{key}", f"须为 {'|'.join(allowed)} 之一，实得 {v!r}")
        return default
    return v


def _str_list(data: dict, key: str, path: str, errors: list[str], *,
              required: bool = True) -> list:
    v = data.get(key)
    if v is None:
        if required:
            _err(errors, f"{path}.{key}", "缺失必填字段")
        return []
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _err(errors, f"{path}.{key}", "必须为字符串数组")
        return []
    return v


# ---------------- 各层校验 ----------------

def _validate_template(data: dict, path: str, errors: list[str]) -> None:
    v = _require_str(data, "template", path, errors)
    if v is None:
        return
    if not (v in TEMPLATES or v.startswith("lab:")):
        _err(errors, f"{path}.template", f"须为 single|custom|lab:<人格>，实得 {v!r}")


def _validate_identity(identity: dict, errors: list[str]) -> None:
    path = "identity"
    _require_str(identity, "name", path, errors)
    for key in ("description", "personality", "values_stance", "scenario", "style_anchor"):
        v = identity.get(key)
        if v is None:
            _err(errors, f"{path}.{key}", "缺失必填字段")
        elif not isinstance(v, str):
            _type_err(errors, f"{path}.{key}", v, "string")
    rules = _require_dict(identity, "style_rules", path, errors)
    if rules is not None:
        _str_list(rules, "do", f"{path}.style_rules", errors)
        _str_list(rules, "dont", f"{path}.style_rules", errors)
        _str_list(rules, "fingerprint", f"{path}.style_rules", errors)
        extra = rules.get("extra_checks", {})
        if extra is not None and not isinstance(extra, dict):
            _type_err(errors, f"{path}.style_rules.extra_checks", extra, "object")
    if "quotes_original" not in identity:
        _err(errors, f"{path}.quotes_original", "缺失必填字段")
    elif not isinstance(identity["quotes_original"], list):
        _type_err(errors, f"{path}.quotes_original", identity["quotes_original"], "array")
    prov = identity.get("provenance")
    if prov is None:
        _err(errors, f"{path}.provenance", "缺失必填字段")
    elif not isinstance(prov, list) or any(not isinstance(x, str) for x in prov):
        _err(errors, f"{path}.provenance", "必须为字符串数组（来源标注）")


def _validate_pass_entry(entry: object, i: int, errors: list[str]) -> None:
    path = f"route.passes[{i}]"
    if not isinstance(entry, dict):
        _type_err(errors, path, entry, "object")
        return
    _enum_field(entry, "type", path, errors, PASS_TYPES)
    params = entry.get("params", {})
    if params is not None and not isinstance(params, dict):
        _type_err(errors, f"{path}.params", params, "object")


def _validate_gates(gates: dict, errors: list[str]) -> None:
    path = "route.gates"
    unknown = set(gates) - GATE_KEYS
    if unknown:
        _err(errors, path, f"未知门禁名: {sorted(unknown)}（合法: {sorted(GATE_KEYS)}）")
    for key in ("length", "fingerprint", "echo_check", "citation", "copyright",
                "topic_dedup", "custom"):
        if key not in gates:
            _err(errors, f"{path}.{key}", "缺失必填字段（门禁开关须显式声明，可配 false/[] 关闭）")
    length = gates.get("length")
    if isinstance(length, dict):
        _int_field(length, "min", f"{path}.length", errors, lo=0)
        _int_field(length, "max", f"{path}.length", errors, lo=0)
        unit = length.get("unit")
        if unit is not None and unit != "chars":
            _err(errors, f"{path}.length.unit", f"本阶段仅支持 chars，实得 {unit!r}")
    fp = gates.get("fingerprint")
    if isinstance(fp, dict):
        _int_field(fp, "min_hits", f"{path}.fingerprint", errors, lo=0)
    echo = gates.get("echo_check")
    if echo is not None and not isinstance(echo, bool):
        _type_err(errors, f"{path}.echo_check", echo, "bool")
    citation = gates.get("citation")
    if isinstance(citation, dict):
        _int_field(citation, "min_count", f"{path}.citation", errors, lo=0)
    cr = gates.get("copyright")
    if isinstance(cr, dict):
        _int_field(cr, "ngram", f"{path}.copyright", errors, lo=2, hi=64)
    td = gates.get("topic_dedup")
    if isinstance(td, dict):
        _int_field(td, "recent_n", f"{path}.topic_dedup", errors, lo=0)
        _float_field(td, "threshold", f"{path}.topic_dedup", errors)
    custom = gates.get("custom")
    if custom is not None and not isinstance(custom, list):
        _type_err(errors, f"{path}.custom", custom, "array")


def _validate_route(route: dict, errors: list[str]) -> None:
    path = "route"
    outline = _require_dict(route, "outline", path, errors)
    if outline is not None:
        op = f"{path}.outline"
        _enum_field(outline, "template", op, errors, OUTLINE_TEMPLATES)
        if "params" not in outline:
            _err(errors, f"{op}.params", "缺失必填字段")
        elif not isinstance(outline["params"], dict):
            _type_err(errors, f"{op}.params", outline["params"], "object")
    draft = _require_dict(route, "draft", path, errors)
    if draft is not None:
        dp = f"{path}.draft"
        _enum_field(draft, "mode", dp, errors, DRAFT_MODES)
        params = _require_dict(draft, "params", dp, errors)
        if params is not None:
            _int_field(params, "max_tokens", dp, errors, required=False, lo=64)
            think = params.get("think", False)
            if not isinstance(think, bool):
                _type_err(errors, f"{dp}.params.think", think, "bool")
    passes = route.get("passes")
    if passes is None:
        _err(errors, f"{path}.passes", "缺失必填字段")
    elif not isinstance(passes, list):
        _type_err(errors, f"{path}.passes", passes, "array")
    else:
        for i, entry in enumerate(passes):
            _validate_pass_entry(entry, i, errors)
    gates = _require_dict(route, "gates", path, errors)
    if gates is not None:
        _validate_gates(gates, errors)
    rewrite = _require_dict(route, "rewrite", path, errors)
    if rewrite is not None:
        rp = f"{path}.rewrite"
        _enum_field(rewrite, "mode", rp, errors, REWRITE_MODES)
        _int_field(rewrite, "max_attempts", rp, errors, lo=1, hi=10)
        _enum_field(rewrite, "on_gate_fail", rp, errors, GATE_FAIL_ACTIONS)
    tr = _require_dict(route, "think_routing", path, errors)
    if tr is not None:
        tp = f"{path}.think_routing"
        _enum_field(tr, "default", tp, errors, THINK_TIERS)
        per_node = tr.get("per_node", {})
        if per_node is None:
            per_node = {}
        if not isinstance(per_node, dict) or any(
                v not in THINK_TIERS for v in per_node.values()):
            _err(errors, f"{tp}.per_node", "必须为 object 且值为 chat|reasoner")
        else:
            unknown = [k for k in per_node if not k.startswith("w_") and k != "writing"]
            if unknown:
                _err(errors, f"{tp}.per_node",
                     f"节点名须为调用点（w_* 前缀或 writing）: {unknown}")


def _validate_memory(memory: dict, errors: list[str]) -> None:
    path = "memory"
    blocks = memory.get("static_blocks")
    if blocks is None:
        _err(errors, f"{path}.static_blocks", "缺失必填字段")
    elif not isinstance(blocks, list):
        _type_err(errors, f"{path}.static_blocks", blocks, "array")
    else:
        seen_ids: set[str] = set()
        for i, b in enumerate(blocks):
            bp = f"{path}.static_blocks[{i}]"
            if not isinstance(b, dict):
                _type_err(errors, bp, b, "object")
                continue
            bid = _require_str(b, "id", bp, errors)
            if bid and bid in seen_ids:
                _err(errors, f"{bp}.id", f"重复的块 id: {bid!r}")
            seen_ids.add(bid or "")
            _require_str(b, "text", bp, errors)
            _require_str(b, "source", bp, errors)
            inj = _require_dict(b, "injection", bp, errors)
            if inj is not None:
                _int_field(inj, "max_chars", f"{bp}.injection", errors, lo=1)
    injection = _require_dict(memory, "injection", path, errors)
    if injection is not None:
        ip = f"{path}.injection"
        _int_field(injection, "max_slices_per_run", ip, errors, lo=0)
        _int_field(injection, "per_block_max_chars", ip, errors, lo=1)
        _enum_field(injection, "selection", ip, errors, SELECTIONS)
        _enum_field(injection, "position", ip, errors, POSITIONS)
    dm = memory.get("dynamic_modules")
    if dm is None:
        _err(errors, f"{path}.dynamic_modules", "缺失必填字段")
    elif not isinstance(dm, dict) or any(
            not isinstance(v, int) or isinstance(v, bool) for v in dm.values()):
        _err(errors, f"{path}.dynamic_modules", "必须为 object 且值为 int（占位符名 → 载入条数）")


def _validate_output(output: dict, errors: list[str]) -> None:
    path = "output"
    fmt = _require_str(output, "format", path, errors)
    if fmt is not None and fmt != "markdown":
        _err(errors, f"{path}.format", f"本阶段仅支持 markdown，实得 {fmt!r}")
    _bool_field(output, "footnote_citations", path, errors)
    mtn = output.get("max_tokens_per_node", {})
    if mtn is None:
        mtn = {}
    if not isinstance(mtn, dict) or any(
            not isinstance(v, int) or isinstance(v, bool) for v in mtn.values()):
        _err(errors, f"{path}.max_tokens_per_node", "必须为 object 且值为 int")


def validate_author_json(data: object) -> list[str]:
    """校验 author.json；返回错误列表（空列表=合法）。顶层必须是 dict。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"(root): 顶层必须为 object，实得 {type(data).__name__}"]
    _require_str(data, "id", "(root)", errors)
    _validate_template(data, "(root)", errors)
    identity = _require_dict(data, "identity", "(root)", errors)
    if identity is not None:
        _validate_identity(identity, errors)
    route = _require_dict(data, "route", "(root)", errors)
    if route is not None:
        _validate_route(route, errors)
    memory = _require_dict(data, "memory", "(root)", errors)
    if memory is not None:
        _validate_memory(memory, errors)
    output = _require_dict(data, "output", "(root)", errors)
    if output is not None:
        _validate_output(output, errors)
    _require_str(data, "version", "(root)", errors)
    return errors


class AuthorConfigError(Exception):
    """author.json 校验失败（message 含全部错误）。"""


def load_author_config(data: object) -> dict:
    """校验并返回配置 dict；失败抛 AuthorConfigError（全部错误一次报出）。"""
    errors = validate_author_json(data)
    if errors:
        raise AuthorConfigError("author.json 校验失败:\n" + "\n".join(f"- {e}" for e in errors))
    return data  # type: ignore[return-value]


def default_author_config(author_id: str, name: str, *, version: str = "2026-09-29-a") -> dict:
    """生成一份合法的默认配置（single 路线，无静态块），供测试与快速建作者用。"""
    return {
        "id": author_id,
        "template": "single",
        "identity": {
            "name": name,
            "description": "",
            "personality": "",
            "values_stance": "",
            "scenario": "",
            "style_anchor": "",
            "style_rules": {"do": [], "dont": [], "fingerprint": [], "extra_checks": {}},
            "quotes_original": [],
            "provenance": ["自创（默认配置）"],
        },
        "route": {
            "outline": {"template": "none", "params": {}},
            "draft": {"mode": "single", "params": {"max_tokens": 4000, "think": False}},
            "passes": [],
            "gates": {
                "length": {"min": 600, "max": 1400, "unit": "chars"},
                "fingerprint": {"min_hits": 0},
                "echo_check": False,
                "citation": {"min_count": 2},
                "copyright": {"ngram": 8},
                "topic_dedup": {"recent_n": 5},
                "custom": [],
            },
            "rewrite": {"mode": "gated_retry", "max_attempts": 3, "on_gate_fail": "revise"},
            "think_routing": {"default": "chat", "per_node": {}},
        },
        "memory": {
            "static_blocks": [],
            "injection": {
                "max_slices_per_run": 0,
                "per_block_max_chars": 500,
                "selection": "round_robin",
                "position": "head",
            },
            "dynamic_modules": {"feedback_memory": 5, "topic_memory": 5},
        },
        "output": {"format": "markdown", "footnote_citations": True, "max_tokens_per_node": {}},
        "version": version,
    }
