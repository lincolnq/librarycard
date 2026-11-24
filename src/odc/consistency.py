"""Cross-file consistency checks that JSON Schema can't express.

Run via ``odc validate`` and tests/test_catalog.py. Each problem string names
the file to fix.
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import urlparse

import yaml

from .adapters import adapter_for
from .catalog import REPO_ROOT, Catalog

ALLOWLIST = REPO_ROOT / "ops" / "network-allowlist.txt"
QUEUE = REPO_ROOT / "ops" / "queue.yaml"


def allowlisted_domains() -> set[str]:
    if not ALLOWLIST.exists():
        return set()
    out = set()
    for line in ALLOWLIST.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line.lower())
    return out


def domain_allowed(host: str, allowed: set[str]) -> bool:
    host = host.lower()
    return any(host == d or (d.startswith("*.") and host.endswith(d[1:])) for d in allowed)


def entry_hosts(e: dict) -> set[str]:
    urls = [ep["url"] for ep in e["access"]["endpoints"]]
    cd = e["change_detection"]
    if cd.get("url"):
        urls.append(cd["url"])
    hosts = set()
    for u in urls:
        h = urlparse(u).hostname
        if h:
            hosts.add(h)
    return hosts


def load_queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    data = yaml.safe_load(QUEUE.read_text()) or {}
    return data.get("queued", []) or []


def consistency_problems(cat: Catalog) -> list[str]:
    problems: list[str] = []
    allowed = allowlisted_domains()
    today = dt.date.today()
    for sid, e in sorted(cat.entries.items()):
        f = f"catalog/{sid}.yaml"
        # adapter wiring
        if e["adapter"]:
            try:
                a = adapter_for(e)
            except Exception as ex:  # noqa: BLE001
                problems.append(f"{f}: adapter '{e['adapter']}' failed to import: {ex}")
                continue
            if a.source_id != sid:
                problems.append(f"src/odc/adapters/{e['adapter']}.py: ADAPTER.source_id={a.source_id!r} but catalog id is {sid!r}")
            if a.version != e["adapter_version"]:
                problems.append(f"{f}: adapter_version {e['adapter_version']} != ADAPTER.version {a.version} (bump both together)")
            if not a.contract:
                problems.append(f"src/odc/adapters/{e['adapter']}.py: no contract cases defined")
            if not a.filters:
                problems.append(f"src/odc/adapters/{e['adapter']}.py: no filters declared")
            # network allowlist: every host the adapter or monitor touches
            for h in entry_hosts(e):
                if not domain_allowed(h, allowed):
                    problems.append(f"ops/network-allowlist.txt: missing {h} (used by {f})")
        # dates
        for k in ("status_since", "last_verified"):
            if dt.date.fromisoformat(e[k]) > today:
                problems.append(f"{f}: {k} is in the future")
        if e["status"] != "healthy" and len(e["status_reason"]) < 15:
            problems.append(f"{f}: non-healthy status needs a descriptive status_reason")
        for r in e.get("related", []):
            if r not in cat.entries:
                problems.append(f"{f}: related id '{r}' not in catalog")
        if e["change_detection"]["method"] == "none" and e["access"]["method"] != "restricted":
            problems.append(f"{f}: change_detection.method 'none' is only allowed for restricted entries")
    for q in load_queue():
        if q.get("id") in cat.entries:
            problems.append(f"ops/queue.yaml: '{q['id']}' is queued but also in catalog/ (remove it from the queue once onboarded)")
        for k in ("id", "name", "reason", "detail", "added"):
            if k not in q:
                problems.append(f"ops/queue.yaml: entry {q.get('id', '?')} missing '{k}'")
        if q.get("reason") not in ("network", "license", "credentials", "scope", "low_priority", "duplicate", "format", "unstable"):
            problems.append(f"ops/queue.yaml: entry {q.get('id', '?')} has unknown reason {q.get('reason')!r}")
    return problems
