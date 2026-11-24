"""USAspending.gov spending by geography (API v2). Catalog: catalog/usaspending-spending-by-geography.yaml

Endpoint: POST https://api.usaspending.gov/api/v2/search/spending_by_geography/ (JSON body, no key)
  {"scope": "place_of_performance"|"recipient_location", "geo_layer": "state"|"county"|"district",
   "geo_layer_filters": [...codes], "spending_level": "transactions"|"awards",
   "filters": {"time_period": [{"start_date","end_date"}], "award_type_codes": [...],
               "agencies": [{"type": "awarding"|"funding", "tier": "toptier", "name": "<toptier agency name>"}]}}
  -> {"results": [{"shape_code", "display_name", "aggregated_amount", "population", "per_capita"}], "messages": [...]}
shape_code: state = postal code; county = 5-digit FIPS; district = state FIPS + 2-digit district ('0612'; '00' at-large).
A row with empty shape_code holds obligations whose location could not be resolved (kept, shape_code null).
Contract (field docs): github.com/fedspendingtransparency/usaspending-api/.../contracts/v2/search/spending_by_geography.md
Agency names are validated against GET /api/v2/references/toptier_agencies/.
Only geographic aggregates are requested — no recipient-level filters or fields (no private persons).
"""

from __future__ import annotations

import datetime as dt

from .. import http
from ..http import SourceError
from ._common import FIPS_STATE, STATE_FIPS, state_abbr, state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

API = "https://api.usaspending.gov/api/v2"
GEO_URL = f"{API}/search/spending_by_geography/"
AGENCIES_URL = f"{API}/references/toptier_agencies/"
AWARD_GROUPS = {
    "contracts": ["A", "B", "C", "D"],
    "idvs": ["IDV_A", "IDV_B", "IDV_B_A", "IDV_B_B", "IDV_B_C", "IDV_C", "IDV_D", "IDV_E"],
    "grants": ["02", "03", "04", "05"],
    "direct_payments": ["06", "10"],
    "loans": ["07", "08"],
    "other": ["09", "11", "-1"],
}
FIRST_FY = 2008  # API search window starts 2007-10-01

_agencies: dict[str, str] | None = None


def _agency_names() -> dict[str, str]:
    """lowercased name or abbreviation -> official toptier name."""
    global _agencies
    if _agencies is None:
        data = http.get_json(AGENCIES_URL)
        res = data.get("results") if isinstance(data, dict) else None
        require(isinstance(res, list) and res, f"unexpected toptier_agencies response from {AGENCIES_URL}")
        m: dict[str, str] = {}
        for a in res:
            n = a.get("agency_name")
            if not n:
                continue
            m[n.lower()] = n
            if a.get("abbreviation"):
                m.setdefault(a["abbreviation"].lower(), n)
        _agencies = m
    return _agencies


def _fy_ok(rows: list[dict]) -> None:
    total = sum(r["aggregated_amount"] or 0 for r in rows)
    # FY2023 federal contract obligations were ~$750B; states-only total must be in a plausible band.
    assert 4e11 < total < 1.2e12, f"FY2023 contract obligations across states = {total:,.0f}"


class UsaspendingSpendingByGeography(SourceAdapter):
    source_id = "usaspending-spending-by-geography"
    version = "1.0.0"
    usage = ("Federal award obligations (dollars) summed by state, county or congressional district for a fiscal year "
             "or date range, optionally restricted to award types (contracts, grants, loans, direct_payments, idvs, other) "
             "and one awarding/funding agency (toptier name or abbreviation, e.g. 'DOT'). scope chooses place of "
             "performance (where the work happens, default) or recipient location. Loans are face value, not subsidy "
             "cost; amounts are obligations (incl. negative de-obligations), not outlays.")
    filters = [
        FilterSpec("geo_layer", "string", "Geography of the rows.", required=True, enum=["county", "district", "state"], example="state"),
        FilterSpec("fiscal_year", "integer", f"Federal fiscal year (Oct 1 - Sep 30), {FIRST_FY} or later. Use this OR start_date/end_date.",
                   example=2023),
        FilterSpec("start_date", "string", "Action date >= YYYY-MM-DD (not before 2007-10-01)."),
        FilterSpec("end_date", "string", "Action date <= YYYY-MM-DD."),
        FilterSpec("award_type", "string_list", "Award type group(s); default all.", enum=sorted(AWARD_GROUPS), example=["grants"]),
        FilterSpec("agency", "string", "Toptier agency name or abbreviation, e.g. 'Department of Transportation' or 'DOT'.",
                   example="Department of Transportation"),
        FilterSpec("agency_type", "string", "Whether `agency` is the awarding (default) or funding agency.",
                   enum=["awarding", "funding"], default="awarding"),
        FilterSpec("scope", "string", "place_of_performance (default) or recipient_location.",
                   enum=["place_of_performance", "recipient_location"], default="place_of_performance"),
        FilterSpec("state", "string", "Restrict rows to one state (postal code or FIPS); applies to every geo_layer.", example="CA"),
        FilterSpec("geo_codes", "string_list", "Exact codes: state postal codes, 5-digit county FIPS, or 4-digit district "
                   "codes (state FIPS + district, e.g. '0612')."),
        FilterSpec("spending_level", "string", "transactions (default; obligations dated in the period) or awards "
                   "(adds total_outlays for awards with activity in the period).", enum=["transactions", "awards"],
                   default="transactions"),
    ]
    contract = [
        ContractCase(
            name="fy2023_contracts_by_state",
            filters={"geo_layer": "state", "fiscal_year": 2023, "award_type": ["contracts"]},
            min_rows=50, max_rows=60,
            required_columns=["shape_code", "display_name", "state_fips", "aggregated_amount", "population", "per_capita"],
            checks=[Check("aggregated_amount", numeric=True, min=-1e9, max=3e11), Check("state_fips", regex=r"\d\d")],
            limit=100,
            custom=_fy_ok,
        ),
        ContractCase(
            name="fy2023_dot_grants_california_counties",
            filters={"geo_layer": "county", "fiscal_year": 2023, "award_type": ["grants"], "agency": "DOT", "state": "CA"},
            min_rows=40, max_rows=58,
            required_columns=["shape_code", "display_name", "aggregated_amount", "state"],
            checks=[Check("shape_code", regex=r"06\d{3}"), Check("state", one_of=["CA"]),
                    Check("aggregated_amount", numeric=True, min=-1e9, max=2e10)],
            limit=100,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        layer = f["geo_layer"]
        if "fiscal_year" in f and ("start_date" in f or "end_date" in f):
            raise FilterError("use either fiscal_year or start_date/end_date, not both")
        if "fiscal_year" in f:
            fy = f["fiscal_year"]
            if fy < FIRST_FY or fy > dt.date.today().year + 1:
                raise FilterError(f"fiscal_year must be between {FIRST_FY} and {dt.date.today().year + 1}")
            start, end = f"{fy - 1}-10-01", f"{fy}-09-30"
        elif "start_date" in f or "end_date" in f:
            start, end = f.get("start_date", "2007-10-01"), f.get("end_date", dt.date.today().isoformat())
            for v in (start, end):
                try:
                    dt.date.fromisoformat(v)
                except ValueError:
                    raise FilterError(f"dates must be YYYY-MM-DD, got {v!r}") from None
            if start < "2007-10-01":
                raise FilterError("the search API starts at 2007-10-01 (FY2008); earlier data needs USAspending bulk downloads")
        else:
            raise FilterError("set fiscal_year (e.g. 2023) or start_date/end_date")
        filters: dict = {"time_period": [{"start_date": start, "end_date": end}]}
        if f.get("award_type"):
            filters["award_type_codes"] = [c for g in f["award_type"] for c in AWARD_GROUPS[g]]
        urls = [GEO_URL]
        if f.get("agency"):
            names = _agency_names()
            official = names.get(f["agency"].strip().lower())
            if not official:
                raise FilterError(f"unknown toptier agency {f['agency']!r}; see {AGENCIES_URL} for names/abbreviations")
            filters["agencies"] = [{"type": f.get("agency_type", "awarding"), "tier": "toptier", "name": official}]
            urls.append(AGENCIES_URL)
        body: dict = {"scope": f.get("scope", "place_of_performance"), "geo_layer": layer, "filters": filters,
                      "spending_level": f.get("spending_level", "transactions")}
        if f.get("geo_codes"):
            body["geo_layer_filters"] = [c.strip().upper() for c in f["geo_codes"]]
        st = state_fips(f["state"]) if f.get("state") else None
        if st and layer == "state":
            body["geo_layer_filters"] = [state_abbr(st)]

        try:
            r = http.request("POST", GEO_URL, json_body=body, timeout=180)
        except SourceError as e:
            if e.status in (400, 422):
                raise FilterError(f"USAspending rejected the query: {e}") from None
            raise
        try:
            data = r.json()
        except ValueError:
            raise SourceError(f"non-JSON from {GEO_URL}: {r.text[:200]}", kind="parse", url=GEO_URL) from None
        require(isinstance(data.get("results"), list), f"USAspending response lacks 'results'; keys={list(data)[:10]}")
        rows = []
        for x in data["results"]:
            require("aggregated_amount" in x and "shape_code" in x, f"unexpected result shape: {list(x)}")
            code = x.get("shape_code") or None
            if layer == "state":
                sf = STATE_FIPS.get(code or "")
            else:
                sf = code[:2] if code and code[:2].isdigit() else None
            if st and sf != st:
                continue
            row = {"shape_code": code, "display_name": x.get("display_name"), "state": FIPS_STATE.get(sf or ""),
                   "state_fips": sf, "aggregated_amount": x.get("aggregated_amount"),
                   "population": x.get("population"), "per_capita": x.get("per_capita")}
            if "total_outlays" in x:
                row["total_outlays"] = x["total_outlays"]
            rows.append(row)
        rows.sort(key=lambda r: (r["shape_code"] is None, r["shape_code"] or ""))
        notes = [f"Obligations with action dates {start} to {end}, by {body['scope']} ({body['spending_level']}).",
                 "A row with shape_code null (if present) holds obligations whose location could not be resolved."]
        notes += [m.strip() for m in data.get("messages") or [] if "subawards" not in m]
        meta = {"request_body": body}
        return FetchResult(rows[:limit], urls, notes, total_available=len(rows), metadata=meta)


ADAPTER = UsaspendingSpendingByGeography()
