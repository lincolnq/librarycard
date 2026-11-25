"""Catalog loading, validation and search.

The catalog is the set of YAML files in ``catalog/``. One file per source, named
``<id>.yaml``. Files starting with ``_`` are ignored (templates, notes).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
import yaml

REPO_ROOT = Path(os.environ.get("ODC_REPO_ROOT", Path(__file__).resolve().parents[2]))
CATALOG_DIR = REPO_ROOT / "catalog"
SCHEMA_PATH = REPO_ROOT / "schema" / "catalog-entry.schema.json"
CURRENT_SCHEMA_VERSION = 1

US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
    "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
    "puerto rico",
}
US_ALIASES = {"us", "usa", "united states", "america", "u.s.", "u.s.a."} | US_STATES


class CatalogError(Exception):
    pass


@lru_cache(maxsize=1)
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def catalog_files(catalog_dir: Path | None = None) -> list[Path]:
    d = catalog_dir or CATALOG_DIR
    return sorted(p for p in d.glob("*.yaml") if not p.name.startswith("_"))


def _normalize(obj: Any) -> Any:
    """YAML parses bare dates into datetime.date; the schema wants strings."""
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()[:10]
    return obj


def load_entry(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise CatalogError(f"{path}: YAML syntax error (quote values containing ': ' or starting with a special character): {e}") from None
    if not isinstance(data, dict):
        raise CatalogError(f"{path}: not a mapping")
    return _normalize(data)


def validate_entry(entry: dict, path: Path | None = None) -> list[str]:
    """Return a list of human-readable problems (empty list == valid)."""
    problems: list[str] = []
    v = jsonschema.Draft202012Validator(schema(), format_checker=jsonschema.FormatChecker())
    for err in sorted(v.iter_errors(entry), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        problems.append(f"{loc}: {err.message}")
    if path is not None and entry.get("id") != path.stem:
        problems.append(f"id: '{entry.get('id')}' must equal file name stem '{path.stem}'")
    lic = entry.get("license", {})
    ev = lic.get("evidence")
    if ev:
        ev_dir = REPO_ROOT / ev
        if not ev_dir.is_dir():
            problems.append(f"license/evidence: directory {ev} does not exist")
        else:
            snaps = [p for p in ev_dir.iterdir() if p.name != "NOTES.md"]
            if not snaps:
                problems.append(f"license/evidence: {ev} has no snapshot files")
            if not (ev_dir / "NOTES.md").exists():
                problems.append(f"license/evidence: {ev}NOTES.md missing")
    if lic.get("redistribution") == "unknown":
        problems.append("license/redistribution: 'unknown' is not allowed in a committed entry; use link_only (see docs/POLICY.md)")
    return problems


@dataclass
class Catalog:
    entries: dict[str, dict]

    @classmethod
    def load(cls, catalog_dir: Path | None = None, validate: bool = True) -> "Catalog":
        entries: dict[str, dict] = {}
        errors: list[str] = []
        for p in catalog_files(catalog_dir):
            e = load_entry(p)
            if validate:
                errors += [f"{p.name}: {m}" for m in validate_entry(e, p)]
            entries[e.get("id", p.stem)] = e
        if errors:
            raise CatalogError("Invalid catalog entries:\n  " + "\n  ".join(errors))
        return cls(entries)

    def get(self, source_id: str) -> dict:
        try:
            return self.entries[source_id]
        except KeyError:
            close = [i for i in self.entries if source_id.split("-")[0] in i]
            hint = f" Did you mean one of: {', '.join(close[:5])}?" if close else ""
            raise CatalogError(f"Unknown source_id '{source_id}'.{hint} Use search_catalog to find ids.") from None

    # ------------------------------------------------------------------ search
    def search(
        self,
        query: str = "",
        domain: str | None = None,
        geography: str | None = None,
        time_range: str | None = None,
        include_retired: bool = False,
        limit: int = 10,
    ) -> list[dict]:
        terms = _tokens(query)
        results = []
        for e in self.entries.values():
            if e["status"] == "retired" and not include_retired:
                continue
            if domain and domain not in e["domains"]:
                continue
            if geography and not _geo_match(e, geography):
                continue
            if time_range and not _time_overlap(e, time_range):
                continue
            score = _score(e, terms) if terms else 1.0
            if terms and score <= 0:
                continue
            # Small nudge so healthy, fetchable sources rank above equally relevant broken ones.
            if e["status"] == "healthy" and e["adapter"]:
                score *= 1.05
            elif e["status"] in ("quarantined", "retired"):
                score *= 0.7
            results.append((score, e))
        results.sort(key=lambda t: (-t[0], t[1]["id"]))
        return [summary(e, round(s, 3)) for s, e in results[:limit]]


def fetchable(e: dict) -> bool:
    return bool(e.get("adapter")) and e["status"] in ("healthy", "degraded")


def summary(e: dict, score: float | None = None) -> dict:
    out = {
        "id": e["id"],
        "name": e["name"],
        "publisher": e["publisher"]["name"],
        "description": e["description"],
        "domains": e["domains"],
        "geographic_granularity": e["coverage"]["geographic_granularity"],
        "time_range": e["coverage"]["time_range"],
        "access_method": e["access"]["method"],
        "status": e["status"],
        "fetchable": fetchable(e),
        "redistribution": e["license"]["redistribution"],
        "caveat_count": len(e["caveats"]),
    }
    if e["status"] != "healthy":
        out["status_reason"] = e["status_reason"]
    if e["access"].get("mcp_server"):
        out["mcp_server"] = e["access"]["mcp_server"]["url"]
    if score is not None:
        out["score"] = score
    return out


_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "and", "or", "in", "for", "by", "to", "on", "data", "dataset", "what", "which", "how", "is", "are", "with", "at"}


def _tokens(s: str) -> list[str]:
    return [t for t in _WORD.findall((s or "").lower()) if t not in _STOP]


def _stem(t: str) -> str:
    for suf in ("ies", "es", "s"):
        if len(t) > 4 and t.endswith(suf):
            return t[: -len(suf)] + ("y" if suf == "ies" else "")
    return t


def _field_text(e: dict) -> dict[str, str]:
    kv = " ".join(f"{v['name']} {v.get('label', '')} {v['definition']}" for v in e["key_variables"])
    return {
        "id_name": f"{e['id'].replace('-', ' ')} {e['name']}",
        "tags": " ".join(e["tags"] + e["domains"]).replace("_", " ").replace("-", " "),
        "publisher": e["publisher"]["name"],
        "description": e["description"],
        "variables": kv,
        "coverage": f"{e['coverage']['geography']} {' '.join(e['coverage']['geographic_granularity'])} {e['coverage']['unit_of_observation']}".replace("_", " "),
        "caveats": " ".join(e["caveats"]),
    }


_WEIGHTS = {"id_name": 5.0, "tags": 4.0, "publisher": 2.0, "description": 2.0, "variables": 1.5, "coverage": 1.5, "caveats": 0.3}


def _score(e: dict, terms: list[str]) -> float:
    fields = {k: {_stem(t) for t in _tokens(v)} for k, v in _field_text(e).items()}
    score = 0.0
    matched = 0
    for t in terms:
        st = _stem(t)
        hit = False
        for f, words in fields.items():
            if st in words:
                score += _WEIGHTS[f]
                hit = True
            elif len(st) >= 4 and any(w.startswith(st) for w in words):
                score += _WEIGHTS[f] * 0.4
                hit = True
        matched += hit
    if not matched:
        return 0.0
    # Reward covering more of the query.
    return score * (matched / len(terms))


def _geo_match(e: dict, geography: str) -> bool:
    g = geography.strip().lower()
    cov = e["coverage"]
    gran = {x.replace("_", " ") for x in cov["geographic_granularity"]}
    if g in gran or g.rstrip("s") in gran or g.replace(" ", "_") in cov["geographic_granularity"]:
        return True
    if g in US_ALIASES and "US" in cov["countries"]:
        return True
    if len(g) == 2 and g.upper() in cov["countries"]:
        return True
    return g in cov["geography"].lower()


def _parse_year_range(s: str) -> tuple[int, int]:
    years = [int(y) for y in re.findall(r"\d{4}", s)]
    if not years:
        raise CatalogError(f"time_range '{s}' must contain a 4-digit year, e.g. '2020' or '2010-2020'")
    return min(years), max(years)


def _time_overlap(e: dict, time_range: str) -> bool:
    lo, hi = _parse_year_range(time_range)
    tr = e["coverage"]["time_range"]
    start = int(tr["start"][:4])
    end = int(tr["end"][:4]) if tr.get("end") else dt.date.today().year
    return start <= hi and lo <= end


def status_report(cat: Catalog, recent_days: int = 30) -> dict:
    counts: dict[str, int] = {"healthy": 0, "degraded": 0, "quarantined": 0, "retired": 0}
    for e in cat.entries.values():
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    today = dt.date.today()
    recent = []
    for e in cat.entries.values():
        since = dt.date.fromisoformat(e["status_since"])
        if (today - since).days <= recent_days:
            recent.append({"id": e["id"], "status": e["status"], "status_since": e["status_since"], "status_reason": e["status_reason"]})
    recent.sort(key=lambda r: r["status_since"], reverse=True)
    stale = sorted(
        ({"id": e["id"], "last_verified": e["last_verified"]} for e in cat.entries.values()
         if (today - dt.date.fromisoformat(e["last_verified"])).days > 90 and e["status"] != "retired"),
        key=lambda r: r["last_verified"],
    )
    return {
        "total_sources": len(cat.entries),
        "counts_by_status": counts,
        "fetchable": sum(1 for e in cat.entries.values() if fetchable(e)),
        "catalog_only_restricted": sorted(e["id"] for e in cat.entries.values() if e["access"]["method"] == "restricted"),
        "recently_changed_status": recent,
        "not_verified_in_90_days": stale,
        "as_of": today.isoformat(),
    }
