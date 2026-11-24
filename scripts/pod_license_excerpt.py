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

sid, url, pattern = sys.argv[1], sys.argv[2], sys.argv[3]
data = http.get_json(url, timeout=120)
rx = re.compile(pattern, re.I)
hits = []
for d in data.get("dataset", []):
    if rx.search(d.get("title", "")) or rx.search(str(d.get("identifier", ""))):
        d = {k: v for k, v in d.items() if k not in ("description",)}
        hits.append(d)
lic_counts: dict = {}
for d in data.get("dataset", []):
    lic_counts[d.get("license")] = lic_counts.get(d.get("license"), 0) + 1
out = {
    "_source_url": url,
    "_retrieved": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    "_pattern": pattern,
    "_catalog_license_counts": lic_counts,
    "entries": hits[:25],
}
d = ROOT / "evidence" / "licenses" / sid
d.mkdir(parents=True, exist_ok=True)
p = d / f"{dt.date.today().isoformat()}-{urlparse(url).netloc.replace('.', '-')}-data-json-excerpt.json"
p.write_text(json.dumps(out, indent=1) + "\n")
print(f"saved {p}: {len(hits)} matches")
for h in hits[:25]:
    print(" ", h.get("title", "")[:80], "|", h.get("license"), "|", h.get("rights", ""))
