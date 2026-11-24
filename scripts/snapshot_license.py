#!/usr/bin/env python3
"""Save dated snapshots of a source's license / terms pages as license evidence.

    python scripts/snapshot_license.py <source_id> <url> [<url> ...]

For each URL this writes ``evidence/licenses/<id>/<YYYY-MM-DD>-<slug>.txt``: a
header (URL, retrieval timestamp, HTTP status, sha256 of the raw bytes) followed
by the page text (HTML tags stripped, whitespace collapsed). Text is stored
instead of raw HTML so evidence is small, readable and diffable across
re-checks; the raw sha256 proves which bytes were read.

It also creates ``NOTES.md`` from a template if missing and appends a line per
snapshot under "## Snapshots". YOU must then fill in the "Operative terms" and
"Classification" sections of NOTES.md by reading the snapshot. A failed fetch
writes a ``-unavailable.txt`` file with the error; per docs/POLICY.md that
means classify as link_only unless another snapshot shows clear terms.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from odc import http  # noqa: E402

TEMPLATE = """# License evidence: {sid}

## Snapshots

## Operative terms
<!-- Quote the exact sentence(s) that grant or restrict reuse, with the snapshot file they come from. -->

## Classification
<!-- redistribution: allowed | link_only ; commercial_use: yes | no | unclear ; and WHY, per docs/POLICY.md#licensing -->
"""


def to_text(raw: bytes, content_type: str) -> str:
    s = raw.decode("utf-8", errors="replace")
    if "html" not in content_type and not s.lstrip().lower().startswith(("<!doctype", "<html")):
        return s
    s = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article)>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def slug(url: str) -> str:
    p = urlparse(url)
    base = (p.netloc + p.path).rstrip("/")
    return re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[-70:]


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    sid, urls = sys.argv[1], sys.argv[2:]
    d = ROOT / "evidence" / "licenses" / sid
    d.mkdir(parents=True, exist_ok=True)
    notes = d / "NOTES.md"
    if not notes.exists():
        notes.write_text(TEMPLATE.format(sid=sid))
    today = dt.date.today().isoformat()
    lines = []
    for url in urls:
        ts = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        try:
            r = http.request("GET", url, retries=1, ok_statuses=(200,))
            raw = r.content
            body = to_text(raw, r.headers.get("content-type", ""))
            sha = hashlib.sha256(raw).hexdigest()
            name = f"{today}-{slug(url)}.txt"
            header = f"URL: {url}\nFinal-URL: {r.url}\nRetrieved: {ts}\nHTTP-Status: {r.status_code}\nRaw-SHA256: {sha}\nRaw-Bytes: {len(raw)}\n---\n"
            (d / name).write_text(header + body + "\n")
            lines.append(f"- `{name}` — {url} — retrieved {ts} — sha256 {sha[:16]}…")
            print(f"saved {d / name} ({len(body)} chars of text)")
            if len(body) < 300:
                print(f"WARNING: only {len(body)} chars of text — probably a JavaScript app or a bot-challenge page. "
                      "This snapshot does NOT show the terms; treat the terms as unfetchable (docs/POLICY.md#licensing) "
                      "or find a dataset-level statement elsewhere (data.json, Socrata/ArcGIS metadata).")
        except Exception as e:  # noqa: BLE001
            name = f"{today}-{slug(url)}-unavailable.txt"
            (d / name).write_text(f"URL: {url}\nAttempted: {ts}\nError: {e}\n")
            err = " ".join(str(e).split())[:200]  # one line, so NOTES.md stays a clean list
            lines.append(f"- `{name}` — {url} — FETCH FAILED {ts}: {err}")
            print(f"FAILED {url}: {e}")
    txt = notes.read_text()
    marker = "## Snapshots\n"
    i = txt.find(marker)
    if i < 0:
        txt += "\n" + marker
        i = txt.find(marker)
    j = i + len(marker)
    # append after existing snapshot lines
    rest = txt[j:]
    k = rest.find("\n## ")
    block, tail = (rest, "") if k < 0 else (rest[:k + 1], rest[k + 1:])
    block = block.rstrip("\n") + "\n" + "\n".join(lines) + "\n\n"
    notes.write_text(txt[:j] + block.lstrip("\n") + tail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
