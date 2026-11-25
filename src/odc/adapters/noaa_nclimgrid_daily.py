"""NOAA nClimGrid-Daily area averages from the public AWS bucket. Catalog: catalog/noaa-nclimgrid-daily.yaml

Bucket: s3://noaa-nclimgrid-daily-pds (anonymous HTTPS: https://noaa-nclimgrid-daily-pds.s3.amazonaws.com/)
Files:  access/averages/<YYYY>/<var>-<YYYYMM>-<cty|ste>-<scaled|prelim>.csv
        No header. Columns: region_type, region_code, region_name, year, month, variable, day1..day31
        region_code uses NCEI state numbering (NOT FIPS) in its first two digits; we convert to FIPS
        using doc/us-state-codes_ncei-to-fips.csv from the same bucket.
"""

from __future__ import annotations

import csv
import io

from .. import http
from ..http import SourceError
from ._common import state_abbr
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter

BUCKET = "https://noaa-nclimgrid-daily-pds.s3.amazonaws.com"
VARIABLES = {"tmax": "°C", "tmin": "°C", "tavg": "°C", "prcp": "mm"}
LEVELS = {"county": "cty", "state": "ste"}
MISSING = "-999.99"

_ncei_to_fips: dict[str, tuple[str, str]] | None = None


def ncei_to_fips() -> dict[str, tuple[str, str]]:
    """NCEI 2-digit state code -> (FIPS, postal)."""
    global _ncei_to_fips
    if _ncei_to_fips is None:
        txt = http.get_text(f"{BUCKET}/doc/us-state-codes_ncei-to-fips.csv")
        rows = list(csv.DictReader(io.StringIO(txt.lstrip("﻿"))))
        _ncei_to_fips = {r["NCEI_code"].zfill(2): (r["FIPS_code"].zfill(2), r["postal_code"]) for r in rows}
    return _ncei_to_fips


def _assert_extreme_heat(rows: list[dict]) -> None:
    # July 2023 Phoenix had a record run of 110°F+ (43.3°C+) days; the county average max must show it.
    assert any(r["value"] >= 43 for r in rows), f"max tmax {max(r['value'] for r in rows)} < 43°C"


class NoaaNclimgridDaily(SourceAdapter):
    source_id = "noaa-nclimgrid-daily"
    version = "1.0.0"
    usage = ("Daily county- or state-average temperature (°C) and precipitation (mm) for one variable and one "
             "calendar month per call. Rows are long format: one row per area per day. 'scaled' files are final; "
             "the most recent ~2 months exist only as 'prelim' and are revised later.")
    filters = [
        FilterSpec("variable", "string", "tmax, tmin, tavg (°C) or prcp (mm).", required=True, enum=sorted(VARIABLES), example="tmax"),
        FilterSpec("year", "integer", "Year, 1951 or later.", required=True, example=2024),
        FilterSpec("month", "integer", "Month 1-12.", required=True, example=7),
        FilterSpec("level", "string", "Area type.", enum=sorted(LEVELS), default="county"),
        FilterSpec("state", "string", "Postal code or FIPS; restricts to one state.", example="AZ"),
        FilterSpec("county_fips", "string", "5-digit county FIPS (state+county), e.g. '04013' (Maricopa)."),
        FilterSpec("day", "integer", "Single day of month (1-31)."),
        FilterSpec("version", "string", "'scaled' (final, default; falls back to prelim if final not yet published) or 'prelim'.",
                   enum=["scaled", "prelim"], default="scaled"),
    ]
    contract = [
        ContractCase(
            name="maricopa_july_2023_heat",
            filters={"variable": "tmax", "year": 2023, "month": 7, "county_fips": "04013"},
            min_rows=31, max_rows=31,
            required_columns=["fips", "region_name", "date", "variable", "value", "unit"],
            checks=[Check("value", numeric=True, min=35, max=50), Check("fips", one_of=["04013"]), Check("state", one_of=["AZ"])],
            custom=lambda rows: _assert_extreme_heat(rows),
        ),
        ContractCase(
            name="state_precip_one_day",
            filters={"variable": "prcp", "year": 2022, "month": 1, "day": 15, "level": "state"},
            min_rows=48, max_rows=50,
            required_columns=["fips", "date", "value"],
            checks=[Check("value", numeric=True, min=0, max=300), Check("fips", regex=r"\d\d")],
            limit=60,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        var, year, month = f["variable"], f["year"], f["month"]
        if not 1 <= month <= 12:
            raise FilterError("month must be 1-12")
        if year < 1951:
            raise FilterError("nClimGrid-Daily starts in 1951")
        lvl = LEVELS[f.get("level", "county")]
        want_state = state_abbr(f["state"]) if f.get("state") else None
        want_county = f.get("county_fips")
        if want_county and (len(want_county) != 5 or not want_county.isdigit()):
            raise FilterError("county_fips must be 5 digits, e.g. '04013'")
        if want_county and lvl != "cty":
            raise FilterError("county_fips requires level='county'")
        day = f.get("day")
        mapping = ncei_to_fips()
        versions = [f.get("version", "scaled")]
        if versions[0] == "scaled":
            versions.append("prelim")
        text, url, used = None, None, None
        for v in versions:
            url = f"{BUCKET}/access/averages/{year}/{var}-{year}{month:02d}-{lvl}-{v}.csv"
            try:
                text = http.get_text(url, retries=1)
                used = v
                break
            except SourceError as e:
                if e.status not in (403, 404):
                    raise
        if text is None:
            raise FilterError(f"no {var} file for {year}-{month:02d} ({lvl}); data may not be published yet")
        out: list[dict] = []
        matched = 0
        unit = VARIABLES[var]
        for rec in csv.reader(io.StringIO(text)):
            if len(rec) < 7:
                continue
            region_type, code, name = rec[0].strip(), rec[1].strip(), rec[2].strip()
            ncei_state = code[:2]
            fips_state, postal = mapping.get(ncei_state, (None, None))
            if postal is None:
                continue  # regions without a state mapping (e.g. CONUS aggregate) are skipped
            fips = fips_state + code[2:] if lvl == "cty" else fips_state
            if want_state and postal != want_state:
                continue
            if want_county and fips != want_county:
                continue
            for d, raw in enumerate(rec[6:], start=1):
                if day and d != day:
                    continue
                raw = raw.strip()
                if raw == MISSING or raw == "":
                    continue  # days that don't exist in this month
                matched += 1
                if len(out) < limit:
                    out.append({
                        "level": "county" if lvl == "cty" else "state",
                        "fips": fips, "ncei_code": code, "state": postal, "region_name": name,
                        "date": f"{year}-{month:02d}-{d:02d}", "variable": var, "value": float(raw), "unit": unit,
                    })
        if matched == 0 and (want_county or want_state):
            raise FilterError("no rows matched; check state/county_fips (county_fips must be a real 5-digit FIPS)")
        notes = [f"Using '{used}' file." + (" Preliminary values are revised when the scaled (final) file is published." if used == "prelim" else ""),
                 "Area averages of a 5 km (nClimGrid) grid; not station observations."]
        return FetchResult(out, [url, f"{BUCKET}/doc/us-state-codes_ncei-to-fips.csv"], notes, total_available=matched)


ADAPTER = NoaaNclimgridDaily()
