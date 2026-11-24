"""BEA Regional Economic Accounts, keyless bulk ZIP/CSV files. Catalog: catalog/bea-regional.yaml

The BEA API needs a UserID key (not usable here), but the same regional tables are published as ZIPs at
  https://apps.bea.gov/regional/zip/<NAME>.zip     (index page: https://apps.bea.gov/regional/downloadzip.htm)
* County/metro tables (CAINC1, CAINC4, CAINC30, CAGDP1, CAGDP2, CAGDP9, ...): one zip per table.
* State tables are grouped: SAGDP.zip (SAGDP1..SAGDP11), SAINC.zip (SAINC1..SAINC91), SQINC.zip, SQGDP.zip,
  SAPCE.zip. An unknown name returns a small HTML page with HTTP 200 (not a zip) -> FilterError.
Each zip holds <TABLE>__ALL_AREAS_<first>_<last>.csv (+ per-state files, definition XML, footnotes).
CSV: GeoFIPS,GeoName,Region,TableName,LineCode,IndustryClassification,Description,Unit,<year or YYYY:Qn>...
Cells are written as ` "01000"` (space before the quote) -> csv skipinitialspace. Non-numeric cell codes:
(NA) not available, (D) suppressed to avoid disclosure, (NM) not meaningful, (L) < $50,000 or < 0.5 jobs,
(T) included in higher-level totals. Trailer lines ("Note: ...", "Last updated: ...") follow the data rows.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile

from .. import http
from ..http import SourceError
from ._common import state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

BASE = "https://apps.bea.gov/regional/zip"
INDEX = "https://apps.bea.gov/regional/downloadzip.htm"
GEO_LEVELS = ["us", "region", "state", "county"]
ID_COLS = ["GeoFIPS", "GeoName", "Region", "TableName", "LineCode", "IndustryClassification", "Description", "Unit"]
_TABLE_RE = re.compile(r"^(CA|SA|SQ|MA|PA)[A-Z]+\d+[A-Z]?$")


def zip_name(table: str) -> str:
    if table.startswith("CA"):
        return table
    return re.match(r"[A-Z]+", table).group(0)  # SAGDP9 -> SAGDP


def geo_level(fips: str) -> str:
    if fips == "00000":
        return "us"
    if fips[:2] >= "91" and fips[2:] == "000":
        return "region"
    if fips[2:] == "000":
        return "state"
    return "county"


def _num(v: str):
    v = v.strip()
    try:
        f = float(v)
    except ValueError:
        return None, v or None
    return (int(f) if f.is_integer() and "." not in v else f), None


def _assert_de_counties(rows: list[dict]) -> None:
    names = {r["GeoName"] for r in rows}
    assert any("Sussex" in n for n in names), f"Sussex County missing from {names}"


class BeaRegional(SourceAdapter):
    source_id = "bea-regional"
    version = "1.0.0"
    usage = ("Pick a BEA regional table (e.g. CAINC1 = county personal income/population/per-capita income, "
             "CAGDP1/CAGDP2 = county GDP total/by industry, SAGDP1/SAGDP2 = state GDP, SAINC1 = state personal "
             "income, SQINC1/SQGDP1 = state quarterly). Rows are long: one per area x line x period, with `value` "
             "and `value_note` for BEA codes like (D) suppressed. Filter by state, geo_level, line_code and years; "
             "LineCode meanings are in `Description` and `Unit` (e.g. thousands of dollars).")
    filters = [
        FilterSpec("table", "string", "BEA regional table id, e.g. 'CAINC1', 'CAGDP2', 'SAGDP1', 'SAINC1', 'SQINC1'.",
                   required=True, example="CAINC1"),
        FilterSpec("state", "string", "Postal code or FIPS; keeps that state and its counties.", example="DE"),
        FilterSpec("geo_fips", "string_list", "Exact 5-digit BEA GeoFIPS codes, e.g. ['10003'] or ['00000'] for the US."),
        FilterSpec("geo_level", "string", "Keep only one level: us, region (BEA regions 91000-98000), state, county "
                   "(county tables: counties and BEA county combinations).", enum=GEO_LEVELS),
        FilterSpec("line_code", "string_list", "Table line(s), e.g. ['1'] (CAINC1 line 1 = personal income; 3 = per capita).",
                   example=["1"]),
        FilterSpec("year", "integer", "Single year (all quarters of that year for SQ tables)."),
        FilterSpec("start_year", "integer", "First year to return."),
        FilterSpec("end_year", "integer", "Last year to return."),
    ]
    contract = [
        ContractCase(
            name="delaware_county_income_2019",
            filters={"table": "CAINC1", "state": "DE", "geo_level": "county", "line_code": ["1", "2", "3"], "year": 2019},
            min_rows=9, max_rows=9,
            required_columns=["GeoFIPS", "GeoName", "LineCode", "Description", "Unit", "period", "value"],
            checks=[Check("GeoFIPS", regex=r"10\d{3}"), Check("value", numeric=True, min=10000, max=60_000_000)],
            custom=_assert_de_counties,
        ),
        ContractCase(
            name="state_gdp_2019",
            filters={"table": "SAGDP1", "geo_level": "state", "line_code": ["3"], "year": 2019},
            min_rows=51, max_rows=52,
            required_columns=["GeoFIPS", "GeoName", "Description", "Unit", "period", "value"],
            checks=[Check("value", numeric=True, min=20000, max=4_000_000), Check("GeoFIPS", regex=r"\d\d000")],
            limit=100,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        table = f["table"].strip().upper()
        if not _TABLE_RE.match(table):
            raise FilterError("table must look like CAINC1, CAGDP2, SAGDP1, SAINC4, SQINC1 (see " + INDEX + ")")
        st = state_fips(f["state"]) if f.get("state") else None
        geo_ids = {g.strip().zfill(5) for g in (f.get("geo_fips") or [])}
        level = f.get("geo_level")
        lines = {str(x).strip() for x in (f.get("line_code") or [])}
        y0 = f.get("start_year", f.get("year"))
        y1 = f.get("end_year", f.get("year"))
        url = f"{BASE}/{zip_name(table)}.zip"
        out: list[dict] = []
        matched = 0
        suppressed = 0
        updated = None
        with http.download(url, cache_allowed=cache_allowed, max_age_s=7 * 86400) as path:
            with open(path, "rb") as fh:
                is_zip = fh.read(4) == b"PK\x03\x04"
            if not is_zip:
                path.unlink(missing_ok=True)  # don't let a cached HTML error page shadow the table for 7 days
                raise FilterError(f"BEA has no regional zip for table {table} ({url}); check the table id on {INDEX}")
            zf = zipfile.ZipFile(path)
            members = [n for n in zf.namelist() if n.startswith(f"{table}__ALL_AREAS_") and n.endswith(".csv")]
            if not members:
                avail = sorted({n.split("__", 1)[0] for n in zf.namelist() if "__ALL_AREAS_" in n})
                raise FilterError(f"table {table} not in {url}; tables there: {avail}")
            with io.TextIOWrapper(zf.open(members[0]), encoding="latin-1", newline="") as text:
                reader = csv.reader(text, skipinitialspace=True)
                header = [h.strip() for h in next(reader)]
                require(header[:8] == ID_COLS, f"{url}:{members[0]}: unexpected header {header[:10]}")
                periods = header[8:]
                keep_idx = [i for i, p in enumerate(periods, start=8)
                            if (y0 is None or int(p[:4]) >= y0) and (y1 is None or int(p[:4]) <= y1)]
                for row in reader:
                    if len(row) < 9:
                        if row and row[0].startswith("Last updated"):
                            updated = row[0]
                        continue
                    rec = {k: row[i].strip() for i, k in enumerate(ID_COLS)}
                    g = rec["GeoFIPS"]
                    if geo_ids and g not in geo_ids:
                        continue
                    if st and g[:2] != st:
                        continue
                    if level and geo_level(g) != level:
                        continue
                    if lines and rec["LineCode"] not in lines:
                        continue
                    for i in keep_idx:
                        matched += 1
                        if len(out) >= limit:
                            continue
                        val, note = _num(row[i]) if i < len(row) else (None, "(missing)")
                        if note:
                            suppressed += 1
                        out.append({**rec, "Region": rec["Region"] or None, "period": periods[i - 8],
                                    "value": val, "value_note": note})
        notes = ["BEA cell codes ((D) suppressed, (NA) not available, (NM) not meaningful, (L) below display threshold, "
                 "(T) in higher totals) are returned as value=null with the code in value_note."]
        if suppressed:
            notes.append(f"{suppressed} returned cells are null with a BEA code.")
        if updated:
            notes.append(updated.strip())
        if matched == 0:
            notes.append("No rows matched: check state/geo_level (state tables have no counties) and line_code.")
        return FetchResult(out, [url], notes, total_available=matched,
                           metadata={"table": table, "file": members[0], "last_updated": updated})


ADAPTER = BeaRegional()
