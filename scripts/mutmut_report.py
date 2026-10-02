#!/usr/bin/env python3
"""mutmut HTML 报告生成器 v3 / Mutation testing HTML report generator v3.

数据源优先级：.meta 文件（原始判定，逐变异体 exit code）> mutmut results 文本。
v3 新增（用户 2026-10-03 要求的精确诊断六要素）：
  1) 覆盖信息/测试套件标识——mutmut-stats.json 的 tests_by_mangled_function_name；
  2) 原始源码位置——模块→文件路径 + diff hunk 推断行号 + GitHub 永久链接（--sha）；
  3) 变异算子类型——按 diff 形态推断（标注"推断"）；
  4) mutmut 配置/运行器——setup.cfg 全文与版本入元信息块；
  5) 测试运行结果——mutmut 不按幸存者保存逐条输出，以"覆盖测试 + 复跑命令"等价替代（如实标注）；
  6) 一键复制——纯文本块 / 「复制给 Agent」（含以上全部字段与分诊指令头）。
仍为单文件零第三方依赖；--skip-diffs 支持无 mutmut 环境渲染。
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

EXIT_STATUS = {1: "killed", 3: "killed", 0: "survived", 5: "no tests", 33: "no tests",
               34: "skipped", 35: "suspicious", 36: "timeout", 2: "interrupted"}

STATUS_LABEL = {"survived": "幸存 Survived", "killed": "杀死 Killed", "no tests": "无测试 No tests",
                "timeout": "超时 Timeout", "suspicious": "可疑 Suspicious", "skipped": "跳过 Skipped",
                "interrupted": "中断 Interrupted", "not checked": "未检查 Not checked"}
STATUS_CLASS = {"survived": "st-surv", "killed": "st-kill", "no tests": "st-note", "timeout": "st-warn",
                "suspicious": "st-warn", "skipped": "st-note", "interrupted": "st-note",
                "not checked": "st-note"}

AGENT_HEAD = (
    "你是 newswright 项目的测试补强 Agent。下面是一个存活的变异体（mutmut survivor）及其覆盖测试信息。请：\n"
    "1) 判断类别：(a) 等价变异——不改变可观察行为，标记豁免；\n"
    "              (b) 防御性分支——正常运行难以触达的防御代码，建议登记豁免清单；\n"
    "              (c) 真实测试缺口——需要补测试；\n"
    "2) 若为 (c)：优先检查覆盖测试为何没杀掉它（断言缺口 or 未触发路径），写一个在该变异下会失败的\n"
    "    pytest 测试（风格与 tests/ 现有用例一致），可先用复跑命令本地验证。\n"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="生成 mutmut 双语 HTML 报告 v3")
    p.add_argument("--out", default="mutmut-report.html")
    p.add_argument("--txt-out", default=None, help="同时写出聚合清单文本（artifact 用）")
    p.add_argument("--meta-dir", default=None, help="mutants/ 目录（.meta 直读，最优先）")
    p.add_argument("--results-file", default=None, help="mutmut results 文本（无 .meta 时回退）")
    p.add_argument("--stats", default=None, help="mutmut-stats.json 路径（覆盖测试映射）")
    p.add_argument("--ref", default="", help="触发 ref（元信息）")
    p.add_argument("--sha", default="", help="commit sha（生成 GitHub 源码永久链接）")
    p.add_argument("--max-diffs", type=int, default=800)
    p.add_argument("--skip-diffs", action="store_true")
    return p.parse_args()


def load_from_meta(meta_dir: str) -> list[tuple[str, str]]:
    rows = []
    for f in sorted(Path(meta_dir).rglob("*.meta")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for key, code in data.get("exit_code_by_key", {}).items():
            st = EXIT_STATUS.get(code, "not checked" if code is None else "suspicious")
            rows.append((key, st))
    return rows


RE_LINE = re.compile(r"^\s*(?P<name>\S+__mutmut_\d+)\s*:\s*(?P<status>.+?)\s*$")


def load_from_results(path: str) -> list[tuple[str, str]]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = RE_LINE.match(line)
        if m:
            rows.append((m.group("name"), m.group("status")))
    return rows


def mutmut_show(name: str) -> str:
    try:
        r = subprocess.run(["mutmut", "show", name], capture_output=True, text=True, timeout=60)
        return (r.stdout or r.stderr or "(无输出)").strip()
    except Exception as e:  # noqa: BLE001
        return f"(show 调用失败 call-failed: {e})"


def split_name(name: str) -> tuple[str, str]:
    head = name.split("__mutmut_")[0]
    if "." in head:
        mod, func = head.rsplit(".", 1)
        return mod, func
    return "(root)", head


def module_to_path(module: str) -> str:
    return module.replace(".", "/") + ".py" if module != "(root)" else module


def parse_diff(diff: str) -> tuple[int | None, str]:
    """返回 (推断起始行号, 推断变异算子类型)。"""
    m = re.search(r"@@ -(\d+)", diff or "")
    lineno = int(m.group(1)) if m else None
    changed = "\n".join(l for l in (diff or "").splitlines() if l[:1] in "+-")
    kind = "语句 statement"
    if re.search(r"XX\w*XX", changed):
        kind = "字符串字面量 string-literal"
    elif re.search(r"\b(True|False|None)\b", changed):
        kind = "布尔/None 翻转 bool-flip"
    elif re.search(r"\b(is|not|and|or|in)\b", changed) or re.search(r"[=!<>]=", changed) or re.search(r"(?<=[\w\)\]])\s*(<|>)\s*", changed):
        kind = "运算符 operator"
    elif re.search(r"^[-+].*\b\d+(\.\d+)?\b", changed, re.M):
        kind = "数值字面量 numeric-literal"
    elif re.search(r"^[-+]\s*(return|raise)\b", changed, re.M | re.I):
        kind = "返回/抛出 return-raise"
    return lineno, kind


def load_stats(path: str | None) -> dict:
    if path and Path(path).exists():
        try:
            d = json.loads(Path(path).read_text(encoding="utf-8"))
            return {"tests": d.get("tests_by_mangled_function_name", {}),
                    "durations": d.get("duration_by_test", {})}
        except Exception:
            pass
    return {"tests": {}, "durations": {}}


def e(s: str) -> str:
    return html.escape(str(s), quote=True)


def fmt_tests(tests: list[str], durations: dict) -> tuple[str, str]:
    if not tests:
        return "（stats 未映射到用例 / no covering test mapped — 属 no-tests 缺口候选）", ""
    shown = "\n".join(f"- {t}（{durations.get(t, '?'):.2f}s）" if isinstance(durations.get(t), float) else f"- {t}" for t in tests[:6])
    extra = f"\n…共 {len(tests)} 条" if len(tests) > 6 else ""
    repro = "python -m pytest " + " ".join(tests[:3]) + " -x -q"
    return shown + extra, repro


def metric_cards(stats: dict) -> str:
    checked = stats["total"] - stats["no tests"]
    rate = (stats["killed"] / checked * 100) if checked else 0.0
    cards = [
        ("总变异体 Total Mutants", stats["total"], "c-total"),
        ("杀死 Killed", stats["killed"], "c-kill"),
        ("杀死率 Kill Rate", f"{rate:.1f}%", "c-rate"),
        ("幸存 Survived", stats["survived"], "c-surv"),
        ("无测试覆盖 No Tests", stats["no tests"], "c-note"),
        ("超时·可疑 Timeout·Suspicious", stats["timeout"] + stats["suspicious"], "c-warn"),
    ]
    cells = "".join(
        f'<div class="card {cls}"><div class="num">{e(val)}</div><div class="lbl">{e(lbl)}</div></div>'
        for lbl, val, cls in cards)
    return f'<div class="cards">{cells}</div>'


def module_table(mod_stats: dict) -> str:
    rows = []
    for mod in sorted(mod_stats, key=lambda m: (-mod_stats[m]["survived"], m)):
        s = mod_stats[mod]
        checked = s["total"] - s["no tests"]
        rate = (s["killed"] / checked * 100) if checked else 0.0
        rows.append(
            f'<tr><td><a href="#mod-{e(mod)}">{e(mod)}</a></td><td class="n">{s["total"]}</td>'
            f'<td class="n k">{s["killed"]}</td><td class="n s">{s["survived"]}</td>'
            f'<td class="n">{s["no tests"]}</td><td class="rate"><div class="bar"><i style="width:{rate:.1f}%"></i></div>'
            f"<span>{rate:.1f}%</span></td></tr>")
    return ('<table class="mods"><thead><tr><th>模块 Module</th><th>总数 Total</th><th>杀死 K</th>'
            "<th>幸存 S</th><th>无测试 N</th><th>杀死率 Kill Rate</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


def item_block(module: str, fname: str, num: str, status: str, diff: str | None,
               stats: dict, sha: str) -> str:
    path = module_to_path(module)
    lineno, mtype = parse_diff(diff or "")
    link = f"https://github.com/PaddySun/newswright/blob/{sha}/{path}" + (f"#L{lineno}" if (sha and lineno) else "")
    tests_html, repro = fmt_tests(stats["tests"].get(f"{module}.{fname}", []), stats["durations"])
    diff_html = (f'<pre class="diff">{e(diff)}</pre>' if diff is not None
                 else '<p class="nodiff">（超出 --max-diffs 上限 / diff not fetched）</p>')
    plain = (f"module: {module}\nmutant: {fname}__mutmut_{num}\nstatus: {status}\n"
             f"mutator(inferred): {mtype}\nsource: {path}"
             + (f":~{lineno}(diff 推断)" if lineno else "") + "\n"
             + (f"link: {link}\n" if link else "")
             + "covering_tests:\n" + "\n".join("  " + t for t in stats["tests"].get(f"{module}.{fname}", [])[:20] or ["  (none mapped)"]) + "\n"
             + (f"repro: {repro}\n" if repro else "")
             + (f"diff:\n{diff}\n" if diff is not None else ""))
    agent = AGENT_HEAD + plain
    return (
        f'<details class="item"><summary><span class="badge {STATUS_CLASS.get(status, "st-note")}">'
        f'{e(STATUS_LABEL.get(status, status))}</span> <span class="badge mt">{e(mtype)}</span> '
        f"<code>{e(fname)}__mutmut_{e(num)}</code></summary>"
        f'<div class="itembody">'
        f'<p class="meta">module: <code>{e(module)}</code> · source: '
        + (f'<a href="{e(link)}" target="_blank">{e(path)}{("~L" + str(lineno)) if lineno else ""} ↗</a>' if link else f"<code>{e(path)}</code>")
        + (f' · 行号为 diff hunk 推断 line inferred from hunk' if lineno else "")
        + "</p>"
        f'<p class="meta"><b>覆盖测试 covering tests</b>：<br>{e(tests_html)}</p>'
        + (f'<p class="meta">复跑 repro：<code>{e(repro)}</code></p>' if repro else "")
        + diff_html
        + f'<textarea class="payload" hidden>{e(plain)}</textarea>'
        f'<textarea class="payload-agent" hidden>{e(agent)}</textarea>'
        f'<div class="btns"><button onclick="cp(this,false)">📋 复制 Copy</button>'
        f'<button class="agentbtn" onclick="cp(this,true)">🤖 复制给 Agent Copy for Agent</button></div>'
        f"</div></details>")


def note_block(module: str, fname: str, num: str) -> str:
    plain = f"module: {module}\nmutant: {fname}__mutmut_{num}\nstatus: no tests\n"
    return (
        f'<details class="item"><summary><span class="badge st-note">无测试 No tests</span> '
        f"<code>{e(fname)}__mutmut_{e(num)}</code></summary>"
        f'<div class="itembody"><p class="meta">module: <code>{e(module)}</code> · '
        f"stats 阶段未映射到任何用例 / no covering test mapped</p>"
        f'<textarea class="payload" hidden>{e(plain)}</textarea>'
        f'<div class="btns"><button onclick="cp(this,false)">📋 复制 Copy</button></div>'
        f"</div></details>")


def render(rows: list[tuple[str, str]], args: argparse.Namespace, mutmut_ver: str,
           cfg_text: str, source_desc: str) -> str:
    stats = defaultdict(int)
    for _, st in rows:
        stats[st] += 1
    stats["total"] = len(rows)

    by_mod: dict[str, list] = defaultdict(list)
    mod_stats: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for name, st in rows:
        mod, func = split_name(name)
        num = name.split("__mutmut_")[-1]
        by_mod[mod].append((func, num, st))
        mod_stats[mod]["total"] += 1
        mod_stats[mod][st] += 1

    survivors = sorted(((m, f, n) for m, items in by_mod.items() for f, n, st in items if st == "survived"))
    n_shown = 0 if args.skip_diffs else min(len(survivors), args.max_diffs)
    st_json = load_stats(args.stats)

    surv_sections = []
    for mod in sorted(by_mod):
        surv_items = [(f, n) for f, n, st in by_mod[mod] if st == "survived"]
        if not surv_items:
            continue
        blocks = []
        for f, n in surv_items:
            diff = None
            if not args.skip_diffs and n_shown > 0:
                diff = mutmut_show(f"{mod}.{f}__mutmut_{n}")
                n_shown -= 1
            blocks.append(item_block(mod, f, n, "survived", diff, st_json, args.sha))
        surv_sections.append(f'<h3 id="mod-{e(mod)}">{e(mod)} <small>({len(surv_items)} 幸存 survivors)</small></h3>' + "".join(blocks))

    note_sections = []
    for mod in sorted(by_mod):
        notes = [(f, n) for f, n, st in by_mod[mod] if st == "no tests"]
        if not notes:
            continue
        blocks = "".join(note_block(mod, f, n) for f, n in notes)
        note_sections.append(f'<h3 id="note-{e(mod)}">{e(mod)} <small>({len(notes)} 无测试 no-tests)</small></h3>' + blocks)

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    diff_note = (f"已为前 {min(len(survivors), args.max_diffs)}/{len(survivors)} 个幸存者取回 diff"
                 if not args.skip_diffs else "（--skip-diffs，未取 diff）")
    cfg_html = e(cfg_text.strip() or "(setup.cfg 未找到)")
    meta = (f'生成 Generated: {e(now)} · ref: <code>{e(args.ref or "-")}</code> · '
            f'mutmut: <code>{e(mutmut_ver or "-")}</code> · 数据源 data source: <code>{e(source_desc)}</code> · {e(diff_note)}')

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mutmut 变异测试报告 Mutation Report — newswright</title>
<style>
 :root {{ --kill:#16a34a; --surv:#dc2626; --note:#6b7280; --warn:#d97706; --ink:#111827; --bg:#f8fafc; }}
 * {{ box-sizing:border-box; }}
 body {{ font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif; margin:0; padding:24px; background:var(--bg); color:var(--ink); }}
 h1 {{ font-size:22px; margin:0 0 4px; }} h1 small {{ font-weight:400; color:var(--note); font-size:14px; }}
 .meta {{ color:var(--note); font-size:12px; margin-bottom:10px; }}
 .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:12px 0 20px; }}
 .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:14px; text-align:center; }}
 .card .num {{ font-size:26px; font-weight:700; }} .card .lbl {{ font-size:12px; color:var(--note); margin-top:4px; }}
 .c-kill .num {{ color:var(--kill); }} .c-surv .num {{ color:var(--surv); }} .c-rate .num {{ color:#2563eb; }} .c-warn .num {{ color:var(--warn); }}
 .mods {{ border-collapse:collapse; width:100%; background:#fff; font-size:13px; margin-bottom:24px; }}
 .mods th,.mods td {{ border:1px solid #e5e7eb; padding:6px 10px; text-align:left; }}
 .mods th {{ background:#f1f5f9; }} .mods td.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
 td.k {{ color:var(--kill); }} td.s {{ color:var(--surv); font-weight:600; }}
 .rate {{ min-width:160px; }} .bar {{ background:#e5e7eb; height:8px; border-radius:4px; overflow:hidden; display:inline-block; width:100px; vertical-align:middle; }}
 .bar i {{ display:block; height:100%; background:var(--kill); }}
 h2 {{ font-size:17px; margin:28px 0 8px; }} h3 {{ font-size:14px; margin:18px 0 6px; color:#374151; }} h3 small {{ color:var(--note); font-weight:400; }}
 details.item {{ background:#fff; border:1px solid #e5e7eb; border-radius:8px; margin:4px 0; }}
 details.item summary {{ cursor:pointer; padding:6px 10px; font-size:13px; }}
 details.item[open] summary {{ border-bottom:1px solid #e5e7eb; }}
 .itembody {{ padding:8px 12px; }}
 .badge {{ display:inline-block; font-size:11px; border-radius:999px; padding:1px 8px; margin-right:4px; }}
 .mt {{ background:#ede9fe; color:#7c3aed; }}
 .st-kill {{ background:#dcfce7; color:var(--kill); }} .st-surv {{ background:#fee2e2; color:var(--surv); }}
 .st-note {{ background:#f3f4f6; color:var(--note); }} .st-warn {{ background:#fef3c7; color:var(--warn); }}
 pre.diff {{ background:#0f172a; color:#e2e8f0; padding:10px; border-radius:8px; font-size:12px; overflow:auto; max-height:340px; }}
 pre.cfg {{ background:#f1f5f9; padding:8px; border-radius:8px; font-size:12px; }}
 .nodiff {{ color:var(--note); font-size:12px; }}
 .btns {{ margin-top:6px; }} button {{ font-size:12px; padding:4px 10px; border-radius:6px; border:1px solid #d1d5db; background:#fff; cursor:pointer; }}
 button.agentbtn {{ border-color:#93c5fd; background:#eff6ff; }} button.ok {{ border-color:var(--kill); color:var(--kill); }}
 code {{ background:#f1f5f9; padding:0 4px; border-radius:4px; font-size:12px; }}
 .hint {{ color:var(--note); font-size:12px; margin:4px 0 0; }}
</style>
</head>
<body>
<h1>mutmut 变异测试报告 <small>Mutation Testing Report — newswright</small></h1>
<p class="meta">{meta}</p>
{metric_cards(stats)}
<h2>模块汇总 <small>Module Summary</small></h2>
{module_table(mod_stats)}
<h2>mutmut 配置 <small>Configuration &amp; Runner（setup.cfg）</small></h2>
<pre class="cfg">{cfg_html}</pre>
<h2>幸存者清单 <small>Survivors（点击展开 · 每条含覆盖测试/推断算子/源码链接/复跑命令，可一键复制）</small></h2>
<p class="hint">「🤖 复制给 Agent」自带三分类分诊指令头。注：mutmut 不按幸存者保存逐条测试输出，以覆盖测试清单+复跑命令等价替代。</p>
{''.join(surv_sections) or '<p class="hint">无幸存者 no survivors 🎉</p>'}
<h2>无测试覆盖清单 <small>No-Tests（覆盖缺口地图）</small></h2>
{''.join(note_sections) or '<p class="hint">无 no-tests 条目</p>'}
<script>
function cp(btn, agent) {{
  var box = btn.closest('.itembody');
  var ta = box.querySelector(agent ? '.payload-agent' : '.payload');
  var text = ta ? ta.value : '';
  function ok() {{ var old = btn.textContent; btn.textContent = '✅ 已复制 Copied'; btn.classList.add('ok');
    setTimeout(function() {{ btn.textContent = old; btn.classList.remove('ok'); }}, 1600); }}
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(ok, function() {{ fallback(); }});
  }} else {{ fallback(); }}
  function fallback() {{
    var t = document.createElement('textarea'); t.value = text; document.body.appendChild(t);
    t.select(); try {{ document.execCommand('copy'); ok(); }} catch (e) {{}} document.body.removeChild(t);
  }}
}}
</script>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    if args.meta_dir and Path(args.meta_dir).exists():
        rows = load_from_meta(args.meta_dir)
        source_desc = f".meta 直读 ({args.meta_dir})"
    elif args.results_file and Path(args.results_file).exists():
        rows = load_from_results(args.results_file)
        source_desc = f"results 文本 ({args.results_file})"
    else:
        r = subprocess.run(["mutmut", "results", "--all"], capture_output=True, text=True, timeout=120)
        rows = [m for line in (r.stdout or "").splitlines() if (m := RE_LINE.match(line))]
        source_desc = "mutmut results --all"
    if not rows:
        print("[mutmut_report] 未解析到任何变异体（无 .meta / results 为空）", file=sys.stderr)
        return 1
    try:
        v = subprocess.run(["mutmut", "--version"], capture_output=True, text=True, timeout=30)
        mutmut_ver = (v.stdout or v.stderr).strip().splitlines()[-1] if (v.stdout or v.stderr).strip() else ""
    except Exception:  # noqa: BLE001
        mutmut_ver = ""
    cfg_text = Path("setup.cfg").read_text(encoding="utf-8") if Path("setup.cfg").exists() else ""
    out = render(rows, args, mutmut_ver, cfg_text, source_desc)
    Path(args.out).write_text(out, encoding="utf-8")
    if args.txt_out:
        Path(args.txt_out).write_text(
            "".join(f"    {n}: {s}\n" for n, s in rows), encoding="utf-8")
    n_surv = sum(1 for _, st in rows if st == "survived")
    print(f"[mutmut_report] 写出 {args.out}（{len(rows)} 变异体 / {n_surv} 幸存）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
