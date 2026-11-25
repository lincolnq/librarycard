#!/usr/bin/env python3
"""Turn monitor reports into GitHub issues (the handoff to repair/update agents).

    python monitor/file_issues.py --changes reports/changes.json --contracts reports/contracts.json [--dry-run]

Env: GITHUB_TOKEN, GITHUB_REPOSITORY (owner/repo) — both set automatically in Actions.

Rules (see docs/POLICY.md and docs/RUNBOOKS.md):
* One OPEN issue per (source, label). Titles start with "[<source_id>]"; that
  prefix plus the label is the dedup key. Existing issue -> add a comment,
  but only if the fingerprint of the new information differs from the last
  one posted (hidden ``<!-- odc-fp:... -->`` marker), so daily runs don't spam.
* Labels: source-changed, needs-repair, needs-human.
* If many sources fail at once (>= SYSTEMIC_MIN sources AND >= SYSTEMIC_FRACTION
  of those checked), that is probably our bug or the CI network, not N
  publisher changes: open ONE needs-human issue and skip per-source repair issues.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odc.catalog import Catalog  # noqa: E402

SYSTEMIC_MIN = 4
SYSTEMIC_FRACTION = 0.4
LABELS = {
    "source-changed": ("1d76db", "Monitor detected an upstream change; an agent should review and update the entry/adapter."),
    "needs-repair": ("d93f0b", "Contract tests failing or source unreachable; an agent should repair or change status."),
    "needs-human": ("b60205", "Escalation: systemic failure, spend anomaly, or policy question. Humans only."),
}
MAX_OUTPUT = 6000


# ------------------------------------------------------------------ GitHub

class GitHub:
    def __init__(self, repo: str, token: str):
        self.repo, self.token = repo, token

    def _req(self, method: str, path: str, body: dict | None = None):
        url = f"https://api.github.com/repos/{self.repo}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "open-data-catalog-monitor",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read().decode()
                return json.loads(txt) if txt else None
        except urllib.error.HTTPError as e:
            if e.code == 422 and path == "/labels":
                return None  # label exists
            raise RuntimeError(f"GitHub {method} {path} -> {e.code}: {e.read().decode()[:500]}") from e

    def ensure_labels(self):
        for name, (color, desc) in LABELS.items():
            self._req("POST", "/labels", {"name": name, "color": color, "description": desc})

    def open_issues(self, label: str) -> list[dict]:
        out, page = [], 1
        while True:
            batch = self._req("GET", f"/issues?state=open&labels={label}&per_page=100&page={page}") or []
            out += [i for i in batch if "pull_request" not in i]
            if len(batch) < 100:
                return out
            page += 1

    def comments(self, number: int) -> list[dict]:
        return self._req("GET", f"/issues/{number}/comments?per_page=100") or []

    def create(self, title: str, body: str, labels: list[str]) -> dict:
        return self._req("POST", "/issues", {"title": title, "body": body, "labels": labels})

    def comment(self, number: int, body: str) -> dict:
        return self._req("POST", f"/issues/{number}/comments", {"body": body})


class DryRun:
    """Records actions instead of calling GitHub. Also used by tests."""

    def __init__(self, existing: dict[str, list[dict]] | None = None):
        self.existing = existing or {}
        self.actions: list[dict] = []

    def ensure_labels(self):
        pass

    def open_issues(self, label):
        return self.existing.get(label, [])

    def comments(self, number):
        return []

    def create(self, title, body, labels):
        self.actions.append({"action": "create", "title": title, "labels": labels, "body": body})
        return {"number": -1}

    def comment(self, number, body):
        self.actions.append({"action": "comment", "number": number, "body": body})
        return {}


# ------------------------------------------------------------------ helpers

def fp(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def marker(source_id: str, label: str, f: str) -> str:
    return f"<!-- odc:source={source_id} label={label} -->\n<!-- odc-fp:{f} -->"


def last_fp(gh, issue: dict) -> str | None:
    texts = [issue.get("body") or ""] + [c.get("body") or "" for c in gh.comments(issue["number"])]
    found = None
    for t in texts:
        m = re.findall(r"<!-- odc-fp:([0-9a-f]+) -->", t)
        if m:
            found = m[-1]
    return found


def upsert(gh, label: str, source_id: str, title: str, body: str, comment_body: str, f: str, index: dict) -> str:
    existing = index.get((label, source_id))
    if existing:
        if last_fp(gh, existing) == f:
            return f"unchanged #{existing['number']}"
        gh.comment(existing["number"], comment_body + "\n\n" + marker(source_id, label, f))
        return f"commented #{existing['number']}"
    gh.create(title, body + "\n\n" + marker(source_id, label, f), [label])
    return "created"


def index_issues(gh) -> dict:
    idx = {}
    for label in LABELS:
        for i in gh.open_issues(label):
            m = re.match(r"^\[([a-z0-9-]+)\]", i["title"])
            if m:
                idx[(label, m.group(1))] = i
            elif i["title"].startswith("[systemic]"):
                idx[(label, "systemic")] = i
    return idx


def entry_context(e: dict | None, source_id: str) -> str:
    if not e:
        return f"- Catalog entry: `catalog/{source_id}.yaml` (not found in catalog at time of report)\n"
    return (
        f"- Catalog entry: `catalog/{source_id}.yaml` — status **{e['status']}** since {e['status_since']} "
        f"({e['status_reason']}); last_verified {e['last_verified']}\n"
        f"- Adapter: `src/odc/adapters/{e['adapter']}.py` (version {e['adapter_version']})\n"
        f"- License: {e['license']['name']} — redistribution `{e['license']['redistribution']}`; evidence `{e['license']['evidence']}` (checked {e['license']['checked_at']})\n"
        f"- Publisher homepage: {e['homepage']}\n"
    )


def trunc(s: str) -> str:
    return s if len(s) <= MAX_OUTPUT else s[:MAX_OUTPUT] + f"\n... [truncated {len(s) - MAX_OUTPUT} chars]"


# ------------------------------------------------------------------ bodies

def changed_body(c: dict, e: dict | None) -> tuple[str, str]:
    sid = c["source_id"]
    details = (
        f"| | |\n|---|---|\n| Detection method | `{c['method']}` |\n| URL polled | {c['url']} |\n"
        f"| Previous | `{c.get('previous_detail')}` (checked {c.get('previous_checked')}) |\n"
        f"| Now | `{c['new_detail']}` |\n"
    )
    body = f"""## Upstream change detected: `{sid}`

The monitor (no LLM) saw the publisher's change signal move. This may be a routine data release, a
methodology/schema change, a moved endpoint, or a license change. Nothing has been modified yet.

{details}
### Context
{entry_context(e, sid)}
### What to do — follow `docs/RUNBOOKS.md#source-changed`
1. Look at what changed at the URL above (release notes, new vintage/year, new columns, moved files).
2. **Re-check the license** (docs/POLICY.md#licensing): re-read the terms page, save a new dated snapshot in
   `evidence/licenses/{sid}/`, update `license.checked_at` (and classification if it changed).
3. Run `odc contract {sid}`. If it fails, repair the adapter (bump `adapter_version` in both places).
4. Update coverage (`time_range.end`), `key_variables`, and `caveats` if the release changed them.
5. Set `last_verified` to today. Open a PR that references this issue ("Fixes #N").
6. If nothing material changed (e.g. a header-only touch), say so in a comment and close the issue.

### Reproduce
```bash
odc contract {sid}
python monitor/detect_changes.py --only {sid} --all --state /tmp/odc-state.json --report /tmp/changes.json
```"""
    comment = f"Another change signal for `{sid}`:\n\n{details}"
    return body, comment


def repair_body(sid: str, e: dict | None, contract: dict | None, unreachable: dict | None) -> tuple[str, str]:
    parts = []
    kinds = set()
    if contract:
        for case in contract["cases"]:
            if not case["passed"]:
                kinds.add(case["kind"])
                parts.append(f"#### Contract case `{case['case']}` — failure kind `{case['kind']}` ({case['seconds']}s, {case['rows']} rows)\n```\n{trunc(case['message'])}\n```")
    if unreachable:
        kinds.add(unreachable["kind"])
        parts.append(f"#### Change-detection poll failed {unreachable['consecutive_errors']}x in a row — kind `{unreachable['kind']}`\n"
                     f"URL: {unreachable['url']} (method `{unreachable['method']}`)\n```\n{trunc(unreachable['error'])}\n```")
    failure = "\n\n".join(parts)
    hint = ""
    if "network" in kinds:
        hint = ("\n> Failure kind `network`: first check whether the host is blocked by the environment's network "
                "allowlist (see `ops/network-allowlist.txt` and docs/POLICY.md#network-access). Do not work around a block.\n")
    body = f"""## Source needs repair: `{sid}`
{hint}
### Failure output
{failure}

### Context
{entry_context(e, sid)}
### What to do — follow `docs/RUNBOOKS.md#needs-repair`
1. Reproduce: `odc contract {sid}`.
2. Diagnose using the failure kind (`docs/RUNBOOKS.md` has a table: network/http/parse/empty/schema/value/filter/error).
3. Make **one** repair attempt: fix the adapter and/or catalog entry, bump `adapter_version` (catalog + adapter), run
   `pytest -m "not live"` and `odc contract {sid}`, open a PR referencing this issue.
4. If it can't be fixed in one attempt, set `status` to `degraded` (partially usable) or `quarantined`, with
   `status_reason` and `status_since`, in a PR referencing this issue. Never leave a broken source `healthy`.
"""
    return body, f"Still failing (new output):\n\n{failure}"


def systemic_body(failing: list[str], checked: int) -> str:
    return f"""## Systemic failure: {len(failing)} of {checked} checked sources failing at once

This many simultaneous failures usually means a bug in shared code (`src/odc/http.py`,
`src/odc/adapters/_common.py`), a dependency upgrade, or the CI runner's network — not
{len(failing)} independent publisher changes. Per docs/POLICY.md#escalation this is escalated to a human,
and per-source `needs-repair` issues were NOT opened for this run.

Failing: {', '.join(f'`{s}`' for s in sorted(failing))}

See the monitor run's artifacts (reports/changes.json, reports/contracts.json) for full output.
"""


# ------------------------------------------------------------------ main logic

def plan_and_file(gh, cat: Catalog | None, changes: dict, contracts: dict) -> list[str]:
    entries = cat.entries if cat else {}
    idx = index_issues(gh)
    log: list[str] = []

    contract_fail = {r["source_id"]: r for r in contracts.get("results", []) if not r["passed"]}
    unreachable = {u["source_id"]: u for u in changes.get("unreachable", [])}
    failing = sorted(set(contract_fail) | set(unreachable))
    checked = len(set(changes.get("checked", [])) | {r["source_id"] for r in contracts.get("results", [])})

    systemic = len(failing) >= SYSTEMIC_MIN and checked and len(failing) / checked >= SYSTEMIC_FRACTION
    if systemic:
        f = fp(sorted(failing))
        body = systemic_body(failing, checked)
        log.append("systemic: " + upsert(gh, "needs-human", "systemic", f"[systemic] {len(failing)} sources failing at once",
                                          body, body, f, idx))
    else:
        for sid in failing:
            c, u = contract_fail.get(sid), unreachable.get(sid)
            body, comment = repair_body(sid, entries.get(sid), c, u)
            f = fp({"c": [(x["case"], x["kind"], x["message"][:500]) for x in (c or {}).get("cases", []) if not x["passed"]],
                    "u": (u or {}).get("kind")})
            kinds = sorted({x["kind"] for x in (c or {}).get("cases", []) if not x["passed"]} | ({u["kind"]} if u else set()))
            title = f"[{sid}] needs repair: {', '.join(kinds)} failure"
            log.append(f"needs-repair {sid}: " + upsert(gh, "needs-repair", sid, title, body, comment, f, idx))

    for c in changes.get("changed", []):
        sid = c["source_id"]
        body, comment = changed_body(c, entries.get(sid))
        log.append(f"source-changed {sid}: " + upsert(gh, "source-changed", sid, f"[{sid}] source changed ({c['method']})",
                                                     body, comment, c["new_fingerprint"], idx))

    # Quarantine lifecycle: passing quarantined sources and overdue ones need an agent.
    for r in contracts.get("results", []):
        if r["passed"] and r["status"] == "quarantined":
            sid = r["source_id"]
            body = (f"## Quarantined source `{sid}` is passing contract tests again\n\n{entry_context(entries.get(sid), sid)}\n"
                    f"Per docs/RUNBOOKS.md#needs-repair: verify with `odc contract {sid}`, then set status back to `healthy` "
                    f"(update `status_since`, `status_reason`, `last_verified`) in a PR referencing this issue.")
            log.append(f"needs-repair {sid} (recovered): " + upsert(gh, "needs-repair", sid, f"[{sid}] quarantined source recovered",
                                                                   body, body, fp(["recovered", sid]), idx))
    for o in contracts.get("quarantine_overdue", []):
        sid = o["source_id"]
        body = (f"## `{sid}` has been quarantined for {o['days_quarantined']} days\n\n{entry_context(entries.get(sid), sid)}\n"
                f"Per docs/POLICY.md#status-transitions, a source quarantined for 30 days with no fix is retired. Either fix it now "
                f"(one attempt), or set `status: retired` with a `status_reason` explaining why, keep the catalog file "
                f"(ids are never reused), and open a PR referencing this issue.")
        log.append(f"needs-repair {sid} (retire?): " + upsert(gh, "needs-repair", sid, f"[{sid}] quarantined 30+ days: fix or retire",
                                                             body, body, fp(["overdue", sid]), idx))
    return log


def merge_mirror_failures(contracts: dict, mirror_report: dict) -> dict:
    """Treat a failed mirror ingest like a failed contract case, so it flows through the same
    needs-repair dedup/systemic logic. The case name 'mirror_ingest' tells the agent which runbook step applies."""
    if not mirror_report.get("failed"):
        return contracts
    out = {**contracts, "results": list(contracts.get("results", []))}
    for f in mirror_report["failed"]:
        case = {"case": "mirror_ingest", "passed": False, "kind": f.get("kind", "error"),
                "message": "odc mirror failed (docs/MIRROR.md; reproduce with `odc mirror " + f["source_id"] +
                           " --dry-run --out /tmp/p`):\n" + f["error"], "seconds": 0, "rows": 0}
        existing = next((r for r in out["results"] if r["source_id"] == f["source_id"]), None)
        if existing:
            existing["passed"] = False
            existing["cases"] = existing["cases"] + [case]
        else:
            out["results"].append({"source_id": f["source_id"], "status": "healthy", "status_since": "", "passed": False, "cases": [case]})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changes", default="reports/changes.json")
    ap.add_argument("--contracts", default="reports/contracts.json")
    ap.add_argument("--mirror", default="reports/mirror.json", help="report from `odc mirror --report`")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    load = lambda p: json.loads(Path(p).read_text() or "{}") if Path(p).exists() else {}  # noqa: E731
    changes, contracts = load(a.changes), load(a.contracts)
    contracts = merge_mirror_failures(contracts, load(a.mirror))
    cat = Catalog.load()
    if a.dry_run or not os.environ.get("GITHUB_TOKEN"):
        gh = DryRun()
        log = plan_and_file(gh, cat, changes, contracts)
        print("DRY RUN (no GITHUB_TOKEN or --dry-run). Planned actions:")
        for act in gh.actions:
            print(f"  {act['action']}: {act.get('title', act.get('number'))}")
    else:
        gh = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
        gh.ensure_labels()
        log = plan_and_file(gh, cat, changes, contracts)
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
