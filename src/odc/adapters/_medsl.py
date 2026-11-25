"""Shared code for MIT Election Data + Science Lab (MEDSL) statewide returns on Harvard Dataverse.

Used by: mit_election_president_state, mit_election_senate_state.

MEDSL publishes one CSV per office (e.g. 1976-2024-president.csv, 1976-2024-senate-state.csv). Dataverse may
"ingest" a CSV and serve it as tab-delimited .tab by default; we always request ``?format=original`` so we get the
uploaded comma-separated file whether or not it was ingested. File ids change with every dataset version, so the
adapter resolves the current file id from the dataset API on each call (one small JSON request).

Download URLs (https://dataverse.harvard.edu/api/access/datafile/<id>?format=original) redirect to a short-lived
signed URL on dvn-cloud-iqss.s3.amazonaws.com.

Value handling (documented in the catalog entries):
* year -> int; state_fips -> 2-digit zero-padded string ("1" -> "01")
* candidatevotes / totalvotes -> int (the senate file writes them as "7310.0")
* writein / special / unofficial -> bool ("True"/"False"; blank -> null)
* empty strings -> null
"""

from __future__ import annotations

from typing import Any, Callable

from ..http import SourceError
from ._common import dataverse_file_url, dataverse_files, pick_dataverse_file, scan_csv, state_abbr
from .base import FilterError

SERVER = "dataverse.harvard.edu"
PARTY_SIMPLIFIED = ["DEMOCRAT", "REPUBLICAN", "LIBERTARIAN", "OTHER"]

INT_COLS = ("year", "candidatevotes", "totalvotes", "state_cen", "state_ic")
BOOL_COLS = ("writein", "special", "unofficial")


def _int(v: str | None) -> int | None:
    if v is None or v.strip() in ("", "NA"):
        return None
    try:
        return int(float(v))
    except ValueError:
        raise SourceError(f"non-numeric value {v!r} where a number was expected", kind="parse") from None


def _bool(v: str | None) -> bool | None:
    if v is None or v.strip() == "":
        return None
    s = v.strip().lower()
    if s in ("true", "1"):
        return True
    if s in ("false", "0"):
        return False
    return None


def clean_row(row: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if k is None:
            continue
        v = v.strip() if isinstance(v, str) else v
        if k in INT_COLS:
            out[k] = _int(v)
        elif k in BOOL_COLS:
            out[k] = _bool(v)
        elif k == "state_fips":
            out[k] = v.zfill(2) if v else None
        else:
            out[k] = v if v not in ("", None) else None
    return out


def year_predicate(f: dict) -> Callable[[dict], bool]:
    """Common filters: year / year_from / year_to / state / party_simplified / candidate."""
    year = f.get("year")
    y0, y1 = f.get("year_from"), f.get("year_to")
    if year is not None and (y0 is not None or y1 is not None):
        raise FilterError("use either 'year' or 'year_from'/'year_to', not both")
    st = state_abbr(f["state"]) if f.get("state") else None
    parties = {p.upper() for p in f.get("party_simplified") or []}
    cand = f.get("candidate", "").strip().upper() or None

    def keep(r: dict) -> bool:
        try:
            y = int(float(r.get("year") or 0))
        except ValueError:
            return False
        if year is not None and y != year:
            return False
        if y0 is not None and y < y0:
            return False
        if y1 is not None and y > y1:
            return False
        if st and (r.get("state_po") or "").strip().upper() != st:
            return False
        if parties and (r.get("party_simplified") or "").strip().upper() not in parties:
            return False
        if cand and cand not in (r.get("candidate") or "").upper():
            return False
        return True

    return keep


def fetch_medsl(doi: str, file_pattern: str, *, columns: list[str], predicate: Callable[[dict], bool],
                limit: int, cache_allowed: bool) -> tuple[list[dict], int, list[str], dict]:
    """Resolve the current file in a MEDSL dataset, stream-filter it, return (rows, matched, urls, metadata).

    ``columns`` is the full expected header: scan_csv raises SourceError(kind="schema") if any is missing, and
    output rows contain exactly these columns in this order.
    """
    files, api_url = dataverse_files(SERVER, doi)
    df = pick_dataverse_file(files, file_pattern)
    url = dataverse_file_url(SERVER, df["id"], original=True)
    rows, matched = scan_csv(url, cache_allowed=cache_allowed, predicate=predicate, limit=limit,
                             delimiter=",", columns=columns, max_age_s=7 * 86400)
    meta = {"dataverse_doi": doi, "dataverse_version": df.get("_version"), "file_name": df.get("filename"),
            "file_id": df.get("id"), "file_md5": df.get("md5")}
    return [clean_row(r) for r in rows], matched, [api_url, url], meta
