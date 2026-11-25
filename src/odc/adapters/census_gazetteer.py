"""Census Gazetteer files (area and internal point per geographic entity). Catalog: catalog/census-gazetteer.yaml

Layout on www2.census.gov:
  /geo/docs/maps-data/data/gazetteer/<YEAR>_Gazetteer/<YEAR>_Gaz_<layer>_national.zip   (one .txt member)
  /geo/docs/maps-data/data/gazetteer/<YEAR>_Gazetteer/<YEAR>_gaz_<layer>_<SS>.txt       (per-state; counties,
                                                                                          cousubs, place, tracts)
Layer tokens: counties, cousubs, place, tracts, zcta, state (2024+), cbsa, ua, unsd, elsd, scsd, sldl, sldu,
<NNN>CDs (Congress number, e.g. 119CDs), aiannh. File names are resolved from the directory listing (case and the
Congress number vary by year).
Format: 2012-2024 files are TAB-delimited with trailing spaces after the last header/value; 2025+ files are
PIPE-delimited and add GEOIDFQ (the fully-qualified GEO_ID, e.g. 0500000US01001). The delimiter is sniffed from the
header. Encoding UTF-8. Numeric columns: ALAND/AWATER (m^2), ALAND_SQMI/AWATER_SQMI, INTPTLAT/INTPTLONG (degrees).
"""

from __future__ import annotations

import re

from .. import http
from ..http import SourceError
from ._common import state_abbr, state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

ROOT = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
FIRST_YEAR = 2020  # 2020-based geography; earlier years exist but are not served

# filter value -> (national file token regex, per-state token or None)
LAYERS = {
    "state": (r"state", None),
    "county": (r"counties", "counties"),
    "county_subdivision": (r"cousubs", "cousubs"),
    "place": (r"place", "place"),
    "tract": (r"tracts", "tracts"),
    "zcta": (r"zcta", None),
    "congressional_district": (r"\d{3}CDs", None),
    "state_legislative_district_upper": (r"sldu", None),
    "state_legislative_district_lower": (r"sldl", None),
    "school_district_unified": (r"unsd", None),
    "school_district_elementary": (r"elsd", None),
    "school_district_secondary": (r"scsd", None),
    "metro_area": (r"cbsa", None),
    "urban_area": (r"ua", None),
    "aiannh": (r"aiannh", None),
}
NUMERIC = {"ALAND": int, "AWATER": int, "ALAND_SQMI": float, "AWATER_SQMI": float, "INTPTLAT": float, "INTPTLONG": float}

_listing_cache: dict[str, str] = {}


def _listing(url: str) -> str:
    if url not in _listing_cache:
        _listing_cache[url] = http.get_text(url)
    return _listing_cache[url]


def years() -> list[int]:
    return sorted(int(y) for y in set(re.findall(r'href="(\d{4})_Gazetteer/"', _listing(ROOT))))


def resolve(year: int, layer: str, st: str | None) -> tuple[str, bool]:
    """Return (url, is_state_file)."""
    d = f"{ROOT}{year}_Gazetteer/"
    try:
        html = _listing(d)
    except SourceError as e:
        if e.status == 404:
            raise FilterError(f"no Gazetteer for {year}; years available: {years()}") from None
        raise
    tok, state_tok = LAYERS[layer]
    if st and state_tok:
        m = re.search(rf'href="({year}_gaz_{state_tok}_{st}\.txt)"', html, re.I)
        if m:
            return d + m.group(1), True
    m = re.search(rf'href="({year}_Gaz_{tok}_national\.zip)"', html, re.I)
    if not m:
        raise FilterError(f"the {year} Gazetteer has no '{layer}' file (see {d})")
    return d + m.group(1), False


def _num(col: str, v: str):
    v = v.strip()
    if v == "":
        return None
    try:
        return NUMERIC[col](v)
    except ValueError:
        return v


class CensusGazetteer(SourceAdapter):
    source_id = "census-gazetteer"
    version = "1.0.0"
    usage = ("One row per geographic entity of a layer (county, place, tract, zcta, congressional_district, ...) "
             "for one Gazetteer year, with GEOID, NAME (where published), land/water area (ALAND/AWATER in square "
             "metres, *_SQMI in square miles) and an internal point INTPTLAT/INTPTLONG. Use ALAND_SQMI for population "
             "density, and GEOID to join with Census tables. `state` uses small per-state files where Census publishes "
             "them (county, county_subdivision, place, tract); ZCTAs have no state.")
    filters = [
        FilterSpec("layer", "string", "Geographic layer.", required=True, enum=sorted(LAYERS), example="county"),
        FilterSpec("year", "integer", f"Gazetteer year (boundaries as of Jan 1 of that year), {FIRST_YEAR} or later. Default: latest.",
                   example=2025),
        FilterSpec("state", "string", "Restrict to one state (postal code or FIPS). Not applicable to zcta, metro_area, urban_area, aiannh.",
                   example="DE"),
        FilterSpec("geoids", "string_list", "Exact GEOIDs, e.g. ['10001'] for Kent County, DE or ['19901'] for a ZCTA.",
                   example=["10001"]),
    ]
    contract = [
        ContractCase(
            name="delaware_counties_2023",
            filters={"layer": "county", "state": "DE", "year": 2023},
            min_rows=3, max_rows=3,
            required_columns=["GEOID", "NAME", "ALAND", "ALAND_SQMI", "INTPTLAT", "INTPTLONG"],
            checks=[Check("GEOID", one_of=["10001", "10003", "10005"]),
                    Check("ALAND_SQMI", numeric=True, min=300, max=1000),
                    Check("INTPTLAT", numeric=True, min=38.4, max=39.9),
                    Check("INTPTLONG", numeric=True, min=-76, max=-75)],
            limit=10,
        ),
        ContractCase(
            name="congressional_districts_2025",
            filters={"layer": "congressional_district", "year": 2025, "state": "DE"},
            min_rows=1, max_rows=1,
            required_columns=["GEOID", "GEOIDFQ", "ALAND_SQMI", "INTPTLAT"],
            checks=[Check("GEOID", one_of=["1000"]), Check("ALAND_SQMI", numeric=True, min=1900, max=2000)],
            limit=10,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        layer = f["layer"]
        year = f.get("year") or max(years())
        if year < FIRST_YEAR:
            raise FilterError(f"year must be {FIRST_YEAR} or later (earlier Gazetteers use 2010-based geography and a different naming scheme)")
        st = state_fips(f["state"]) if f.get("state") else None
        if st and layer in ("zcta", "metro_area", "urban_area", "aiannh"):
            raise FilterError(f"layer '{layer}' is not nested in states; drop the state filter (filter by geoids instead)")
        geoids = set(f.get("geoids") or [])
        url, is_state_file = resolve(year, layer, st)
        usps = state_abbr(st) if st else None
        out: list[dict] = []
        matched = 0
        with http.download(url, cache_allowed=cache_allowed, max_age_s=60 * 86400) as path:
            with http.open_text(path, encoding="utf-8-sig") as fh:
                header_line = fh.readline()
                delim = "|" if "|" in header_line else "\t"
                header = [h.strip() for h in header_line.rstrip("\r\n").split(delim)]
                require("GEOID" in header and "INTPTLAT" in header and "ALAND" in header,
                        f"{url}: expected GEOID/ALAND/INTPTLAT in header, got {header}")
                for line in fh:
                    if not line.strip():
                        continue
                    vals = [v.strip() for v in line.rstrip("\r\n").split(delim)]
                    row = dict(zip(header, vals))
                    if st and not is_state_file:
                        if "USPS" in row:
                            if row["USPS"] != usps:
                                continue
                        elif not row["GEOID"].startswith(st):
                            continue
                    if geoids and row["GEOID"] not in geoids:
                        continue
                    matched += 1
                    if len(out) < limit:
                        out.append({k: (_num(k, v) if k in NUMERIC else (v or None)) for k, v in row.items()})
        notes = [f"{year} Gazetteer, layer '{layer}', from {url}.",
                 "ALAND/AWATER are square metres; ALAND_SQMI/AWATER_SQMI square miles; INTPTLAT/INTPTLONG is the "
                 "Census internal point (inside the area, not a centroid)."]
        if year < 2025:
            notes.append("GEOIDFQ (fully-qualified GEO_ID) is only published from the 2025 Gazetteer onward.")
        return FetchResult(out, [url], notes, total_available=matched, metadata={"year": year, "layer": layer})


ADAPTER = CensusGazetteer()
