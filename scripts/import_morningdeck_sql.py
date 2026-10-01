"""morningdeck PG dump（COPY 格式）→ SQLite scratch 分析库（向量与排序实测数据底座）。

用法：
    .venv/Scripts/python scripts/import_morningdeck_sql.py <dump.sql.gz> <out.sqlite3>

输入：pg_dump 16.15 纯文本格式（gzip），数据段为 `COPY public.<table> (...) FROM stdin;`
到 `\\.` 的行。输出：SQLite 库，列名与 PG 一致、类型按 PG 映射 SQLite 亲和性
（boolean t/f→0/1，整型/浮点转型，失败保留原文），scratch 库 gitignore（*.db），不入仓。

转义还原（PG COPY text 格式）：\\b \\f \\n \\r \\t \\v \\\\ 以及 \\xNN 十六进制；
\\N = NULL。其余反斜杠序列按字面保留（不做猜测性还原）。
"""
from __future__ import annotations

import gzip
import re
import sqlite3
import sys

CREATE_RE = re.compile(r"CREATE TABLE (?:public\.)?(\w+) \((.*?)\n\)", re.S)
COPY_RE = re.compile(r"COPY (?:public\.)?(\w+) \(([^)]*)\) FROM stdin;", re.M)

_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\"}

_INT_TYPES = {"integer", "bigint", "smallint"}
_REAL_TYPES = {"numeric", "real", "double precision"}
# PG 类型 → SQLite 声明（决定值亲和性）
AFFINITY = {
    "uuid": "TEXT", "character varying": "TEXT", "varchar": "TEXT", "text": "TEXT",
    "json": "TEXT", "jsonb": "TEXT", "timestamp with time zone": "TEXT",
    "timestamp without time zone": "TEXT", "time without time zone": "TEXT", "date": "TEXT",
    "integer": "INTEGER", "bigint": "INTEGER", "smallint": "INTEGER",
    "numeric": "REAL", "real": "REAL", "double precision": "REAL",
    "boolean": "INTEGER", "bytea": "BLOB",
}


def unescape_field(raw: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        if i + 1 >= len(raw):
            out.append(ch)
            break
        nxt = raw[i + 1]
        if nxt in _ESCAPES:
            out.append(_ESCAPES[nxt])
            i += 2
        elif nxt == "x":
            hexpart = raw[i + 2 : i + 4]
            try:
                out.append(chr(int(hexpart, 16)))
                i += 4
            except ValueError:
                out.append(ch)
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_line(line: str) -> list[str | None]:
    fields = line.split("\t")
    return [None if f == "\\N" else unescape_field(f) for f in fields]


def coerce(val: str | None, pg_type: str | None) -> object:
    """COPY 文本值 → SQLite 值：boolean t/f→1/0，整型/浮点转型，失败保留原文。"""
    if val is None:
        return None
    if pg_type == "boolean":
        return 1 if val == "t" else (0 if val == "f" else val)
    if pg_type in _INT_TYPES:
        try:
            return int(val)
        except ValueError:
            return val
    if pg_type in _REAL_TYPES:
        try:
            return float(val)
        except ValueError:
            return val
    return val


def parse_schema(txt: str) -> tuple[dict[str, list[tuple[str, str]]], dict[str, list[str]]]:
    """返回 {table: [(col, pg_type)]} 与 {table: [col]}。"""
    cols_by_table: dict[str, list[tuple[str, str]]] = {}
    for name, body in CREATE_RE.findall(txt):
        depth = 0
        cur: list[str] = []
        parts: list[str] = []
        for ch in body:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append("".join(cur))
                cur = []
            else:
                cur.append(ch)
        parts.append("".join(cur))
        cols: list[tuple[str, str]] = []
        for p in parts:
            p = p.strip()
            if not p or p.startswith(("CONSTRAINT", "PRIMARY KEY", "UNIQUE", "CHECK", "FOREIGN", "EXCLUDE")):
                continue
            m = re.match(r'"?(\w+)"?\s+(.*?)(?:\s+NOT NULL|\s+DEFAULT|\s+REFERENCES|\s+NULL\s*$|\s*$)', p)
            if m and m.group(1).upper() not in ("PRIMARY", "UNIQUE", "CHECK", "CONSTRAINT", "FOREIGN", "EXCLUDE"):
                cols.append((m.group(1), m.group(2).strip().lower()))
        cols_by_table[name] = cols
    return cols_by_table, {t: [c for c, _ in v] for t, v in cols_by_table.items()}


def main(dump_path: str, out_path: str) -> None:
    opener = gzip.open if dump_path.endswith(".gz") else open
    with opener(dump_path, "rt", encoding="utf-8", errors="replace") as f:
        txt = f.read()

    schema_cols, plain_cols = parse_schema(txt)
    con = sqlite3.connect(out_path)
    imported: dict[str, int] = {}
    for m in COPY_RE.finditer(txt):
        table, colstr = m.group(1), m.group(2)
        cols = [c.strip().strip('"') for c in colstr.split(",")]
        start = m.end()
        end = txt.find("\n\\.", start)
        if end == -1:
            end = len(txt)
        data = txt[start:end]
        if data.startswith("\n"):
            data = data[1:]
        col_specs = schema_cols.get(table) or [(c, "text") for c in cols]
        ddl_cols = [c for c, _ in col_specs]
        pg_types = {c: t for c, t in col_specs}
        col_defs = ", ".join(f'"{c}" {AFFINITY.get(pg_types[c], "TEXT")}' for c in ddl_cols)
        con.execute(f'DROP TABLE IF EXISTS "{table}"')
        con.execute(f'CREATE TABLE "{table}" ({col_defs})')
        placeholders = ",".join("?" * len(ddl_cols))
        insert_sql = f'INSERT INTO "{table}" ({", ".join(chr(34)+c+chr(34) for c in ddl_cols)}) VALUES ({placeholders})'
        count = 0
        bad_rows = 0
        for line in data.split("\n"):
            if not line:
                continue
            vals = parse_line(line)
            if len(vals) != len(ddl_cols):
                # 列数不符的脏行：如实计数，多列截断/少列补空导入（不做猜测性修补）
                bad_rows += 1
                vals = (vals + [None] * len(ddl_cols))[: len(ddl_cols)]
            con.execute(
                insert_sql,
                [coerce(v, pg_types.get(c)) for v, c in zip(vals, ddl_cols)],
            )
            count += 1
        con.commit()
        if bad_rows:
            print(f"  {table}: {bad_rows} malformed lines (padded/truncated)")
        imported[table] = count
        print(f"{table}: {count} rows ({len(ddl_cols)} cols)")
    con.close()
    print("done:", imported)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
