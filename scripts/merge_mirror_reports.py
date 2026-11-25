"""Merge per-source mirror reports from the mirror.yml matrix into one report for monitor/file_issues.py.

A source that was planned but left no report (job timed out or crashed before writing it) is recorded as failed,
so it still becomes a needs-repair issue.

Usage: python scripts/merge_mirror_reports.py PLAN.json REPORTS_DIR OUT.json
"""
import json
import sys
from pathlib import Path


def merge(plan: dict, reports: list[dict]) -> dict:
    out = {"published": [], "skipped": list(plan.get("skipped", [])), "failed": list(plan.get("failed", []))}
    seen = set()
    for r in reports:
        for k in ("published", "skipped", "failed"):
            out[k] += r.get(k, [])
            seen |= {x["source_id"] for x in r.get(k, [])}
    for sid in plan.get("due", []):
        if sid not in seen:
            out["failed"].append({"source_id": sid, "kind": "timeout",
                                  "error": "mirror job ended without a report (timed out or crashed); see the "
                                           f"mirror.yml run log for job 'build ({sid})'."})
    return out


def main(argv: list[str]) -> int:
    plan = json.loads(Path(argv[0]).read_text())
    reports = [json.loads(p.read_text()) for p in sorted(Path(argv[1]).rglob("*.json"))
               if p.stat().st_size and p.name != "reports-plan.json"]
    Path(argv[2]).parent.mkdir(parents=True, exist_ok=True)
    Path(argv[2]).write_text(json.dumps(merge(plan, reports), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
