"""搜索双家连通实测 + 归一化一致性比对（能力④，V10①②）。

用法：.venv/Scripts/python scripts/test_search_providers.py [--keyword "词"]
输出：每家鉴权/延迟/字段完整度；同词双家结果比对；原始明细写 verify/V10_search_providers.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from app.db import SessionLocal, init_db
    from app.models import SearchCallLog
    from app.search import registry

    init_db()
    keyword = "AI Agent 工程实践"
    if "--keyword" in sys.argv:
        keyword = sys.argv[sys.argv.index("--keyword") + 1]

    report: dict = {"keyword": keyword, "providers": {}, "comparison": {}}
    results_by_provider: dict[str, list] = {}

    with SessionLocal() as db:
        for name in ("bocha", "tencent"):
            entry: dict = {}
            try:
                provider = registry.get_provider(name)
                t0 = time.monotonic()
                results = provider.search(keyword, count=10)
                dt = int((time.monotonic() - t0) * 1000)
                entry["ok"] = True
                entry["latency_ms"] = dt
                entry["results"] = len(results)
                fields = {"title": 0, "url": 0, "snippet": 0, "content": 0, "published_at": 0}
                for r in results:
                    for f in fields:
                        if getattr(r, f):
                            fields[f] += 1
                entry["field_coverage"] = fields
                entry["sample"] = [
                    {"title": r.title[:60], "url": r.url[:100],
                     "snippet": r.snippet[:80], "date": str(r.published_at)}
                    for r in results[:3]
                ]
                results_by_provider[name] = results
                db.add(SearchCallLog(provider=name, query=keyword, keyword_group="connectivity-test",
                                     result_count=len(results), latency_ms=dt, ok=True, status="ok"))
                db.commit()
            except Exception as e:  # noqa: BLE001  连通失败如实记录
                entry["ok"] = False
                entry["error"] = f"{type(e).__name__}: {e}"
                db.add(SearchCallLog(provider=name, query=keyword, keyword_group="connectivity-test",
                                     result_count=0, latency_ms=0, ok=False, status="error",
                                     error=f"{type(e).__name__}: {e}"[:500]))
                db.commit()
            report["providers"][name] = entry

    # 归一化一致性：URL 域名重合度 + 字段完整度差异
    b = results_by_provider.get("bocha") or []
    t = results_by_provider.get("tencent") or []

    def domains(rs):
        from urllib.parse import urlparse
        return {urlparse(r.url).netloc for r in rs if r.url}

    if b or t:
        bd, td = domains(b), domains(t)
        report["comparison"] = {
            "bocha_domains": len(bd), "tencent_domains": len(td),
            "domain_overlap": len(bd & td),
            "url_overlap_exact": len({r.url for r in b} & {r.url for r in t}),
            "field_diff_note": (
                "bocha: content=summary 字段（summary=true 时有）；"
                "tencent(lite): content 为空、passage 作 snippet、score 0-1 在 raw"
            ),
        }

    out = PROJECT_ROOT / "verify" / "V10_search_providers.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str)[:3000])
    print(f"\n明细已写 {out}")
    return 0 if all(p.get("ok") for p in report["providers"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
