"""CDC PLACES: Local Data for Better Health (Socrata on data.cdc.gov). Catalog: catalog/cdc-places.yaml

Each annual release is published as four separate Socrata datasets, one per geography level
(county, place, census tract, ZCTA), in long format: one row per location x measure x data value
type (crude / age-adjusted prevalence). Dataset ids per release are in RELEASES below; a new
release means NEW dataset ids (change detection watches the dataset names on data.cdc.gov's
catalog API). Columns differ slightly by level: tract rows carry countyfips/countyname; ZCTA
rows have no stateabbr/statedesc; `totalpop18plus` exists from the 2024 release on.
`geolocation` (GeoJSON point) is flattened to `lon`/`lat`.
"""

from __future__ import annotations

from ..http import SourceError
from ._common import soql_quote, socrata, state_abbr
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

DOMAIN = "data.cdc.gov"
# release -> geography -> Socrata dataset id (from data.cdc.gov catalog, checked 2026-11-24)
RELEASES: dict[int, dict[str, str]] = {
    2025: {"county": "swc5-untb", "place": "eav7-hnsx", "tract": "cwsq-ngmh", "zcta": "qnzd-25i4"},
    2024: {"county": "fu4u-a9bh", "place": "sd8v-uq83", "tract": "ai6z-tcin", "zcta": "4r2x-hcfq"},
    2023: {"county": "h3ej-a9ec", "place": "krqc-563j", "tract": "em5e-5hvn", "zcta": "9umn-c3jf"},
    2022: {"county": "duw2-7jbt", "place": "epbn-9bv3", "tract": "nw2y-v4gm", "zcta": "gd4x-jyhw"},
    2021: {"county": "pqpp-u99h", "place": "q8ig-wwk9", "tract": "373s-ayzu", "zcta": "s85h-9xpy"},
    2020: {"county": "dv4u-3x3q", "place": "q8xq-ygsk", "tract": "4ai3-zynv", "zcta": "fbbf-hgkc"},
}
LATEST = max(RELEASES)
NUMERIC = ("data_value", "low_confidence_limit", "high_confidence_limit", "totalpopulation", "totalpop18plus")
DROP_PREFIX = ":@computed_region"


def _num(v):
    if v in (None, ""):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return int(f) if f.is_integer() and "." not in str(v) else f


def _clean(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if k.startswith(DROP_PREFIX):
            continue
        if k == "geolocation":
            coords = (v or {}).get("coordinates") if isinstance(v, dict) else None
            out["lon"], out["lat"] = (coords[0], coords[1]) if coords and len(coords) == 2 else (None, None)
            continue
        out[k] = _num(v) if k in NUMERIC else v
    return out


def _check_de_obesity(rows: list[dict]) -> None:
    ids = {r["locationid"] for r in rows}
    assert {"10001", "10003", "10005"} <= ids, f"Delaware's three counties missing: {ids}"


class CdcPlaces(SourceAdapter):
    source_id = "cdc-places"
    version = "1.0.0"
    usage = ("Long format: one row per location x measure (measureid, e.g. OBESITY, DIABETES, CSMOKING, DEPRESSION, "
             "ACCESS2) x data value type (CrdPrv = crude prevalence, AgeAdjPrv = age-adjusted; tracts and ZCTAs have "
             "crude only). Pick `geography` and usually `state` + `measure_id`; `release` selects the annual release "
             "(default latest). `year` is the BRFSS data year, which differs by measure within a release. Values "
             "are model-based small-area estimates (%), with 95% confidence limits.")
    filters = [
        FilterSpec("geography", "string", "Geography level: county, place (Census place), tract (census tract) or zcta.",
                   enum=["county", "place", "tract", "zcta"], default="county", example="county"),
        FilterSpec("release", "integer", f"PLACES release year (default {LATEST}). Each release uses data from ~2 years earlier.",
                   enum=sorted(RELEASES), default=LATEST),
        FilterSpec("state", "string", "State postal code or FIPS (not available for zcta). 'US' rows (national) exist in the county file.",
                   example="CA"),
        FilterSpec("measure_id", "string_list", "Measure ids, e.g. ['OBESITY','DIABETES']. See metadata.measures or https://www.cdc.gov/places/measure-definitions/.",
                   example=["OBESITY"]),
        FilterSpec("data_value_type", "string", "CrdPrv (crude prevalence) or AgeAdjPrv (age-adjusted prevalence; county and place only).",
                   enum=["CrdPrv", "AgeAdjPrv"]),
        FilterSpec("year", "integer", "BRFSS data year of the estimate (e.g. 2023 or 2022 in the 2025 release).", example=2023),
        FilterSpec("location_id", "string_list", "Exact locationid values: 5-digit county FIPS, 7-digit place FIPS, 11-digit tract FIPS or 5-digit ZCTA.",
                   example=["06037"]),
        FilterSpec("category_id", "string", "Measure category, e.g. HLTHOUT (health outcomes), PREVENT, RISKBEH, HLTHSTAT, DISABLT, SOCLNEED.",
                   example="HLTHOUT"),
    ]
    contract = [
        ContractCase(
            name="delaware_county_obesity_2025",
            filters={"geography": "county", "release": 2025, "state": "DE", "measure_id": ["OBESITY"], "data_value_type": "CrdPrv"},
            min_rows=3, max_rows=3,
            required_columns=["year", "stateabbr", "locationid", "locationname", "measureid", "datavaluetypeid",
                              "data_value", "low_confidence_limit", "high_confidence_limit", "totalpopulation"],
            checks=[Check("data_value", numeric=True, min=15, max=60), Check("stateabbr", one_of=["DE"]),
                    Check("measureid", one_of=["OBESITY"]), Check("locationid", regex=r"10\d{3}")],
            custom=_check_de_obesity,
            limit=20,
        ),
        ContractCase(
            name="delaware_tract_diabetes_2024",
            filters={"geography": "tract", "release": 2024, "state": "DE", "measure_id": ["DIABETES"]},
            min_rows=200,
            required_columns=["locationid", "countyfips", "data_value", "measureid"],
            checks=[Check("data_value", numeric=True, min=0, max=60), Check("locationid", regex=r"10\d{9}"),
                    Check("datavaluetypeid", one_of=["CrdPrv"])],
            limit=500,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        geo = f.get("geography", "county")
        release = f.get("release", LATEST)
        ds = RELEASES[release][geo]
        clauses = []
        if "state" in f:
            if geo == "zcta":
                raise FilterError("ZCTA rows have no state column; filter by location_id (5-digit ZCTAs) instead")
            st = "US" if str(f["state"]).upper() == "US" else state_abbr(f["state"])
            clauses.append(f"stateabbr = {soql_quote(st)}")
        if "measure_id" in f:
            clauses.append("measureid in (" + ",".join(soql_quote(m.upper()) for m in f["measure_id"]) + ")")
        if "data_value_type" in f:
            clauses.append(f"datavaluetypeid = {soql_quote(f['data_value_type'])}")
        if "year" in f:
            clauses.append(f"year = {soql_quote(str(f['year']))}")
        if "location_id" in f:
            clauses.append("locationid in (" + ",".join(soql_quote(x) for x in f["location_id"]) + ")")
        if "category_id" in f:
            clauses.append(f"categoryid = {soql_quote(f['category_id'].upper())}")
        where = " AND ".join(clauses) or None
        try:
            raw, url = socrata(DOMAIN, ds, where=where, order="locationid,measureid,datavaluetypeid", limit=limit)
        except SourceError as e:
            if e.status == 400:
                raise FilterError(f"data.cdc.gov rejected the query: {e}") from None
            raise
        require(isinstance(raw, list), f"expected a JSON list from {url}", kind="parse")
        urls = [url]
        total = None
        if len(raw) >= limit:
            try:
                cnt, curl_ = socrata(DOMAIN, ds, where=where, select="count(*) as n", limit=1)
                total = int(cnt[0]["n"])
                urls.append(curl_)
            except (SourceError, KeyError, IndexError, ValueError):
                total = None
        else:
            total = len(raw)
        rows = [_clean(r) for r in raw]
        if rows:
            require("measureid" in rows[0] and "data_value" in rows[0],
                    f"PLACES dataset {ds} rows lack measureid/data_value: {sorted(rows[0])}")
        notes = [f"PLACES {release} release, {geo} level (data.cdc.gov dataset {ds}). Estimates are model-based "
                 "(multilevel regression and poststratification of BRFSS), not direct survey estimates.",
                 "geolocation was flattened to lon/lat; numeric fields converted from strings. Blank data_value means "
                 "suppressed or not estimated (see data_value_footnote)."]
        return FetchResult(rows, urls, notes, total_available=total,
                           metadata={"release": release, "geography": geo, "dataset_id": ds,
                                     "dataset_url": f"https://{DOMAIN}/d/{ds}"})


ADAPTER = CdcPlaces()
