"""CDC/ATSDR Social Vulnerability Index (SVI) CSV files. Catalog: catalog/cdc-svi.yaml

File layout on svi.cdc.gov (same pattern the official download page's loadXML.js builds):
  https://svi.cdc.gov/Documents/Data/<YEAR>/csv/states/SVI_<YEAR>_US.csv                 US-ranked tracts   (~61 MB, 2022)
  https://svi.cdc.gov/Documents/Data/<YEAR>/csv/states_counties/SVI_<YEAR>_US_county.csv  US-ranked counties (~2.3 MB)
  https://svi.cdc.gov/Documents/Data/<YEAR>/csv/zcta/SVI_<YEAR>_US_ZCTA.csv               US-ranked ZCTAs (2022 only, ~25 MB)
  .../states/<StateName>.csv, .../states_counties/<StateName>_county.csv, .../zcta/<StateName>_ZCTA.csv
                                                                                          state-ranked versions
<StateName> is the state name with spaces removed (e.g. NewHampshire, DistrictofColumbia).
Variables differ by release (e.g. E_POV in 2018 vs E_POV150 in 2020+); columns are passed through.
-999 / -999.0 means "unavailable / not calculable" and is converted to null.
"""

from __future__ import annotations

from ..http import SourceError
from ._common import scan_csv, state_abbr
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

BASE = "https://svi.cdc.gov/Documents/Data"
YEARS = [2018, 2020, 2022]
LATEST = max(YEARS)
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "DistrictofColumbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "NewHampshire", "NJ": "NewJersey", "NM": "NewMexico",
    "NY": "NewYork", "NC": "NorthCarolina", "ND": "NorthDakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "RhodeIsland", "SC": "SouthCarolina", "SD": "SouthDakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "WestVirginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "PuertoRico",
}
SENTINELS = {"-999", "-999.0", "-999.00"}
NUMERIC_PREFIXES = ("E_", "M_", "EP_", "MP_", "EPL_", "SPL_", "RPL_", "F_")
ID_COLUMNS = ("FIPS", "ST_ABBR", "LOCATION")


def file_url(year: int, geography: str, ranking: str, state: str | None) -> str:
    territory = f"SVI_{year}_US" if ranking == "us" else STATE_NAMES[state_abbr(state)]
    if geography == "tract":
        return f"{BASE}/{year}/csv/states/{territory}.csv"
    if geography == "county":
        return f"{BASE}/{year}/csv/states_counties/{territory}_county.csv"
    return f"{BASE}/{year}/csv/zcta/{territory}_ZCTA.csv"


def _value(k: str, v):
    if v is None:
        return None
    v = v.strip()
    if v == "" or v in SENTINELS:
        return None
    if k == "AREA_SQMI" or k.startswith(NUMERIC_PREFIXES) or k == "E_DAYPOP":
        try:
            f = float(v)
        except ValueError:
            return v
        return int(f) if f.is_integer() and "." not in v else f
    return v


def _check_county_ranks(rows: list[dict]) -> None:
    ranks = [r["RPL_THEMES"] for r in rows if r.get("RPL_THEMES") is not None]
    assert len(ranks) >= 3000, f"only {len(ranks)} counties have RPL_THEMES"
    assert min(ranks) <= 0.01 and max(ranks) >= 0.99, "US-ranked percentiles should span ~0..1"


class CdcSvi(SourceAdapter):
    source_id = "cdc-svi"
    version = "1.0.0"
    usage = ("One row per county, census tract or ZCTA (2022 only) with ~150 columns: E_* estimates and M_* margins "
             "of error (ACS 5-year), EP_* percentages, EPL_* variable percentile ranks, RPL_THEME1-4 theme ranks and "
             "RPL_THEMES (overall SVI, 0-1, higher = more vulnerable), F_* flags. `ranking` 'us' ranks against the whole "
             "US (use for multi-state work); 'state' downloads the state-ranked file (ranks within the state; needs "
             "`state`). Use `variables` to trim columns. -999 is returned as null.")
    filters = [
        FilterSpec("geography", "string", "county, tract (census tract) or zcta (2022 only).",
                   enum=["county", "tract", "zcta"], default="county", example="county"),
        FilterSpec("year", "integer", f"SVI release year (ACS 5-year period ending that year). Default {LATEST}.",
                   enum=YEARS, default=LATEST),
        FilterSpec("ranking", "string", "'us' = percentiles ranked nationally (default); 'state' = ranked within the state (requires state).",
                   enum=["us", "state"], default="us"),
        FilterSpec("state", "string", "State postal code or FIPS; restricts rows (and picks the file when ranking='state').", example="DE"),
        FilterSpec("fips", "string_list", "Exact FIPS ids: 5-digit county, 11-digit tract or 5-digit ZCTA.", example=["10001"]),
        FilterSpec("variables", "string_list", "Columns to return besides FIPS/ST_ABBR/LOCATION, e.g. ['RPL_THEMES','EP_POV150'].",
                   example=["RPL_THEMES", "RPL_THEME1", "EP_POV150"]),
    ]
    contract = [
        ContractCase(
            name="us_counties_2022",
            filters={"geography": "county", "year": 2022, "variables": ["RPL_THEMES", "RPL_THEME1", "E_TOTPOP", "EP_POV150"]},
            min_rows=3100, max_rows=3200,
            required_columns=["FIPS", "ST_ABBR", "LOCATION", "RPL_THEMES", "E_TOTPOP"],
            checks=[Check("RPL_THEMES", numeric=True, min=0, max=1), Check("EP_POV150", numeric=True, min=0, max=100),
                    Check("FIPS", regex=r"\d{5}")],
            custom=_check_county_ranks,
            limit=3300,
        ),
        ContractCase(
            name="delaware_tracts_state_ranked_2022",
            filters={"geography": "tract", "year": 2022, "ranking": "state", "state": "DE"},
            min_rows=200,
            required_columns=["FIPS", "ST_ABBR", "RPL_THEMES", "RPL_THEME4", "E_TOTPOP", "M_TOTPOP"],
            checks=[Check("RPL_THEMES", numeric=True, min=0, max=1), Check("ST_ABBR", one_of=["DE"]),
                    Check("FIPS", regex=r"10\d{9}")],
            limit=500,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        geo, year, ranking = f.get("geography", "county"), f.get("year", LATEST), f.get("ranking", "us")
        if geo == "zcta" and year != 2022:
            raise FilterError("ZCTA-level SVI exists only for year 2022")
        st = state_abbr(f["state"]) if f.get("state") else None
        if ranking == "state" and not st:
            raise FilterError("ranking='state' needs the 'state' filter (e.g. 'DE')")
        url = file_url(year, geo, ranking, st)
        fips = set(f.get("fips") or [])
        wanted = f.get("variables")

        def keep(r: dict) -> bool:
            if st and (r.get("ST_ABBR") or "").strip().upper() != st:
                return False
            return not fips or (r.get("FIPS") or "").strip() in fips

        def transform(r: dict) -> dict:
            out = {}
            for k, v in r.items():
                if k is None or (wanted and k not in wanted and k not in ID_COLUMNS):
                    continue
                out[k] = _value(k, v)
            return out

        try:
            rows, matched = scan_csv(url, cache_allowed=cache_allowed, predicate=keep, limit=limit,
                                     transform=transform, max_age_s=30 * 86400)
        except SourceError as e:
            if e.status == 404:
                raise FilterError(f"no SVI file for {geo}/{year}/{ranking} ranking at {url}") from None
            raise
        if rows:
            require("FIPS" in rows[0] and "ST_ABBR" in rows[0], f"{url}: FIPS/ST_ABBR missing; columns {list(rows[0])[:20]}")
            if wanted:
                missing = [w for w in wanted if w not in rows[0]]
                if missing:
                    raise FilterError(f"unknown variable(s) {missing} for SVI {year}; variables differ by year (see documentation)")
        notes = [f"CDC/ATSDR SVI {year} ({year - 4}-{year} ACS 5-year), {geo} level, "
                 + ("ranked against all US areas." if ranking == "us" else f"ranked within {st} only."),
                 "Publisher sentinel -999 (data unavailable or not calculable) was converted to null."]
        return FetchResult(rows, [url], notes, total_available=matched,
                           metadata={"year": year, "geography": geo, "ranking": ranking})


ADAPTER = CdcSvi()
