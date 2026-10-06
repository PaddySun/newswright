"""author.json ↔ DB Author 导入导出（M16 round-trip 校验用）。

分层纪律：author_json 列存全量配置（身份资产，可导出/版本管理）；DB 侧运行时
字段（model/persona_prompt/memory_config/readable_directions）由 JSON 派生或
独立绑定——**model 永不从 JSON 来**（后台/DB 绑定）。

persona_prompt = identity 层的扁平渲染（供无 JSON 代码路径/后台展示兼容）；
有 JSON 的作者写作走 pipeline.py，不读 persona_prompt。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Author
from .schema import AuthorConfigError, load_author_config


def render_persona_prompt(cfg: dict) -> str:
    """identity 层扁平渲染（后台可见的作者人设文本）。"""
    ident = cfg["identity"]
    rules = ident.get("style_rules", {})
    parts = [
        f"【身份】{ident.get('name', '')}",
        f"【传记事实】{ident.get('description', '')}",
        f"【人格与思维】{ident.get('personality', '')}",
        f"【价值立场】{ident.get('values_stance', '')}",
        f"【场景】{ident.get('scenario', '')}",
        "【文风——必须】" + "；".join(rules.get("do", [])),
        "【文风——禁止】" + "；".join(rules.get("dont", [])),
        "【风格指纹】" + "、".join(rules.get("fingerprint", [])),
        f"【配置来源】author.json id={cfg.get('id')} version={cfg.get('version')} "
        f"route={cfg['route']['outline']['template']}/{cfg['route']['draft']['mode']}"
        f"+{'/'.join(p['type'] for p in cfg['route'].get('passes', [])) or '直发'}",
    ]
    return "\n".join(parts)


def import_author_json(
    db: Session,
    data: dict,
    *,
    model: str | None = None,
    readable_directions: list | None = None,
    rank_provider: str | None = None,
) -> Author:
    """校验并导入 author.json → DB Author（按 identity.name upsert）。

    model/readable_directions/rank_provider 为运行时绑定参数：显式传入则覆盖，
    未传入时既有作者保留原值、新作者必须给 model（模型不在 JSON 中）。
    """
    cfg = load_author_config(copy.deepcopy(data))
    name = cfg["identity"]["name"]
    author = db.query(Author).filter_by(name=name).first()
    if author is None:
        if not model:
            raise AuthorConfigError(f"新作者 {name!r} 需要显式 model 绑定（模型不在 JSON 中）")
        author = Author(name=name, model=model)
        db.add(author)
    if model:
        author.model = model
    if readable_directions is not None:
        author.readable_directions = readable_directions
    if rank_provider is not None:
        author.rank_provider = rank_provider
    dm = cfg["memory"].get("dynamic_modules") or {}
    if dm:
        author.memory_config = {f"{k}_memory" if not k.endswith("_memory") else k: v
                                for k, v in dm.items()}
    # 呈现层可选键：bio/public_visible 携带时覆盖 DB 列，缺省保持原值（旧文档兼容）
    if "bio" in cfg and cfg["bio"] is not None:
        author.bio = str(cfg["bio"])
    if "public_visible" in cfg and cfg["public_visible"] is not None:
        author.public_visible = bool(cfg["public_visible"])
    author.persona_prompt = render_persona_prompt(cfg)
    author.author_json = cfg
    db.commit()
    return author


def import_author_json_file(db: Session, path: str | Path, **kwargs) -> Author:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return import_author_json(db, data, **kwargs)


def export_author_json(author: Author) -> dict:
    """导出 author.JSON：身份资产全量 + 呈现层两列（bio/public_visible）随文档
    一起走——导出文档再导入即恢复同一作者的完整呈现配置（round-trip 一致）。"""
    if not author.author_json:
        raise ValueError(f"作者 {author.name!r} 没有 author.json 配置")
    out = copy.deepcopy(author.author_json)
    out["bio"] = author.bio or ""
    out["public_visible"] = bool(author.public_visible)
    return out


def roundtrip_check(author: Author, original: dict) -> tuple[bool, list[str]]:
    """JSON ↔ DB 一致性：DB 中 author_json 与导入原文件逐字段一致。"""
    stored = author.author_json or {}
    diffs: list[str] = []

    def walk(a: object, b: object, path: str) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            for k in set(a) | set(b):
                if k not in a:
                    diffs.append(f"{path}.{k}: DB 多出")
                elif k not in b:
                    diffs.append(f"{path}.{k}: DB 缺失")
                else:
                    walk(a[k], b[k], f"{path}.{k}")
        elif a != b:
            diffs.append(f"{path}: {b!r} != {a!r}")

    walk(stored, original, "(root)")
    return not diffs, diffs
