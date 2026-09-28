"""导入 author.json 到 DB（用法：python scripts/import_authors.py authors/luxun.json ...）。

模型绑定必须显式给出（--model），或对既有作者省略（保留原绑定）——模型不进 JSON。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.authors.importer import import_author_json_file, roundtrip_check  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Author  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--model", default=None, help="运行时模型绑定（新作者必填）")
    ap.add_argument("--directions", default="[{\"direction_id\": 1, \"threshold\": 60}]",
                    help="readable_directions JSON")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        for f in args.files:
            cfg_model = args.model
            if cfg_model is None:
                existing = db.query(Author).filter_by(
                    name=__import__("json").loads(
                        Path(f).read_text(encoding="utf-8"))["identity"]["name"]).first()
                if existing is None:
                    sys.exit(f"[import] {f}: 新作者必须显式 --model（模型不进 JSON）")
            author = import_author_json_file(
                db, f, model=cfg_model,
                readable_directions=__import__("json").loads(args.directions))
            ok, diffs = roundtrip_check(author, author.author_json)
            print(f"[import] {f} -> author id={author.id} name={author.name} "
                  f"model={author.model} roundtrip={'OK' if ok else diffs}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
