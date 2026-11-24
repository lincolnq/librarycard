"""Census Small Area Income and Poverty Estimates (SAIPE). Catalog: catalog/census-saipe.yaml

Bulk files on www2.census.gov (fixed-width text; the same files are also published as .xls, which we don't read):
  /programs-surveys/saipe/datasets/<YEAR>/<YEAR>-state-and-county/est<YY>all.txt   (US, states, counties; ~850 KB)
  /programs-surveys/saipe/datasets/<YEAR>/<YEAR>-school-districts/ussd<YY>.txt       (all school districts; ~1.7 MB)
Record layouts (identical for 2010..2024 releases, checked 2026-11-24):
  /programs-surveys/saipe/technical-documentation/file-layouts/state-county/<YEAR>-estimate-layout.txt
  /programs-surveys/saipe/technical-documentation/file-layouts/school-district/<YEAR>-district-layout.txt
Missing values are published as "." (e.g. Kalawao County, HI) and become null. Files are latin-1 (district names
such as "La Ca\\xf1ada"). Output column names follow the Census SAIPE API variable names (SAEPOVALL_PT, ...).
"""

from __future__ import annotations

import datetime as dt
import re

from .. import http
from ..http import SourceError
from ._common import state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

ROOT = "https://www2.census.gov/programs-surveys/saipe/datasets/"
FIRST_YEAR = 2010  # earliest year whose fixed-width layout matches the one encoded below

# (name, start, end) 1-based inclusive positions from the <YEAR>-estimate-layout.txt
SC_LAYOUT = [
    ("STATE", 1, 2), ("COUNTY", 4, 6),
    ("SAEPOVALL_PT", 8, 15), ("SAEPOVALL_LB90", 17, 24), ("SAEPOVALL_UB90", 26, 33),
    ("SAEPOVRTALL_PT", 35, 38), ("SAEPOVRTALL_LB90", 40, 43), ("SAEPOVRTALL_UB90", 45, 48),
    ("SAEPOV0_17_PT", 50, 57), ("SAEPOV0_17_LB90", 59, 66), ("SAEPOV0_17_UB90", 68, 75),
    ("SAEPOVRT0_17_PT", 77, 80), ("SAEPOVRT0_17_LB90", 82, 85), ("SAEPOVRT0_17_UB90", 87, 90),
    ("SAEPOV5_17R_PT", 92, 99), ("SAEPOV5_17R_LB90", 101, 108), ("SAEPOV5_17R_UB90", 110, 117),
    ("SAEPOVRT5_17R_PT", 119, 122), ("SAEPOVRT5_17R_LB90", 124, 127), ("SAEPOVRT5_17R_UB90", 129, 132),
    ("SAEMHI_PT", 134, 139), ("SAEMHI_LB90", 141, 146), ("SAEMHI_UB90", 148, 153),
    ("SAEPOV0_4_PT", 155, 161), ("SAEPOV0_4_LB90", 163, 169), ("SAEPOV0_4_UB90", 171, 177),
    ("SAEPOVRT0_4_PT", 179, 182), ("SAEPOVRT0_4_LB90", 184, 187), ("SAEPOVRT0_4_UB90", 189, 192),
    ("NAME", 194, 238), ("STABREV", 240, 241),
]
SD_LAYOUT = [
    ("STATE", 1, 2), ("DISTRICT_ID", 4, 8), ("NAME", 10, 81),
    ("POP_TOTAL", 83, 90), ("POP_5_17", 92, 99), ("POV_5_17_RELATED", 101, 108),
]
TEXT_COLS = {"STATE", "COUNTY", "DISTRICT_ID", "NAME", "STABREV"}

_latest: dict[str, int] = {}


def _url(year: int, kind: str) -> str:
    yy = f"{year % 100:02d}"
    if kind == "school_district":
        return f"{ROOT}{year}/{year}-school-districts/ussd{yy}.txt"
    return f"{ROOT}{year}/{year}-state-and-county/est{yy}all.txt"


def latest_year() -> int:
    if "y" in _latest:
        return _latest["y"]
    years = sorted({int(y) for y in re.findall(r'href="(20\d\d)/"', http.get_text(ROOT))}, reverse=True)
    require(bool(years), f"no <YEAR>/ directories in {ROOT}")
    for y in years[:3]:
        try:
            http.head(_url(y, "county"))
            _latest["y"] = y
            return y
        except SourceError:
            continue
    raise SourceError(f"no est<YY>all.txt found for the latest years {years[:3]} under {ROOT}", kind="http")


def _val(name: str, raw: str):
    v = raw.strip()
    if name in TEXT_COLS:
        return v or None
    if v in ("", "."):
        return None
    try:
        return float(v) if "." in v else int(v)
    except ValueError:
        raise SourceError(f"unexpected value {raw!r} in column {name}", kind="parse") from None


def parse_line(line: str, layout: list[tuple[str, int, int]]) -> dict:
    return {n: _val(n, line[a - 1:b]) for n, a, b in layout}


class CensusSaipe(SourceAdapter):
    source_id = "census-saipe"
    version = "1.0.0"
    usage = ("geography=nation|state|county gives poverty counts and rates (all ages, 0-17, related children 5-17, "
             "and 0-4 for nation/state only) plus median household income, each with a 90% confidence interval "
             "(_LB90/_UB90); geography=school_district gives total population, relevant children 5-17 and related "
             "children 5-17 in poverty (no CIs). Filter with `state`, `county_fips` or `district_ids`. "
             "SAIPE are model-based estimates; compare years only with the CIs in mind.")
    filters = [
        FilterSpec("geography", "string", "nation, state, county or school_district.",
                   enum=["nation", "state", "county", "school_district"], default="county", example="county"),
        FilterSpec("year", "integer", f"Estimate year, {FIRST_YEAR} or later. Default: latest released.", example=2023),
        FilterSpec("state", "string", "Restrict to one state (postal code or FIPS).", example="NM"),
        FilterSpec("county_fips", "string_list", "5-digit county GEOIDs, e.g. ['35013'] (geography=county).", example=["35013"]),
        FilterSpec("district_ids", "string_list",
                   "7-digit school-district GEOIDs = state FIPS + 5-digit district (NCES LEA) id, e.g. ['0100190'].",
                   example=["0100190"]),
    ]
    contract = [
        ContractCase(
            name="state_poverty_2022",
            filters={"geography": "state", "year": 2022},
            min_rows=51, max_rows=51,
            required_columns=["GEOID", "NAME", "SAEPOVRTALL_PT", "SAEMHI_PT", "SAEMHI_LB90"],
            checks=[Check("SAEPOVRTALL_PT", numeric=True, min=4, max=25),
                    Check("SAEMHI_PT", numeric=True, min=40000, max=120000),
                    Check("GEOID", regex=r"\d\d")],
            limit=100,
        ),
        ContractCase(
            name="delaware_school_districts_2022",
            filters={"geography": "school_district", "state": "DE", "year": 2022},
            min_rows=15,
            required_columns=["GEOID", "NAME", "POP_TOTAL", "POP_5_17", "POV_5_17_RELATED"],
            checks=[Check("POV_5_17_RELATED", numeric=True, min=0, max=50000), Check("GEOID", regex=r"10\d{5}")],
            limit=100,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        geo = f.get("geography", "county")
        year = f.get("year") or latest_year()
        if year < FIRST_YEAR or year > dt.date.today().year:
            raise FilterError(f"year must be between {FIRST_YEAR} and the latest release")
        st = state_fips(f["state"]) if f.get("state") else None
        counties = set(f.get("county_fips") or [])
        districts = set(f.get("district_ids") or [])
        if counties and geo != "county":
            raise FilterError("county_fips requires geography='county'")
        if districts and geo != "school_district":
            raise FilterError("district_ids requires geography='school_district'")
        if st and geo == "nation":
            raise FilterError("drop the state filter for geography='nation'")
        kind = "school_district" if geo == "school_district" else "county"
        layout = SD_LAYOUT if kind == "school_district" else SC_LAYOUT
        url = _url(year, kind)
        out: list[dict] = []
        matched = 0
        try:
            with http.download(url, cache_allowed=cache_allowed, max_age_s=30 * 86400) as path:
                with http.open_text(path, encoding="latin-1") as fh:
                    for n, line in enumerate(fh):
                        line = line.rstrip("\r\n")
                        if not line.strip():
                            continue
                        if n == 0:
                            need = 241 if kind == "county" else 108
                            require(len(line) >= need and line[:2].isdigit(),
                                    f"{url}: first record is {len(line)} chars / doesn't start with a FIPS code; layout changed?",
                                    kind="parse")
                        stc = line[0:2]
                        if kind == "county":
                            cty = line[3:6].strip()
                            level = "nation" if stc == "00" else ("state" if cty == "0" else "county")
                            if level != geo:
                                continue
                            geoid = None if level == "nation" else (stc if level == "state" else stc + cty.zfill(3))
                            if st and stc != st:
                                continue
                            if counties and geoid not in counties:
                                continue
                        else:
                            geoid = stc + line[3:8]
                            if st and stc != st:
                                continue
                            if districts and geoid not in districts:
                                continue
                        matched += 1
                        if len(out) < limit:
                            rec = parse_line(line, layout)
                            if kind == "county":
                                rec["COUNTY"] = rec["COUNTY"].zfill(3) if rec.get("COUNTY") and geo == "county" else None
                            out.append({"GEOID": geoid, "YEAR": year, **rec})
        except SourceError as e:
            if e.status == 404:
                raise FilterError(f"no SAIPE {kind.replace('_', ' ')} file for {year} ({url})") from None
            raise
        notes = [f"SAIPE {year} estimates from {url} (fixed-width; parsed with the published record layout).",
                 "Values published as '.' (not available) were converted to null.",
                 "_LB90/_UB90 are bounds of the 90% confidence interval; rates (SAEPOVRT*) are percentages."]
        if geo == "county":
            notes.append("The under-5 poverty columns (SAEPOV0_4_*) are published only for the nation and states; null for counties.")
        if geo == "school_district":
            notes.append("POV_5_17_RELATED counts children 5-17 related to the householder in poverty; divide by POP_5_17 for a rate.")
        return FetchResult(out, [url], notes, total_available=matched, metadata={"year": year, "geography": geo})


ADAPTER = CensusSaipe()
