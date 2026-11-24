"""ACS table-based Summary File (bulk, pipe-delimited). Catalog: catalog/census-acs-summary-file.yaml

Layout on www2.census.gov (2021 onward):
  /programs-surveys/acs/summary_file/<YEAR>/table-based-SF/data/<5YRData|1YRData>/acsdt<5y|1y><YEAR>-<table>.dat
  /programs-surveys/acs/summary_file/<YEAR>/table-based-SF/documentation/Geos<YEAR><5YR|1YR>.txt   (GEO_ID -> NAME, ~90 MB)
  /programs-surveys/acs/summary_file/<YEAR>/table-based-SF/documentation/ACS<YEAR><5YR|1YR>_Table_Shells.txt (labels)
Each .dat file has header GEO_ID|<TABLE>_E001|<TABLE>_M001|... covering every published geography.
"""

from __future__ import annotations

import datetime as dt
import re

from .. import http
from ..http import SourceError
from ._common import scan_csv, state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter

BASE = "https://www2.census.gov/programs-surveys/acs/summary_file"
FIRST_YEAR = 2021  # table-based summary files start with the 2021 release

# friendly name -> (summary level, nested within state?)
GEOGRAPHIES = {
    "nation": ("010", False),
    "region": ("020", False),
    "division": ("030", False),
    "state": ("040", False),
    "county": ("050", True),
    "county_subdivision": ("060", True),
    "tract": ("140", True),
    "block_group": ("150", True),
    "place": ("160", True),
    "metro_area": ("310", False),
    "congressional_district": ("500", True),
    "state_legislative_district_upper": ("610", True),
    "state_legislative_district_lower": ("620", True),
    "zcta": ("860", False),
    "school_district_unified": ("970", True),
}
# Census "jam values": annotations encoded as impossible negative numbers.
JAM_VALUES = {"-666666666", "-999999999", "-888888888", "-222222222", "-333333333", "-555555555", "-111111111", "-777777777"}

_latest_cache: dict[str, int] = {}


def _dat_url(year: int, dataset: str, table: str) -> str:
    d, s = ("5YRData", "5y") if dataset == "5yr" else ("1YRData", "1y")
    return f"{BASE}/{year}/table-based-SF/data/{d}/acsdt{s}{year}-{table.lower()}.dat"


def _doc_url(year: int, dataset: str, kind: str) -> str:
    tag = "5YR" if dataset == "5yr" else "1YR"
    name = f"Geos{year}{tag}.txt" if kind == "geos" else f"ACS{year}{tag}_Table_Shells.txt"
    return f"{BASE}/{year}/table-based-SF/documentation/{name}"


def latest_year(dataset: str) -> int:
    if dataset in _latest_cache:
        return _latest_cache[dataset]
    this = dt.date.today().year
    for y in range(this, FIRST_YEAR - 1, -1):
        try:
            http.head(_dat_url(y, dataset, "B01003"))
            _latest_cache[dataset] = y
            return y
        except SourceError as e:
            if e.status in (401, 403, 404):
                continue  # that release year isn't published (yet); www2.census.gov answers 401 for missing files
            raise
    raise SourceError("could not find any ACS table-based summary file release", kind="http")


def _clean(v: str | None):
    if v is None:
        return None
    v = v.strip()
    if v == "" or v in JAM_VALUES:
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() and "." not in v else f
    except ValueError:
        return v


class CensusAcsSummaryFile(SourceAdapter):
    source_id = "census-acs-summary-file"
    version = "1.0.1"
    usage = ("Pick a detailed table id (e.g. B19013 = median household income, B01003 = total population, "
             "B17001 = poverty status) and a geography. Columns are <TABLE>_E### (estimate) and <TABLE>_M### "
             "(90% margin of error); `metadata.variable_labels` maps them to labels. Table ids are listed in "
             "the table shells file (see catalog endpoints). 5-year data covers all geographies down to block "
             "group; 1-year covers only areas with 65,000+ people.")
    filters = [
        FilterSpec("table", "string", "ACS detailed table id, e.g. 'B19013'.", required=True, example="B19013"),
        FilterSpec("geography", "string", "Geographic summary level.", required=True, enum=sorted(GEOGRAPHIES), example="county"),
        FilterSpec("dataset", "string", "'5yr' (default; all geographies) or '1yr' (65k+ population areas only).", enum=["5yr", "1yr"], default="5yr"),
        FilterSpec("year", "integer", f"Release year (end year of the period), {FIRST_YEAR} or later. Default: latest available."),
        FilterSpec("state", "string", "Restrict state-nested geographies to one state (postal code or FIPS).", example="CA"),
        FilterSpec("geo_ids", "string_list", "Exact GEO_IDs, e.g. ['0500000US06037']. Overrides geography/state matching but geography must still be set."),
        FilterSpec("variables", "string_list", "Subset of columns to return, e.g. ['B19013_E001','B19013_M001']. Default: all columns of the table."),
        FilterSpec("include_names", "boolean", "Join human-readable NAME from the Geos file (~90 MB download on first use).", default=True),
    ]
    contract = [
        ContractCase(
            name="state_median_income",
            filters={"table": "B19013", "geography": "state", "include_names": True},
            min_rows=50, max_rows=60,
            required_columns=["GEO_ID", "NAME", "B19013_E001", "B19013_M001"],
            checks=[Check("B19013_E001", numeric=True, min=15000, max=200000),
                    Check("GEO_ID", regex=r"0400000US\d\d")],
            limit=100,
        ),
        ContractCase(
            name="tract_population_one_state",
            filters={"table": "B01003", "geography": "tract", "state": "DE", "include_names": False},
            min_rows=150,
            required_columns=["GEO_ID", "B01003_E001"],
            checks=[Check("B01003_E001", numeric=True, min=0, max=100000), Check("GEO_ID", regex=r"1400000US10\d{9}")],
            limit=1000,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        table = f["table"].upper().strip()
        if not re.fullmatch(r"[BC]\d{5}[A-Z]{0,4}", table):
            raise FilterError("table must look like B19013, B01001A or C17002 (detailed tables only)")
        dataset = f.get("dataset", "5yr")
        year = f.get("year") or latest_year(dataset)
        if year < FIRST_YEAR:
            raise FilterError(f"table-based summary files start in {FIRST_YEAR}; for earlier years see data.census.gov or the Census API (restricted)")
        sumlev, nested = GEOGRAPHIES[f["geography"]]
        st = state_fips(f["state"]) if f.get("state") else None
        if st and not nested:
            raise FilterError(f"geography '{f['geography']}' is not nested within states; drop the state filter")
        geo_ids = set(f.get("geo_ids") or [])

        def keep(row: dict) -> bool:
            g = row.get("GEO_ID", "")
            if geo_ids:
                return g in geo_ids
            if g[:3] != sumlev:
                return False
            if g[5:7] != "00":
                return False  # geographic components (urban/rural parts, AIAN areas, ...) are not whole areas
            if st:
                return g.split("US", 1)[-1][:2] == st
            return True

        url = _dat_url(year, dataset, table)
        try:
            rows, matched = scan_csv(url, cache_allowed=cache_allowed, predicate=keep, limit=limit, delimiter="|", max_age_s=30 * 86400)
        except SourceError as e:
            if e.status in (401, 404):
                raise FilterError(f"no {dataset} file for table {table} in {year} ({url}). Check the table id; 1-year data omits some tables.") from None
            raise
        wanted = f.get("variables")
        with_names = f.get("include_names", True)
        out = []
        for r in rows:
            rec = {"GEO_ID": r["GEO_ID"], "NAME": None} if with_names else {"GEO_ID": r["GEO_ID"]}
            for k, v in r.items():
                if k == "GEO_ID" or (wanted and k not in wanted):
                    continue
                rec[k] = _clean(v)
            out.append(rec)
        urls = [url]
        notes = [f"ACS {dataset} {year if dataset == '1yr' else f'{year - 4}-{year}'} estimates. Margins of error are 90% confidence.",
                 "Census 'jam values' (e.g. -666666666 = estimate not computable) were converted to null."]
        if with_names and out:
            names = self._names(year, dataset, {r["GEO_ID"] for r in out}, cache_allowed)
            for r in out:
                r["NAME"] = names.get(r["GEO_ID"])
            urls.append(_doc_url(year, dataset, "geos"))
        labels = self._labels(year, dataset, table, cache_allowed)
        return FetchResult(out, urls, notes, total_available=matched,
                           metadata={"year": year, "dataset": dataset, "table": table, "variable_labels": labels})

    def _names(self, year: int, dataset: str, ids: set[str], cache_allowed: bool) -> dict[str, str]:
        rows, _ = scan_csv(_doc_url(year, dataset, "geos"), cache_allowed=cache_allowed, delimiter="|",
                           predicate=lambda r: r.get("GEO_ID") in ids, limit=len(ids) + 1, max_age_s=60 * 86400,
                           encoding="latin-1")
        return {r["GEO_ID"]: r.get("NAME") for r in rows}

    def _labels(self, year: int, dataset: str, table: str, cache_allowed: bool) -> dict[str, str]:
        try:
            rows, _ = scan_csv(_doc_url(year, dataset, "shells"), cache_allowed=cache_allowed, delimiter="|",
                               predicate=lambda r: r.get("Table ID") == table, limit=2000, max_age_s=60 * 86400,
                               encoding="latin-1")
        except SourceError:
            return {}
        out = {}
        for r in rows:
            uid = r.get("Unique ID", "")  # e.g. B19013_001
            if "_" in uid:
                t, n = uid.split("_", 1)
                label = f"{r.get('Title', '')} — {r.get('Label', '')} (universe: {r.get('Universe', '')})"
                out[f"{t}_E{n}"] = "Estimate: " + label
                out[f"{t}_M{n}"] = "Margin of error (90%): " + label
        return out


ADAPTER = CensusAcsSummaryFile()
