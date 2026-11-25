"""Census Population Estimates Program (PEP): total population and components of change.
Catalog: catalog/census-pep.yaml

Layout on www2.census.gov (2020s decade; one directory per vintage, each vintage revises every year back to 2020):
  /programs-surveys/popest/datasets/2020-<V>/counties/totals/co-est<V>-alldata.csv   (states + counties, SUMLEV 040/050)
  /programs-surveys/popest/datasets/2020-<V>/state/totals/NST-EST<V>-ALLDATA.csv     (nation, regions, divisions,
                                                                                       states incl. Puerto Rico)
File-name case varies by vintage (NST-EST2021-alldata.csv vs NST-EST2022-ALLDATA.csv), so the adapter resolves the
name from the directory listing. Files are latin-1 encoded (e.g. "Do\\xf1a Ana County"). Columns are wide:
<MEASURE><YEAR>, e.g. POPESTIMATE2024, BIRTHS2024, NETMIG2024, RBIRTH2024 (rate per 1,000). The state file spells
the numeric change NPOPCHG_<YEAR>; the adapter renames it to NPOPCHG<YEAR> to match the county file.
File layouts: /programs-surveys/popest/technical-documentation/file-layouts/2020-<V>/ (PDF).
"""

from __future__ import annotations

import re

from .. import http
from ..http import SourceError
from ._common import scan_csv, state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

ROOT = "https://www2.census.gov/programs-surveys/popest/datasets/"
FIRST_VINTAGE = 2021  # first 2020-based vintage with the 2020-<V> directory layout

SUMLEV = {"nation": "010", "region": "020", "division": "030", "state": "040", "county": "050"}
ID_COLS = ["SUMLEV", "REGION", "DIVISION", "STATE", "COUNTY", "GEOID", "NAME"]

_latest: dict[str, int] = {}
_files: dict[tuple[int, str], str] = {}


def _listing(url: str) -> str:
    return http.get_text(url)


def vintages() -> list[int]:
    html = _listing(ROOT)
    vs = sorted({int(v) for v in re.findall(r'href="2020-(20\d\d)/"', html)})
    require(bool(vs), f"no 2020-<vintage>/ directories found in {ROOT}")
    return vs


def latest_vintage() -> int:
    if "v" not in _latest:
        _latest["v"] = max(vintages())
    return _latest["v"]


def file_url(vintage: int, kind: str) -> str:
    """kind: 'county' or 'state'. Resolve the exact (case-varying) file name from the directory listing."""
    key = (vintage, kind)
    if key in _files:
        return _files[key]
    sub, pat = (("counties/totals/", rf"co-est{vintage}-alldata\.csv") if kind == "county"
                else ("state/totals/", rf"nst-est{vintage}-alldata\.csv"))
    d = f"{ROOT}2020-{vintage}/{sub}"
    try:
        html = _listing(d)
    except SourceError as e:
        if e.status == 404:
            raise FilterError(f"vintage {vintage} not found at {d}; vintages available: {vintages()}") from None
        raise
    m = re.search(rf'href="({pat})"', html, re.I)
    require(m is not None, f"{d}: no file matching /{pat}/i in directory listing")
    _files[key] = d + m.group(1)
    return _files[key]


def _num(v: str | None):
    if v is None:
        return None
    v = v.strip()
    if v == "":
        return None
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


class CensusPep(SourceAdapter):
    source_id = "census-pep"
    version = "1.0.0"
    usage = ("One row per area for one vintage, with wide columns <MEASURE><YEAR> for every year 2020..vintage: "
             "POPESTIMATE (July 1 resident population), NPOPCHG, BIRTHS, DEATHS, NATURALCHG, INTERNATIONALMIG, "
             "DOMESTICMIG, NETMIG, RESIDUAL, GQESTIMATES, and rates per 1,000 (RBIRTH, RDEATH, RNETMIG, ...). "
             "Use `year` to keep only one year's columns and `variables` to pick measures. Each new vintage revises "
             "all earlier years, so always compare years within one vintage. Default vintage is the latest published.")
    filters = [
        FilterSpec("geography", "string", "Summary level: nation, region, division, state (incl. Puerto Rico) or county.",
                   enum=list(SUMLEV), default="county", example="county"),
        FilterSpec("vintage", "integer", f"Estimates vintage (year of the latest estimate), {FIRST_VINTAGE} or later. Default: latest available.",
                   example=2024),
        FilterSpec("state", "string", "Restrict state/county rows to one state (postal code or FIPS).", example="TX"),
        FilterSpec("county_fips", "string_list", "5-digit county GEOIDs (state+county FIPS), e.g. ['48201'] (geography=county only).",
                   example=["48201"]),
        FilterSpec("year", "integer", "Keep only measure columns for this year (2020..vintage). Default: all years.", example=2024),
        FilterSpec("variables", "string_list",
                   "Measure prefixes or exact columns to keep, e.g. ['POPESTIMATE','NETMIG'] or ['POPESTIMATE2024']. Default: all.",
                   example=["POPESTIMATE", "BIRTHS", "DEATHS", "NETMIG"]),
    ]
    contract = [
        ContractCase(
            name="state_totals_v2024",
            filters={"geography": "state", "vintage": 2024, "year": 2020},
            min_rows=52, max_rows=52,
            required_columns=["GEOID", "NAME", "POPESTIMATE2020", "BIRTHS2020", "NETMIG2020"],
            checks=[Check("POPESTIMATE2020", numeric=True, min=500_000, max=40_000_000),
                    Check("GEOID", regex=r"\d\d")],
            limit=100,
        ),
        ContractCase(
            name="delaware_counties_v2024",
            filters={"geography": "county", "state": "DE", "vintage": 2024, "variables": ["POPESTIMATE", "DEATHS"]},
            min_rows=3, max_rows=3,
            required_columns=["GEOID", "NAME", "POPESTIMATE2024", "DEATHS2023"],
            checks=[Check("GEOID", one_of=["10001", "10003", "10005"]),
                    Check("POPESTIMATE2024", numeric=True, min=150_000, max=650_000)],
            limit=10,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        geo = f.get("geography", "county")
        vintage = f.get("vintage") or latest_vintage()
        if vintage < FIRST_VINTAGE:
            raise FilterError(f"vintage must be {FIRST_VINTAGE} or later (2010s vintages use a different layout and are not served)")
        year = f.get("year")
        if year is not None and not (2020 <= year <= vintage):
            raise FilterError(f"year must be between 2020 and the vintage ({vintage})")
        st = state_fips(f["state"]) if f.get("state") else None
        if st and geo not in ("state", "county"):
            raise FilterError("the state filter applies only to geography 'state' or 'county'")
        counties = set(f.get("county_fips") or [])
        if counties:
            if geo != "county":
                raise FilterError("county_fips requires geography='county'")
            bad = [c for c in counties if not re.fullmatch(r"\d{5}", c)]
            if bad:
                raise FilterError(f"county_fips must be 5-digit state+county FIPS codes, got {bad}")
        sumlev = SUMLEV[geo]
        url = file_url(vintage, "county" if geo == "county" else "state")

        def keep(row: dict) -> bool:
            if row.get("SUMLEV") != sumlev:
                return False
            if st and row.get("STATE") != st:
                return False
            if counties and row.get("STATE", "") + row.get("COUNTY", "") not in counties:
                return False
            return True

        rows, matched = scan_csv(url, cache_allowed=cache_allowed, predicate=keep, limit=limit,
                                 encoding="latin-1", max_age_s=30 * 86400)
        if rows:
            require("SUMLEV" in rows[0] and f"POPESTIMATE{vintage}" in rows[0],
                    f"{url}: expected SUMLEV and POPESTIMATE{vintage} columns, got {list(rows[0])[:12]}")
        wanted = f.get("variables") or []
        out = []
        for r in rows:
            name = r.get("CTYNAME") if geo == "county" else r.get("NAME")
            stc = r.get("STATE")
            rec = {
                "SUMLEV": r.get("SUMLEV"), "REGION": r.get("REGION"), "DIVISION": r.get("DIVISION"),
                "STATE": stc, "COUNTY": r.get("COUNTY") if geo == "county" else None,
                "GEOID": (stc + r.get("COUNTY", "")) if geo == "county" else (stc if geo == "state" else None),
                "NAME": name,
            }
            if geo == "county":
                rec["STNAME"] = r.get("STNAME")
            for k, v in r.items():
                if k in ("SUMLEV", "REGION", "DIVISION", "STATE", "COUNTY", "STNAME", "CTYNAME", "NAME"):
                    continue
                k2 = re.sub(r"^NPOPCHG_(\d{4})$", r"NPOPCHG\1", k)
                if year is not None and not k2.endswith(str(year)):
                    continue
                if wanted and not any(k2 == w or re.fullmatch(re.escape(w) + r"\d{4}", k2) for w in wanted):
                    continue
                rec[k2] = _num(v)
            out.append(rec)
        notes = [f"Vintage {vintage} estimates (July 1 reference dates, 2020-{vintage}); file {url}.",
                 "Component columns for 2020 cover April 1-June 30, 2020 only; later years cover July 1-June 30.",
                 "Rate columns (R*) are per 1,000 average population and start in 2021."]
        if geo == "state":
            notes.append("State rows come from the national/state file and include Puerto Rico (STATE 72).")
        return FetchResult(out, [url], notes, total_available=matched, metadata={"vintage": vintage, "geography": geo})


    mirror_partition_keys = ["geography", "STATE"]
    mirror_semantics = {"STATE": "state_fips", "GEOID": "county_fips"}

    def mirror_plan(self):
        from ..mirror import MirrorUnit
        for geo in SUMLEV:
            yield MirrorUnit(partition={"geography": geo}, filters={"geography": geo}, split_by=["STATE"])

    def mirror_rows(self, unit):
        rows, urls, notes, meta = super().mirror_rows(unit)
        return [{"geography": unit.partition["geography"], **r} for r in rows], urls, notes, meta


ADAPTER = CensusPep()
