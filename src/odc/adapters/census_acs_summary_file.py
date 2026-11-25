"""ACS table-based Summary File (bulk, pipe-delimited). Catalog: catalog/census-acs-summary-file.yaml

Layout on www2.census.gov (2021 onward):
  /programs-surveys/acs/summary_file/<YEAR>/table-based-SF/data/<5YRData|1YRData>/acsdt<5y|1y><YEAR>-<table>.dat
  /programs-surveys/acs/summary_file/<YEAR>/table-based-SF/documentation/Geos<YEAR><5YR|1YR>.txt   (GEO_ID -> NAME, ~90 MB)
  /programs-surveys/acs/summary_file/<YEAR>/table-based-SF/documentation/ACS<YEAR><5YR|1YR>_Table_Shells.txt (labels)
Each .dat file has header GEO_ID|<TABLE>_E001|<TABLE>_M001|... covering every published geography.

Mirror (docs/MIRROR.md): the full summary file is >1,000 tables x 2 datasets, so the R2 mirror covers a curated set
of the most-used tables (MIRROR_TABLES) for the latest 5-year release only, every geography in GEOGRAPHIES.
To widen it, add table ids to MIRROR_TABLES, bump `version` (minor) here and in the catalog entry, and update
access.notes / the mirror caveat in catalog/census-acs-summary-file.yaml.
"""

from __future__ import annotations

import csv
import datetime as dt
import re

from .. import http
from ..http import SourceError
from ._common import FIPS_STATE, scan_csv, state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

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

# Tables mirrored to R2 (latest 5-year release, all GEOGRAPHIES). Keep in sync with the catalog entry's access.notes
# and mirror caveat. Cost scales with columns: measured ~0.5 s of ingest and ~1.1 MB compressed per column (E or M)
# per table, plus ~5 s per table (452k geography rows each). These 33 tables have 486 columns (~7 min, ~0.55 GB), sized
# to finish in one mirror run here. Wide tables left out for now (B17001 118 cols, B27010 132, C24010 146, B18101 78,
# B21001 78, B08301 42, B08303 26, B28002 26, B25034 22, B25070 22, B25024 22, B05002 54, B08201 60) can be added
# when the ingest runs as a scheduled workflow with a longer budget.
MIRROR_TABLES = [
    "B01001",  # sex by age
    "B01002",  # median age by sex
    "B01003",  # total population
    "B02001",  # race
    "B03002",  # Hispanic or Latino origin by race
    "B05001",  # nativity and citizenship status
    "B11001",  # household type
    "B15003",  # educational attainment (25+)
    "B17020",  # poverty status by age
    "B19001",  # household income brackets
    "B19013",  # median household income
    "B19057",  # public assistance income
    "B19083",  # Gini index
    "B19113",  # median family income
    "B19301",  # per capita income
    "B22003",  # SNAP receipt by poverty status
    "B23025",  # employment status (16+)
    "B25001",  # housing units
    "B25002",  # occupancy status
    "B25003",  # tenure
    "B25004",  # vacancy status
    "B25010",  # average household size by tenure
    "B25035",  # median year structure built
    "B25058",  # median contract rent
    "B25064",  # median gross rent
    "B25071",  # median gross rent as a percentage of household income
    "B25077",  # median home value
    "B25088",  # median selected monthly owner costs
    "B25105",  # median monthly housing costs
    "B26001",  # group quarters population
    "B27020",  # health insurance coverage by citizenship (sum the no-coverage lines for the uninsured total)
    "B29001",  # citizen voting-age population by age
    "C16002",  # household language by limited English speaking status
]
MIRROR_DATASET = "5yr"


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
        return int(v)  # fast path: most cells are plain integers (the mirror ingest parses millions of them)
    except ValueError:
        pass
    try:
        f = float(v)
        return int(f) if f.is_integer() and "." not in v else f
    except ValueError:
        return v


class CensusAcsSummaryFile(SourceAdapter):
    source_id = "census-acs-summary-file"
    version = "1.1.0"
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

    # -------------------------------------------------------------- mirror (docs/MIRROR.md)
    # One unit per table of the latest 5-year release: the table's .dat file is streamed once and split into
    # partitions by geography and (for state-nested geographies) state. Rows = fetch rows (GEO_ID, NAME, cells) plus
    # the partition columns table/geography/state. Geos names are loaded once per ingest, labels go in metadata.
    mirror_partition_keys = ["table", "geography", "state"]
    mirror_required = ["table", "geography"]
    mirror_semantics = {"state": "state_postal"}

    def mirror_plan(self):
        from ..mirror import MirrorUnit
        for table in MIRROR_TABLES:
            yield MirrorUnit(partition={"table": table}, filters={"table": table}, split_by=["geography", "state"])

    def mirror_rows(self, unit):
        table, dataset = unit.filters["table"], MIRROR_DATASET
        year = latest_year(dataset)
        url = _dat_url(year, dataset, table)
        period = f"{year - 4}-{year}"
        names = self._all_names(year, dataset)
        labels = self._all_labels(year, dataset).get(table, {})
        by_sumlev = {sl: (geo, nested) for geo, (sl, nested) in GEOGRAPHIES.items()}

        def rows():
            # cache_allowed=False: each table file is read once per ingest; don't keep GBs of .dat files around.
            with http.download(url, cache_allowed=False) as path, http.open_text(path) as fh:
                reader = csv.reader(fh, delimiter="|")
                header = [h.strip() for h in next(reader, [])]
                require(header[:1] == ["GEO_ID"] and len(header) > 1, f"{url}: unexpected header {header[:5]}")
                cols = header[1:]
                for vals in reader:
                    g = vals[0]
                    hit = by_sumlev.get(g[:3])
                    if hit is None or g[5:7] != "00":
                        continue  # not a mirrored summary level, or a geographic component
                    geo, nested = hit
                    rec = {"table": table, "geography": geo,
                           "state": FIPS_STATE.get(g.split("US", 1)[-1][:2]) if nested else None,
                           "GEO_ID": g, "NAME": names.get(g)}
                    for k, v in zip(cols, vals[1:]):
                        rec[k] = _clean(v)
                    yield rec

        notes = [f"ACS 5-year {period} estimates (table-based summary file). Margins of error are 90% confidence.",
                 "Census 'jam values' (e.g. -666666666 = estimate not computable) were converted to null.",
                 "Mirror columns table/geography/state are partition keys (filter table and geography); state "
                 "(postal code) is set only for state-nested geographies.",
                 "The mirror covers the latest 5-year release and a curated table list (metadata.mirror_scope); other "
                 "tables, 1-year data and older releases: use the local odc-server, which fetches from the publisher."]
        meta = {"variable_labels": labels,
                "release": {"dataset": dataset, "year": year, "period": period,
                            "dollars": f"inflation-adjusted {year} dollars (dollar-valued tables)"},
                "mirror_scope": {"tables": list(MIRROR_TABLES), "dataset": dataset,
                                 "how_to_widen": "add table ids to MIRROR_TABLES in src/odc/adapters/census_acs_summary_file.py"}}
        return rows(), [url, _doc_url(year, dataset, "geos"), _doc_url(year, dataset, "shells")], notes, meta

    _names_cache: dict = {}
    _labels_cache: dict = {}

    def _all_names(self, year: int, dataset: str) -> dict[str, str]:
        """GEO_ID -> NAME for every whole-area geography in GEOGRAPHIES; loaded once per (year, dataset)."""
        key = (year, dataset)
        if key not in self._names_cache:
            self._names_cache.clear()  # keep one release in memory at a time
            sumlevs = {sl for sl, _ in GEOGRAPHIES.values()}
            out: dict[str, str] = {}
            with http.download(_doc_url(year, dataset, "geos"), cache_allowed=True, max_age_s=60 * 86400) as path, \
                    http.open_text(path, encoding="latin-1") as fh:
                for r in csv.DictReader(fh, delimiter="|"):
                    g = r.get("GEO_ID") or ""
                    if g[:3] in sumlevs and g[5:7] == "00":
                        out[g] = r.get("NAME")
            require(len(out) > 1000, f"Geos file for {dataset} {year} yielded only {len(out)} names")
            self._names_cache[key] = out
        return self._names_cache[key]

    def _all_labels(self, year: int, dataset: str) -> dict[str, dict[str, str]]:
        """table -> {<TABLE>_E### / _M###: label} from the table shells, for MIRROR_TABLES; once per (year, dataset)."""
        key = (year, dataset)
        if key not in self._labels_cache:
            wanted = set(MIRROR_TABLES)
            out: dict[str, dict[str, str]] = {}
            with http.download(_doc_url(year, dataset, "shells"), cache_allowed=True, max_age_s=60 * 86400) as path, \
                    http.open_text(path, encoding="latin-1") as fh:
                for r in csv.DictReader(fh, delimiter="|"):
                    t, uid = r.get("Table ID"), r.get("Unique ID", "")
                    if t in wanted and "_" in uid:
                        n = uid.split("_", 1)[1]
                        label = f"{r.get('Title', '')} — {r.get('Label', '')} (universe: {r.get('Universe', '')})"
                        out.setdefault(t, {})[f"{t}_E{n}"] = "Estimate: " + label
                        out[t][f"{t}_M{n}"] = "Margin of error (90%): " + label
            require(out, f"table shells for {dataset} {year} have no labels for the mirrored tables")
            self._labels_cache[key] = out
        return self._labels_cache[key]


ADAPTER = CensusAcsSummaryFile()
