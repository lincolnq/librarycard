"""Command-line helpers for maintainers (humans and agents).

    odc validate                     # schema + consistency checks for every catalog entry
    odc search "county election results" [--domain elections]
    odc describe census-acs5
    odc fetch census-acs5 '{"variables": ["B01003_001E"], "geography": "state"}' --limit 5
    odc contract census-acs5 [more ids...]   # run live contract tests, print results
    odc status
"""

from __future__ import annotations

import argparse
import json
import sys

from . import server
from .catalog import Catalog, CatalogError
from .contracts import run_many
from .consistency import consistency_problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="odc")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--domain")
    s.add_argument("--geography")
    s.add_argument("--time-range")
    d = sub.add_parser("describe")
    d.add_argument("source_id")
    f = sub.add_parser("fetch")
    f.add_argument("source_id")
    f.add_argument("filters", nargs="?", default="{}")
    f.add_argument("--limit", type=int, default=10)
    c = sub.add_parser("contract")
    c.add_argument("source_ids", nargs="+")
    sub.add_parser("status")
    m = sub.add_parser("mirror", help="ingest allowed sources into R2 (see docs/MIRROR.md)")
    m.add_argument("source_ids", nargs="*", help="default: every mirrorable source")
    m.add_argument("--due", action="store_true", help="only sources whose upstream changed / never mirrored / stale")
    m.add_argument("--dry-run", action="store_true", help="build packs locally, do not upload")
    m.add_argument("--out", help="keep packs in this directory (default: temp, deleted)")
    m.add_argument("--report", help="write a JSON report of published/skipped/failed sources")
    m.add_argument("--resume", action="store_true",
                   help="with --out: continue an interrupted ingest from its checkpoint (or publish a finished one)")
    e = sub.add_parser("export", help="write the catalog JSON bundled into the Worker")
    e.add_argument("--out", default="worker/src/generated/catalog.json")
    a = ap.parse_args(argv)

    if a.cmd == "validate":
        try:
            cat = Catalog.load()
        except CatalogError as e:
            print(e)
            return 1
        problems = consistency_problems(cat)
        for p in problems:
            print(p)
        print(f"{len(cat.entries)} entries; {len(problems)} consistency problems")
        return 1 if problems else 0
    if a.cmd == "mirror":
        from pathlib import Path

        from .mirror import run
        return run(a.source_ids or None, a.due, a.dry_run, Path(a.out) if a.out else None,
                   report_path=Path(a.report) if a.report else None, resume=a.resume)
    if a.cmd == "export":
        from pathlib import Path

        from .export import export_catalog
        n = export_catalog(Path(a.out))
        print(f"wrote {a.out} ({n} entries)")
        return 0
    if a.cmd == "search":
        out = server.search_catalog(a.query, a.domain, a.geography, a.time_range)
    elif a.cmd == "describe":
        out = server.describe_source(a.source_id)
    elif a.cmd == "fetch":
        out = server.fetch(a.source_id, json.loads(a.filters), a.limit)
    elif a.cmd == "status":
        out = server.catalog_status_tool()
    elif a.cmd == "contract":
        results = run_many(Catalog.load(), a.source_ids)
        for r in results:
            mark = "PASS" if r.passed else f"FAIL[{r.kind}]"
            print(f"{mark:14} {r.source_id}::{r.case} ({r.rows} rows, {r.seconds}s) {'' if r.passed else r.message}")
        return 0 if all(r.passed for r in results) else 1
    print(json.dumps(out, indent=2, default=str))
    return 1 if isinstance(out, dict) and "error" in out else 0


if __name__ == "__main__":
    sys.exit(main())
