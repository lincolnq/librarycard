#!/usr/bin/env python3
"""Detect upstream changes for every catalog source that is due for polling.

No LLM involved. Reads each entry's ``change_detection`` block, computes a
fingerprint, compares it with the stored state, and writes a JSON report.

    python monitor/detect_changes.py --state STATE.json --report reports/changes.json [--all] [--only id1,id2]

Methods (catalog field ``change_detection.method``):
  http_headers  fingerprint = selected response headers (default ETag + Last-Modified)
  content_hash  fingerprint = sha256 of the response body
  json_field    fingerprint = value at ``json_path`` in the JSON response
  regex         fingerprint = all matches of ``pattern`` in the response body
  none          never polled (restricted / catalog-only entries)

State file (JSON): {source_id: {fingerprint, detail, last_checked, last_changed,
consecutive_errors, last_error}}. First observation records a baseline and is
NOT reported as a change. Errors are only reported as ``unreachable`` after
UNREACHABLE_AFTER consecutive failures, so one flaky poll doesn't open an issue.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odc import http  # noqa: E402
from odc.catalog import Catalog  # noqa: E402
from odc.http import SourceError  # noqa: E402,F401
from odc.changes import extract_json_path, fingerprint  # noqa: E402,F401

UNREACHABLE_AFTER = 2


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def is_due(entry: dict, st: dict | None, t: dt.datetime) -> bool:
    if not st or not st.get("last_checked"):
        return True
    last = dt.datetime.fromisoformat(st["last_checked"])
    interval = dt.timedelta(days=entry["change_detection"]["poll_interval_days"]) - dt.timedelta(hours=2)
    if st.get("consecutive_errors"):
        interval = dt.timedelta(hours=20)  # re-check failing sources daily
    return t - last >= interval


def run(cat: Catalog, state: dict, force_all: bool = False, only: set[str] | None = None) -> dict:
    t = now()
    report = {"generated_at": t.isoformat(), "checked": [], "changed": [], "unreachable": [], "errors_below_threshold": [], "not_due": [], "skipped": []}
    for sid, e in sorted(cat.entries.items()):
        if only and sid not in only:
            continue
        cd = e["change_detection"]
        if cd["method"] == "none" or e["status"] == "retired":
            report["skipped"].append(sid)
            continue
        st = state.get(sid, {})
        if not force_all and not is_due(e, st, t):
            report["not_due"].append(sid)
            continue
        report["checked"].append(sid)
        try:
            fp, detail = fingerprint(cd)
        except Exception as ex:  # noqa: BLE001
            kind = getattr(ex, "kind", "error")
            st["consecutive_errors"] = st.get("consecutive_errors", 0) + 1
            st["last_error"] = f"[{kind}] {ex}"[:2000]
            st["last_checked"] = t.isoformat()
            state[sid] = st
            item = {"source_id": sid, "kind": kind, "error": st["last_error"], "url": cd.get("url"),
                    "method": cd["method"], "consecutive_errors": st["consecutive_errors"]}
            (report["unreachable"] if st["consecutive_errors"] >= UNREACHABLE_AFTER else report["errors_below_threshold"]).append(item)
            continue
        prev = st.get("fingerprint")
        if prev is not None and prev != fp:
            report["changed"].append({
                "source_id": sid, "method": cd["method"], "url": cd["url"],
                "previous_fingerprint": prev, "previous_detail": st.get("detail"),
                "new_fingerprint": fp, "new_detail": detail,
                "previous_checked": st.get("last_checked"),
            })
            st["last_changed"] = t.isoformat()
        st.update({"fingerprint": fp, "detail": detail, "last_checked": t.isoformat(), "consecutive_errors": 0})
        st.pop("last_error", None)
        if prev is None:
            st["baseline_at"] = t.isoformat()
        state[sid] = st
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="monitor-state/state.json")
    ap.add_argument("--report", default="reports/changes.json")
    ap.add_argument("--all", action="store_true", help="ignore poll intervals")
    ap.add_argument("--only", help="comma-separated source ids")
    a = ap.parse_args(argv)
    sp = Path(a.state)
    state = json.loads(sp.read_text()) if sp.exists() and sp.read_text().strip() else {}
    cat = Catalog.load()
    report = run(cat, state, a.all, set(a.only.split(",")) if a.only else None)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    rp = Path(a.report)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, indent=2) + "\n")
    print(f"checked={len(report['checked'])} changed={len(report['changed'])} "
          f"unreachable={len(report['unreachable'])} transient_errors={len(report['errors_below_threshold'])} "
          f"not_due={len(report['not_due'])}")
    for c in report["changed"]:
        print(f"  CHANGED {c['source_id']}: {c['previous_detail']} -> {c['new_detail']}")
    for u in report["unreachable"] + report["errors_below_threshold"]:
        print(f"  ERROR   {u['source_id']} (x{u['consecutive_errors']}): {u['error'][:200]}")
    return 0  # problems are surfaced via issues, not the exit code


if __name__ == "__main__":
    sys.exit(main())
