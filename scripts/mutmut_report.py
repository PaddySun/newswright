#!/usr/bin/env python3
"""mutmut HTML 报告生成器 / Mutation testing HTML report generator.

在 `mutmut run` 之后、`.mutmut-cache` 仍在场时执行（mutation workflow 内调用）：

    python scripts/mutmut_report.py --out mutmut-report.html \
        --results-file mutmut-results-full.txt --ref mutmut-baseline-2

设计要求（用户 2026-10-03 拍板）：
- 中英双语；主要指标直观展示（顶部指标卡 + 模块汇总表）；
- 细节默认收起（<details> 折叠），点击展开；
- 一键复制：纯文本结构块 / 「复制给 Agent」（自带分诊指令头，便于粘贴给执行 Agent）；
- 零第三方依赖（仅标准库），单文件 HTML。

本地开发可用 --skip-diffs 免除对 mutmut 缓存的依赖（只列清单不出 diff）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

RE_LINE = re.compile(r"^\s*(?P<name>\S+__mutmut_\d+)\s*:\s*(?P<status>.+?)\s*$")

STATUS_LABEL = {
    "survived": "幸存 Survived",
    "killed": "杀死 Killed",
    "no tests": "无测试 No tests",
    "timeout": "超时 Timeout",
    "suspicious": "可疑 Suspicious",
    "skipped": "跳过 Skipped",
    "not checked": "未检查 Not checked",
}
STATUS_CLASS = {
    "survived": "st-surv",
    "killed": "st-kill",
    "no tests": "st-note",
    "timeout": "st-warn",
    "suspicious": "st-warn",
    "skipped": "st-note",
    "not checked": "st-note",
}

AGENT_HEAD = (
    "你是 newswright 项目的测试补强 Agent。下面是一个存活的变异体（mutmut survivor）。请：\n"
    "1) 判断类别：(a) 等价变异——不改变可观察行为，标记豁免；\n"
    "              (b) 防御性分支——正常运行难以触达的防御代码，建议登记豁免清单；\n"
    "              (c) 真实测试缺口——需要补测试；\n"
    "2) 若为 (c)：写一个在该变异下会失败的 pytest 测试（风格与 tests/ 现有用例一致），"
    "并一行说明它验证了什么。\n"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="生成 mutmut 双语 HTML 报告")
    p.add_argument("--out", default="mutmut-report.html")
    p.add_argument("--results-file", default=None, help="mutmut results 的文本输出（缺省则现场执行 mutmut results）")
    p.add_argument("--ref", default="", help="触发本次运行的 ref/tag，仅作元信息展示")
    p.add_argument("--max-diffs", type=int, default=800, help="最多为多少个幸存者取 diff（超出只列清单）")
    p.add_argument("--skip-diffs", action="store_true", help="不调用 mutmut show（本地无缓存时用）")
    return p.parse_args()


def load_results(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.results_file and Path(args.results_file).exists():
        text = Path(args.results_file).read_text(encoding="utf-8")
    else:
        r = subprocess.run(["mutmut", "results"], capture_output=True, text=True, timeout=120)
        text = r.stdout + r.stderr
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        m = RE_LINE.match(line)
        if m:
            rows.append((m.group("name"), m.group("status")))
    return rows


def mutmut_show(name: str) -> str:
    try:
        r = subprocess.run(["mutmut", "show", name], capture_output=True, text=True, timeout=60)
        out = (r.stdout or r.stderr or "").strip()
        return out or "(mutmut show 无输出 no output)"
    except Exception as e:  # noqa: BLE001
        return f"(show 调用失败 call-failed: {e})"


def split_module(name: str) -> tuple[str, str]:
    """app.authors.pipeline.x_run__mutmut_3 -> (app.authors.pipeline, x_run__mutmut_3)"""
    head = name.split("__mutmut_")[0]
    if "." in head:
        mod, func = head.rsplit(".", 1)
        return mod, f"{func}__mutmut_{name.split('__mutmut_')[-1]}"
    return "(root)", name


def e(s: str) -> str:
    return html.escape(s, quote=True)


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
        f'<div class="card {cls}"><div class="num">{e(str(val))}</div>'
        f'<div class="lbl">{e(lbl)}</div></div>'
        for lbl, val, cls in cards
    )
    return f'<div class="cards">{cells}</div>'


def module_table(mod_stats: dict[str, dict]) -> str:
    rows = []
    for mod in sorted(mod_stats, key=lambda m: (-mod_stats[m]["survived"], m)):
        s = mod_stats[mod]
        checked = s["total"] - s["no tests"]
        rate = (s["killed"] / checked * 100) if checked else 0.0
        rows.append(
            f'<tr><td><a href="#mod-{e(mod)}">{e(mod)}</a></td>'
            f'<td class="n">{s["total"]}</td><td class="n k">{s["killed"]}</td>'
            f'<td class="n s">{s["survived"]}</td><td class="n">{s["no tests"]}</td>'
            f'<td class="rate"><div class="bar"><i style="width:{rate:.1f}%"></i></div>'
            f'<span>{rate:.1f}%</span></td></tr>'
        )
    return (
        '<table class="mods"><thead><tr><th>模块 Module</th><th>总数 Total</th>'
        "<th>杀死 K</th><th>幸存 S</th><th>无测试 N</th><th>杀死率 Kill Rate</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )


def item_block(module: str, fname: str, status: str, diff: str | None) -> str:
    plain = f"module: {module}\nmutant: {fname}\nstatus: {status}\n"
    if diff is not None:
        plain += f"diff:\n{diff}\n"
    agent = AGENT_HEAD + plain
    diff_html = f'<pre class="diff">{e(diff)}</pre>' if diff is not None else (
        '<p class="nodiff">（超出 --max-diffs 上限，未取 diff / diff not fetched）</p>')
    return (
        f'<details class="item"><summary><span class="badge {STATUS_CLASS.get(status, "st-note")}">'
        f'{e(STATUS_LABEL.get(status, status))}</span> <code>{e(fname)}</code></summary>'
        f'<div class="itembody"><p class="meta">module: <code>{e(module)}</code></p>'
        f"{diff_html}"
        f'<textarea class="payload" hidden>{e(plain)}</textarea>'
        f'<textarea class="payload-agent" hidden>{e(agent)}</textarea>'
        f'<div class="btns"><button onclick="cp(this,false)">📋 复制 Copy</button>'
        f'<button class="agentbtn" onclick="cp(this,true)">🤖 复制给 Agent Copy for Agent</button></div>'
        f"</div></details>"
    )


def render(rows: list[tuple[str, str]], args: argparse.Namespace, mutmut_ver: str) -> str:
    stats = defaultdict(int)
    for _, st in rows:
        stats[st] += 1
    stats["total"] = len(rows)

    by_mod: dict[str, list[tuple[str, str]]] = defaultdict(list)
    mod_stats: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for name, st in rows:
        mod, fname = split_module(name)
        by_mod[mod].append((fname, st))
        mod_stats[mod]["total"] += 1
        mod_stats[mod][st] += 1

    survivors_all = [(m, f, st) for m, items in by_mod.items() for f, st in items if st == "survived"]
    survivors_all.sort(key=lambda x: (x[0], x[1]))
    n_shown = 0 if args.skip_diffs else min(len(survivors_all), args.max_diffs)

    surv_sections = []
    for mod in sorted(by_mod):
        items = by_mod[mod]
        surv_items = [(f, st) for f, st in items if st == "survived"]
        if not surv_items:
            continue
        blocks = []
        for f, st in surv_items:
            diff = None
            if not args.skip_diffs and n_shown > 0:
                diff = mutmut_show(f"{mod}.{f}")
                n_shown -= 1
            blocks.append(item_block(mod, f, st, diff))
        surv_sections.append(
            f'<h3 id="mod-{e(mod)}">{e(mod)} '
            f'<small>({len(surv_items)} 幸存 survivors)</small></h3>' + "".join(blocks)
        )

    note_sections = []
    for mod in sorted(by_mod):
        notes = [(f, st) for f, st in by_mod[mod] if st == "no tests"]
        if not notes:
            continue
        blocks = "".join(
            f'<details class="item"><summary><span class="badge st-note">无测试 No tests</span> '
            f"<code>{e(f)}</code></summary>"
            f'<div class="itembody"><p class="meta">module: <code>{e(mod)}</code> — '
            f"stats 阶段未映射到任何测试用例 / no covering test mapped in stats phase</p>"
            f'<textarea class="payload" hidden>module: {mod}\nmutant: {f}\nstatus: no tests\n</textarea>'
            f'<div class="btns"><button onclick="cp(this,false)">📋 复制 Copy</button></div>'
            f"</div></details>"
            for f, _ in notes
        )
        note_sections.append(
            f'<h3 id="note-{e(mod)}">{e(mod)} <small>({len(notes)} 无测试 no-tests)</small></h3>' + blocks
        )

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    diff_note = (
        f"已为前 {min(len(survivors_all), args.max_diffs)} / {len(survivors_all)} 个幸存者取回 diff"
        if not args.skip_diffs else "（--skip-diffs 模式，未取 diff）"
    )
    meta = (
        f'生成 Generated: {e(now)} · ref: <code>{e(args.ref or "-")}</code> · '
        f"mutmut: <code>{e(mutmut_ver or '-')}</code> · {e(diff_note)}"
    )

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
 .meta {{ color:var(--note); font-size:12px; margin-bottom:16px; }}
 .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:12px 0 20px; }}
 .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:10px; padding:14px; text-align:center; }}
 .card .num {{ font-size:26px; font-weight:700; }} .card .lbl {{ font-size:12px; color:var(--note); margin-top:4px; }}
 .c-kill .num {{ color:var(--kill); }} .c-surv .num {{ color:var(--surv); }}
 .c-rate .num {{ color:#2563eb; }} .c-warn .num {{ color:var(--warn); }}
 .mods {{ border-collapse:collapse; width:100%; background:#fff; font-size:13px; margin-bottom:24px; }}
 .mods th,.mods td {{ border:1px solid #e5e7eb; padding:6px 10px; text-align:left; }}
 .mods th {{ background:#f1f5f9; }} .mods td.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
 td.k {{ color:var(--kill); }} td.s {{ color:var(--surv); font-weight:600; }}
 .rate {{ min-width:160px; }} .bar {{ background:#e5e7eb; height:8px; border-radius:4px; overflow:hidden; display:inline-block; width:100px; vertical-align:middle; }}
 .bar i {{ display:block; height:100%; background:var(--kill); }}
 h2 {{ font-size:17px; margin:28px 0 8px; }} h3 {{ font-size:14px; margin:18px 0 6px; color:#374151; }}
 h3 small {{ color:var(--note); font-weight:400; }}
 details.item {{ background:#fff; border:1px solid #e5e7eb; border-radius:8px; margin:4px 0; }}
 details.item summary {{ cursor:pointer; padding:6px 10px; font-size:13px; }}
 details.item[open] summary {{ border-bottom:1px solid #e5e7eb; }}
 .itembody {{ padding:8px 12px; }}
 .badge {{ display:inline-block; font-size:11px; border-radius:999px; padding:1px 8px; margin-right:6px; }}
 .st-kill {{ background:#dcfce7; color:var(--kill); }} .st-surv {{ background:#fee2e2; color:var(--surv); }}
 .st-note {{ background:#f3f4f6; color:var(--note); }} .st-warn {{ background:#fef3c7; color:var(--warn); }}
 pre.diff {{ background:#0f172a; color:#e2e8f0; padding:10px; border-radius:8px; font-size:12px; overflow:auto; max-height:340px; }}
 .nodiff {{ color:var(--note); font-size:12px; }}
 .btns {{ margin-top:6px; }} button {{ font-size:12px; padding:4px 10px; border-radius:6px; border:1px solid #d1d5db; background:#fff; cursor:pointer; }}
 button.agentbtn {{ border-color:#93c5fd; background:#eff6ff; }}
 button.ok {{ border-color:var(--kill); color:var(--kill); }}
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
<h2>幸存者清单 <small>Survivors（点击展开 · click to expand · 每条可一键复制）</small></h2>
<p class="hint">「🤖 复制给 Agent Copy for Agent」会把该变异体连同分诊指令（等价变异/防御分支/测试缺口三分类）一起放进剪贴板，直接粘贴给执行 Agent 即可。</p>
{''.join(surv_sections) or '<p class="hint">无幸存者 no survivors 🎉</p>'}
<h2>无测试覆盖清单 <small>No-Tests（stats 未映射到用例的变异体 = 覆盖缺口地图）</small></h2>
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
    rows = load_results(args)
    if not rows:
        print("[mutmut_report] 未解析到任何变异体行（results 为空或格式不符）", file=sys.stderr)
        return 1
    try:
        v = subprocess.run(["mutmut", "--version"], capture_output=True, text=True, timeout=30)
        mutmut_ver = (v.stdout or v.stderr).strip().splitlines()[-1] if (v.stdout or v.stderr).strip() else ""
    except Exception:  # noqa: BLE001
        mutmut_ver = ""
    out = render(rows, args, mutmut_ver)
    Path(args.out).write_text(out, encoding="utf-8")
    n_surv = sum(1 for _, st in rows if st == "survived")
    print(f"[mutmut_report] 写出 {args.out}（{len(rows)} 变异体 / {n_surv} 幸存）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
