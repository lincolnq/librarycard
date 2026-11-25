#!/usr/bin/env python3
"""End-to-end smoke test: launch `odc-server` over stdio and call every tool (LIVE network).

    python scripts/smoke_test_server.py [source_id ...]

Default sources: one per access method that is fetchable. For each: describe_source, then
fetch with the first contract case's filters. Also runs search_catalog and catalog_status,
and checks refusals for restricted sources. Exits non-zero on any failure.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from odc.adapters import adapter_for  # noqa: E402
from odc.catalog import Catalog  # noqa: E402


def pick_default(cat: Catalog) -> list[str]:
    chosen, seen = [], set()
    for sid, e in sorted(cat.entries.items()):
        m = e["access"]["method"]
        if e["adapter"] and e["status"] == "healthy" and m not in seen:
            chosen.append(sid)
            seen.add(m)
    return chosen


async def main(ids: list[str]) -> int:
    cat = Catalog.load()
    ids = ids or pick_default(cat)
    exe = shutil.which("odc-server") or str(Path(sys.executable).parent / "odc-server")
    failures = 0

    def check(cond: bool, label: str, detail: str = "") -> None:
        nonlocal failures
        print(("  ok   " if cond else "  FAIL ") + label + (f" — {detail}" if detail and not cond else ""))
        failures += 0 if cond else 1

    async with Client(StdioServerParameters(command=exe, args=[], env=dict(os.environ)), read_timeout_seconds=300) as c:
        tools = sorted(t.name for t in (await c.list_tools()).tools)
        print("tools:", tools)
        check(tools == ["catalog_status", "describe_source", "fetch", "request_data", "search_catalog"], "five tools exposed")

        r = (await c.call_tool("catalog_status", {})).structured_content
        print("catalog_status:", json.dumps(r["counts_by_status"]), "fetchable:", r["fetchable"])
        check(r["total_sources"] == len(cat.entries), "catalog_status counts all entries")

        for q, kw in [("county election results", {}), ("unemployment rate county", {"domain": "labor"}),
                      ("median household income", {"geography": "tract"}), ("poverty", {"time_range": "2015-2020"})]:
            r = (await c.call_tool("search_catalog", {"query": q, **kw})).structured_content
            top = [x["id"] for x in r.get("results", [])][:3]
            print(f"search_catalog({q!r}, {kw}) -> {top}")
            check(bool(top) or "error" not in r, f"search '{q}' returns without error")

        for sid in ids:
            print(f"\n== {sid}")
            d = (await c.call_tool("describe_source", {"source_id": sid})).structured_content
            check("error" not in d and d.get("caveats"), f"describe_source({sid}) has caveats")
            case = adapter_for(cat.get(sid)).contract[0]
            r = (await c.call_tool("fetch", {"source_id": sid, "filters": case.filters, "limit": 5})).structured_content
            ok = "error" not in r and r.get("row_count", 0) > 0
            check(ok, f"fetch({sid}, {case.filters}) returns rows", r.get("error", ""))
            if ok:
                p = r["provenance"]
                check(all(k in p for k in ("publisher", "retrieved_at", "request_urls", "license", "citation")), "provenance complete")
                print("   first row:", json.dumps(r["rows"][0], default=str)[:200])
                print("   citation:", p["citation"][:200])

        for sid, e in sorted(cat.entries.items()):
            if e["access"]["method"] == "restricted":
                r = (await c.call_tool("fetch", {"source_id": sid})).structured_content
                check("error" in r, f"fetch refuses restricted {sid}")
                break
        r = (await c.call_tool("fetch", {"source_id": ids[0], "filters": {"bogus": 1}})).structured_content
        check("error" in r and "fetch_parameters" in r, "bad filters -> error with fetch_parameters")

    print(f"\n{'PASS' if not failures else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(anyio.run(main, sys.argv[1:]))
