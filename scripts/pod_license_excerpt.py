#!/usr/bin/env python3
"""Save the license fields of matching datasets from an agency's Project Open Data catalog.

    python scripts/pod_license_excerpt.py <source_id> <data.json url> <title-or-identifier regex>

US federal agencies publish https://<agency>/data.json listing every dataset with a
`license` (and sometimes `rights`) field. That is often the clearest dataset-level
license statement available. This writes
evidence/licenses/<id>/<date>-<host>-data-json-excerpt.json with matching entries
(descriptions dropped) and prints their licenses. Cite it in NOTES.md.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from odc import http  # noqa: E402

MAX_ENTRIES = 100


def licenses_of(d: dict) -> list:
    """Dataset-level `license` (or the British spelling `licence`, used by FEC), plus any
    distribution-level licenses (CMS puts them only on distributions)."""
    out = [d.get("license") or d.get("licence")]
    out += [x.get("license") or x.get("licence") for x in d.get("distribution", []) or [] if isinstance(x, dict)]
    return sorted({str(x) for x in out if x})


sid, url, pattern = sys.argv[1], sys.argv[2], sys.argv[3]
data = http.get_json(url, timeout=120)
rx = re.compile(pattern, re.I)
hits = []
for d in data.get("dataset", []):
    if rx.search(d.get("title", "")) or rx.search(str(d.get("identifier", ""))):
        d = {k: v for k, v in d.items() if k not in ("description",)}
        d["_licenses_found"] = licenses_of(d)
        hits.append(d)
# newest first, so recent vintages are never cut off by MAX_ENTRIES
hits.sort(key=lambda d: str(d.get("modified", "")), reverse=True)
lic_counts: dict = {}
for d in data.get("dataset", []):
    k = "; ".join(licenses_of(d)) or None
    lic_counts[k] = lic_counts.get(k, 0) + 1
out = {
    "_source_url": url,
    "_retrieved": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    "_pattern": pattern,
    "_matches": len(hits),
    "_catalog_license_counts": lic_counts,
    "entries": hits[:MAX_ENTRIES],
}
d = ROOT / "evidence" / "licenses" / sid
d.mkdir(parents=True, exist_ok=True)
base = f"{dt.date.today().isoformat()}-{urlparse(url).netloc.replace('.', '-')}-data-json-excerpt"
p = d / f"{base}.json"
n = 2
while p.exists():  # never overwrite earlier evidence from the same day
    p = d / f"{base}-{n}.json"
    n += 1
p.write_text(json.dumps(out, indent=1) + "\n")
print(f"saved {p}: {len(hits)} matches (kept {min(len(hits), MAX_ENTRIES)}, newest first)")
for h in hits[:MAX_ENTRIES]:
    print(" ", h.get("title", "")[:80], "|", h["_licenses_found"] or "NO LICENSE FIELD", "|", h.get("modified", ""))
notes = d / "NOTES.md"
line = f"- `{p.name}` — excerpt of {url} (pattern `{pattern}`, {len(hits)} matches) — retrieved {out['_retrieved']}\n"
if notes.exists():
    txt = notes.read_text()
    txt = txt.replace("## Snapshots\n", "## Snapshots\n" + line, 1) if "## Snapshots\n" in txt else txt + "\n## Snapshots\n" + line
    notes.write_text(txt)
    print(f"appended snapshot line to {notes}")
else:
    print(f"NOTE: {notes} does not exist yet; run scripts/snapshot_license.py first or add the line by hand:\n{line}")
