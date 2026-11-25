#!/usr/bin/env python3
"""Usage and estimated cost for the weekly maintainer digest (docs/MAINTAINER.md).

    python scripts/usage_report.py [--days 7] [--json]

Reads Cloudflare's R2 usage API and Workers analytics (GraphQL) for the librarycard bucket and Worker. Needs
CLOUDFLARE_ACCOUNT_ID, and CLOUDFLARE_API_TOKEN unless a proxy injects it; the token needs Account Analytics:Read
and R2 read. Prices are list prices as of 2026-11 and are estimates; check the Cloudflare dashboard for billing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import httpx

API = "https://api.cloudflare.com/client/v4"
BUCKET = os.environ.get("ODC_R2_BUCKET", "librarycard-data")
WORKER = "librarycard-mcp"
# Escalation thresholds (keep in sync with docs/POLICY.md §Escalation and docs/MAINTAINER.md).
THRESHOLDS = {"r2_gb": 50, "requests_per_day": 1_000_000, "error_rate": 0.05}


def client() -> httpx.Client:
    h = {"content-type": "application/json"}
    if os.environ.get("CLOUDFLARE_API_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}"
    return httpx.Client(headers=h, timeout=60)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not acct:
        print("CLOUDFLARE_ACCOUNT_ID not set", file=sys.stderr)
        return 2
    c = client()
    out: dict = {"as_of": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "warnings": []}
    try:
        u = c.get(f"{API}/accounts/{acct}/r2/buckets/{BUCKET}/usage").json()["result"]
        gb = int(u["payloadSize"]) / 1e9
        out["r2"] = {"bucket": BUCKET, "gb": round(gb, 2), "objects": int(u["objectCount"]),
                     "est_monthly_usd": round(max(0.0, gb - 10) * 0.015, 2)}
        if gb > THRESHOLDS["r2_gb"]:
            out["warnings"].append(f"R2 storage {gb:.1f} GB exceeds {THRESHOLDS['r2_gb']} GB threshold")
    except Exception as e:  # noqa: BLE001
        out["warnings"].append(f"R2 usage unavailable: {e}")
    since = (dt.date.today() - dt.timedelta(days=a.days)).isoformat()
    q = ('{ viewer { accounts(filter:{accountTag:"%s"}) { workersInvocationsAdaptive(limit:100, '
         'filter:{scriptName:"%s", date_geq:"%s"}) { sum { requests errors } dimensions { date } } } } }') % (acct, WORKER, since)
    try:
        d = c.post(f"{API}/graphql", json={"query": q}).json()
        rows = d["data"]["viewer"]["accounts"][0]["workersInvocationsAdaptive"]
        days = sorted(({"date": r["dimensions"]["date"], **r["sum"]} for r in rows), key=lambda r: r["date"])
        total = sum(r["requests"] for r in days)
        errors = sum(r["errors"] for r in days)
        peak = max((r["requests"] for r in days), default=0)
        out["worker"] = {"script": WORKER, "days": days, "requests": total, "errors": errors,
                         "error_rate": round(errors / total, 4) if total else 0.0, "peak_day_requests": peak,
                         "est_monthly_usd": round(5 + max(0.0, total * 30 / max(a.days, 1) - 10_000_000) / 1e6 * 0.30, 2)}
        if peak > THRESHOLDS["requests_per_day"]:
            out["warnings"].append(f"peak {peak} requests/day exceeds threshold")
        if total and errors / total > THRESHOLDS["error_rate"]:
            out["warnings"].append(f"Worker error rate {errors / total:.1%} exceeds {THRESHOLDS['error_rate']:.0%}")
    except Exception as e:  # noqa: BLE001
        out["warnings"].append(f"Worker analytics unavailable: {e}")
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        r2, w = out.get("r2", {}), out.get("worker", {})
        print(f"R2 {r2.get('bucket')}: {r2.get('gb')} GB, {r2.get('objects')} objects, ~${r2.get('est_monthly_usd')}/mo")
        print(f"Worker {WORKER}: {w.get('requests')} requests / {a.days}d (peak {w.get('peak_day_requests')}/day), "
              f"error rate {w.get('error_rate')}, ~${w.get('est_monthly_usd')}/mo incl. $5 Workers Paid")
        for x in out["warnings"]:
            print("WARNING:", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
