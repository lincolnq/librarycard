#!/usr/bin/env python3
"""Run live contract tests for a rotating sample of sources and write a JSON report.

    python monitor/run_contracts.py --sample 6 --report reports/contracts.json
    python monitor/run_contracts.py --only census-acs5,fec-bulk   # explicit list
    python monitor/run_contracts.py --all

Selection when sampling (deterministic, so every source is covered every
ceil(N_sources / sample) days):
  * healthy + degraded sources with adapters, rotated by day number
  * plus quarantined sources whose backoff retry is due (days quarantined is
    1, 2, 4, 8, 16 or >= 30)
Also lists quarantined sources that have exceeded 30 days (policy: retire).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odc.catalog import Catalog  # noqa: E402
from odc.contracts import run_source  # noqa: E402

QUARANTINE_RETIRE_DAYS = 30
BACKOFF_DAYS = {1, 2, 4, 8, 16}


def quarantine_retry_due(days: int) -> bool:
    return days in BACKOFF_DAYS or days >= QUARANTINE_RETIRE_DAYS


def select(cat: Catalog, sample: int, today: dt.date) -> list[str]:
    active = sorted(sid for sid, e in cat.entries.items() if e["adapter"] and e["status"] in ("healthy", "degraded"))
    chosen: list[str] = []
    if active:
        n = min(sample, len(active))
        start = (today.toordinal() * n) % len(active)
        chosen = [active[(start + i) % len(active)] for i in range(n)]
    for sid, e in sorted(cat.entries.items()):
        if e["status"] == "quarantined" and e["adapter"]:
            days = (today - dt.date.fromisoformat(e["status_since"])).days
            if quarantine_retry_due(days):
                chosen.append(sid)
    return chosen


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=6)
    ap.add_argument("--only")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--report", default="reports/contracts.json")
    a = ap.parse_args(argv)
    cat = Catalog.load()
    today = dt.date.today()
    if a.only:
        ids = [s.strip() for s in a.only.split(",") if s.strip()]
    elif a.all:
        ids = sorted(sid for sid, e in cat.entries.items() if e["adapter"] and e["status"] != "retired")
    else:
        ids = select(cat, a.sample, today)
    per_source = []
    for sid in ids:
        e = cat.get(sid)
        results = run_source(e)
        per_source.append({
            "source_id": sid,
            "status": e["status"],
            "status_since": e["status_since"],
            "passed": all(r.passed for r in results),
            "cases": [r.as_dict() for r in results],
        })
        print(("PASS " if per_source[-1]["passed"] else "FAIL ") + sid)
        for r in results:
            if not r.passed:
                print(f"    {r.case}: [{r.kind}] {r.message[:300]}")
    overdue = []
    for sid, e in sorted(cat.entries.items()):
        if e["status"] == "quarantined":
            days = (today - dt.date.fromisoformat(e["status_since"])).days
            if days >= QUARANTINE_RETIRE_DAYS:
                overdue.append({"source_id": sid, "days_quarantined": days, "status_reason": e["status_reason"]})
    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "sources_tested": len(per_source),
        "sources_failed": sum(1 for p in per_source if not p["passed"]),
        "total_active_sources": sum(1 for e in cat.entries.values() if e["adapter"] and e["status"] in ("healthy", "degraded")),
        "results": per_source,
        "quarantine_overdue": overdue,
    }
    rp = Path(a.report)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, indent=2) + "\n")
    print(f"tested={report['sources_tested']} failed={report['sources_failed']} quarantine_overdue={len(overdue)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
