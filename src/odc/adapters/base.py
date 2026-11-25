"""Adapter base class.

Every fetchable source has one module ``src/odc/adapters/<module>.py`` that
defines a module-level ``ADAPTER`` instance of a ``SourceAdapter`` subclass.
The catalog entry's ``adapter`` field names the module; ``adapter_version``
must equal ``ADAPTER.version`` (checked by tests).

An adapter declares:
* ``filters``  - the parameters ``fetch`` accepts (validated before any network call)
* ``contract`` - small live checks proving the publisher still returns what we
  expect (run by tests/contract and by the monitor's rotating sample)
* ``_fetch``   - the actual retrieval, returning rows + the URLs it requested

The base class handles validation, limits, provenance and the license-gated
cache flag. Adapters must not cache or persist data themselves.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..http import SourceError

MAX_LIMIT = 5000
DEFAULT_LIMIT = 500


class FilterError(ValueError):
    """Caller passed bad filters. Message must tell them how to fix it."""


@dataclass
class FilterSpec:
    name: str
    type: str  # "string" | "integer" | "number" | "boolean" | "string_list"
    description: str
    required: bool = False
    enum: list[Any] | None = None
    default: Any = None
    example: Any = None

    def as_dict(self) -> dict:
        d = {"name": self.name, "type": self.type, "required": self.required, "description": self.description}
        for k in ("enum", "default", "example"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        return d

    def coerce(self, value: Any) -> Any:
        t = self.type
        try:
            if t == "string":
                value = str(value)
            elif t == "integer":
                value = int(value)
            elif t == "number":
                value = float(value)
            elif t == "boolean":
                if isinstance(value, str):
                    value = value.strip().lower() in ("1", "true", "yes", "y")
                value = bool(value)
            elif t == "string_list":
                if isinstance(value, str):
                    value = [v.strip() for v in value.split(",") if v.strip()]
                value = [str(v) for v in value]
            else:
                raise AssertionError(f"unknown filter type {t}")
        except (TypeError, ValueError):
            raise FilterError(f"filter '{self.name}' must be {t}, got {value!r}") from None
        if self.enum is not None:
            vals = value if isinstance(value, list) else [value]
            bad = [v for v in vals if v not in self.enum]
            if bad:
                raise FilterError(f"filter '{self.name}' got {bad}; allowed: {self.enum}")
        return value


@dataclass
class Check:
    """A declarative assertion about a column in contract-test output."""

    column: str
    non_null: bool = True          # at least one row has a non-empty value
    numeric: bool = False          # every non-empty value parses as a number
    min: float | None = None       # every numeric value >= min
    max: float | None = None       # every numeric value <= max
    one_of: list[Any] | None = None  # every non-empty value is in this list
    regex: str | None = None       # every non-empty value fully matches


@dataclass
class ContractCase:
    """One live contract test. Keep them cheap: small limit, narrow filters."""

    name: str
    filters: dict
    min_rows: int = 1
    max_rows: int | None = None
    required_columns: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    limit: int = 50
    custom: Callable[[list[dict]], None] | None = None  # raise AssertionError on failure


@dataclass
class FetchResult:
    rows: list[dict]
    request_urls: list[str]
    notes: list[str] = field(default_factory=list)
    total_available: int | None = None
    metadata: dict = field(default_factory=dict)  # e.g. variable labels; returned as `metadata`


class SourceAdapter:
    source_id: str = ""
    version: str = "0.0.0"
    filters: list[FilterSpec] = []
    contract: list[ContractCase] = []
    # A one-paragraph hint shown in describe_source under fetch_parameters.
    usage: str = ""

    # ------------------------------------------------------------- public API
    def describe_filters(self) -> dict:
        return {"usage": self.usage, "filters": [f.as_dict() for f in self.filters], "max_limit": MAX_LIMIT, "default_limit": DEFAULT_LIMIT}

    def validate_filters(self, filters: dict | None) -> dict:
        filters = dict(filters or {})
        known = {f.name: f for f in self.filters}
        unknown = sorted(set(filters) - set(known))
        if unknown:
            raise FilterError(f"unknown filter(s) {unknown} for {self.source_id}; accepted: {sorted(known)}")
        out = {}
        for f in self.filters:
            if f.name in filters and filters[f.name] not in (None, "", []):
                out[f.name] = f.coerce(filters[f.name])
            elif f.required:
                ex = f" e.g. {f.example!r}" if f.example is not None else ""
                raise FilterError(f"filter '{f.name}' is required for {self.source_id}: {f.description}{ex}")
            elif f.default is not None:
                out[f.name] = f.default
        return out

    def fetch(self, entry: dict, filters: dict | None, limit: int | None = None) -> dict:
        """Validate, fetch, and wrap rows with provenance. ``entry`` is the catalog entry."""
        limit = DEFAULT_LIMIT if limit is None else int(limit)
        if limit < 1 or limit > MAX_LIMIT:
            raise FilterError(f"limit must be between 1 and {MAX_LIMIT}")
        clean = self.validate_filters(filters)
        cache_allowed = entry["license"]["redistribution"] == "allowed"
        retrieved_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        res = self._fetch(clean, limit + 1, cache_allowed)
        rows = res.rows
        truncated = len(rows) > limit
        rows = rows[:limit]
        columns: list[str] = []
        for r in rows[:50]:
            for k in r:
                if k not in columns:
                    columns.append(k)
        return {
            "source_id": self.source_id,
            "row_count": len(rows),
            "truncated": truncated,
            "columns": columns,
            "rows": rows,
            "notes": res.notes,
            "metadata": res.metadata,
            "provenance": provenance(entry, self, clean, res.request_urls, retrieved_at, res.total_available),
        }

    # -------------------------------------------------------- for subclasses
    def _fetch(self, filters: dict, limit: int, cache_allowed: bool) -> FetchResult:
        raise NotImplementedError

    # -------------------------------------------------------- mirroring (src/odc/mirror.py)
    # Sources with license.redistribution == "allowed" are mirrored into R2 and served from there.
    # To opt in, define mirror_plan(); see docs/MIRROR.md.
    mirror_partition_keys: list[str] = []   # partition key names, coarse to fine (e.g. ["table", "geography", "state"])
    mirror_required: list[str] = []         # partition keys a reader must filter on (for very large sources)
    mirror_semantics: dict[str, str] = {}   # column -> state_postal | state_fips | county_fips | year | date

    def mirror_plan(self):
        """Yield mirror.MirrorUnit(partition, filters, split_by) covering the whole dataset."""
        raise NotImplementedError

    def mirror_rows(self, unit) -> tuple:
        """Return (rows_iterable, request_urls, notes, metadata) for one unit. Default: call _fetch without a
        row limit. Override to stream when a unit is too big to hold in memory."""
        clean = self.validate_filters(unit.filters)
        res = self._fetch(clean, 10**12, True)
        return res.rows, res.request_urls, res.notes, res.metadata


def provenance(entry: dict, adapter: SourceAdapter, filters: dict, urls: list[str], retrieved_at: str, total: int | None) -> dict:
    lic = entry["license"]
    p = {
        "source_id": entry["id"],
        "source_name": entry["name"],
        "publisher": entry["publisher"]["name"],
        "homepage": entry["homepage"],
        "retrieved_at": retrieved_at,
        "request_urls": urls,
        "filters": filters,
        "adapter_version": adapter.version,
        "catalog_status": entry["status"],
        "license": {
            "name": lic["name"],
            "url": lic["url"],
            "redistribution": lic["redistribution"],
            "commercial_use": lic["commercial_use"],
        },
        "citation": f"{lic['attribution']} Retrieved {retrieved_at[:10]} from {urls[0] if urls else entry['homepage']}.",
    }
    if total is not None:
        p["total_rows_matching_at_source"] = total
    return p


# ------------------------------------------------------------- row helpers

def rows_from_table(table: list[list[Any]]) -> list[dict]:
    """[[header...], [row...], ...] -> list of dicts (Census API style)."""
    if not table:
        return []
    header = table[0]
    return [dict(zip(header, r)) for r in table[1:]]


def match_ci(value: Any, wanted: Iterable[str]) -> bool:
    v = str(value).strip().lower()
    return any(v == str(w).strip().lower() for w in wanted)


def as_list(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def require(cond: bool, msg: str, kind: str = "schema") -> None:
    """Raise SourceError when the publisher's response doesn't look like we expect."""
    if not cond:
        raise SourceError(msg, kind=kind)
