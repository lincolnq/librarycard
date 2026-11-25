"""Upstream change fingerprints (shared by monitor/detect_changes.py and the mirror ingest).

See docs/SCHEMA.md#change_detection for the methods.
"""

from __future__ import annotations

import hashlib
import json
import re

from . import http
from .http import SourceError


def extract_json_path(data, path: str):
    """Tiny path language: a.b[0].c, a[key=value].b, a[*].b (list of values)."""
    tokens = re.findall(r"[^.\[\]]+|\[[^\]]*\]", path)
    cur = [data]
    for tok in tokens:
        nxt = []
        for node in cur:
            if tok.startswith("["):
                inner = tok[1:-1]
                if not isinstance(node, list):
                    continue
                if inner == "*":
                    nxt.extend(node)
                elif "=" in inner:
                    k, v = inner.split("=", 1)
                    nxt.extend(x for x in node if isinstance(x, dict) and str(x.get(k)) == v)
                else:
                    i = int(inner)
                    if -len(node) <= i < len(node):
                        nxt.append(node[i])
            else:
                if isinstance(node, dict) and tok in node:
                    nxt.append(node[tok])
        cur = nxt
    if not cur:
        raise SourceError(f"json_path {path!r} matched nothing", kind="schema")
    return cur[0] if len(cur) == 1 else cur


def fingerprint(cd: dict) -> tuple[str, str]:
    """Return (fingerprint, human-readable detail)."""
    method = cd["method"]
    url = cd["url"]
    params = cd.get("params")
    if method == "http_headers":
        r = http.head(url, params=params)
        wanted = cd.get("headers") or ["etag", "last-modified"]
        vals = {h: r.headers.get(h) for h in wanted}
        if not any(vals.values()):
            raise SourceError(f"none of headers {wanted} present on {url}; pick another method", kind="schema", url=url)
        detail = ", ".join(f"{k}={v}" for k, v in vals.items() if v)
        return hashlib.sha256(json.dumps(vals, sort_keys=True).encode()).hexdigest()[:16], detail
    r = http.request("GET", url, params=params, retries=2)
    if method == "content_hash":
        h = hashlib.sha256(r.content).hexdigest()
        return h[:16], f"sha256={h[:16]} bytes={len(r.content)}"
    if method == "json_field":
        try:
            data = r.json()
        except ValueError:
            raise SourceError(f"{url} did not return JSON", kind="parse", url=url) from None
        paths = cd["json_path"] if isinstance(cd["json_path"], list) else [cd["json_path"]]
        vals = {p: extract_json_path(data, p) for p in paths}
        s = json.dumps(vals, sort_keys=True, default=str)
        return hashlib.sha256(s.encode()).hexdigest()[:16], s[:400]
    if method == "regex":
        rx = re.compile(cd["pattern"])
        found = [m.group(1) if m.groups() else m.group(0) for m in rx.finditer(r.text)]
        if not found:
            raise SourceError(f"pattern {cd['pattern']!r} matched nothing at {url}", kind="schema", url=url)
        s = json.dumps(sorted(set(found)))
        return hashlib.sha256(s.encode()).hexdigest()[:16], f"matches={s[:300]}"
    raise ValueError(f"unknown change_detection method {method}")
