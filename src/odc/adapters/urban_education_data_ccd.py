"""Urban Institute Education Data Portal — NCES Common Core of Data (CCD), school districts.
Catalog: catalog/urban-education-data-ccd.yaml

API (no key): https://educationdata.urban.org/api/v1/school-districts/ccd/<topic>/<year>/[...]/?<field>=<value>
  finance    /school-districts/ccd/finance/{year}/                         (F-33 survey; years 1991, 1994-2020)
  enrollment /school-districts/ccd/enrollment/{year}/grade-{g}/[race/|sex/|race/sex/]  (1986-2024)
  directory  /school-districts/ccd/directory/{year}/                       (1986-2024)
Query params filter on any field (fips=, leaid= single value). Responses: {"count", "next", "previous",
"results": [...]}; follow `next` to paginate. Codes: -1 missing/not reported, -2 not applicable, -3 suppressed
(converted to null except in code columns); race/sex 99 = total; grade -1 = pre-K, 0 = K, 99 = total.
Endpoint catalogue with years: https://educationdata.urban.org/api/v1/api-endpoints/
"""

from __future__ import annotations

import json
import re
import time

import httpx

from .. import http
from ._common import state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

BASE = "https://educationdata.urban.org/api/v1/school-districts/ccd"
GRADES = ["pk", "k"] + [str(i) for i in range(1, 14)] + ["99"]
BREAKDOWNS = {"none": "", "race": "race/", "sex": "sex/", "race_sex": "race/sex/"}
SENTINELS = {-1, -2, -3, "-1", "-2", "-3"}
CODE_COLS = {"year", "fips", "leaid", "grade", "race", "sex", "censusid", "state_leaid", "agency_type",
             "lea_type", "urban_centric_locale", "phone", "zip_mailing", "zip_location", "county_code", "cbsa", "csa",
             "congress_district_id", "state_leg_district_lower", "state_leg_district_upper", "agency_level",
             "boundary_change_indicator", "supervisory_union_number", "highest_grade_offered", "lowest_grade_offered",
             "lea_name", "street_mailing", "city_mailing", "state_mailing", "street_location",
             "city_location", "state_location"}


def _clean(row: dict) -> dict:
    return {k: (None if k not in CODE_COLS and v in SENTINELS else v) for k, v in row.items()}


def _check_wilmington_scale(rows: list[dict]) -> None:
    tot = sum(r["enrollment"] or 0 for r in rows if r.get("race") == 99 and r.get("sex") == 99)
    assert 100_000 < tot < 160_000, f"Delaware 2020 total district enrollment {tot} implausible"


class UrbanEducationDataCcd(SourceAdapter):
    source_id = "urban-education-data-ccd"
    version = "1.1.0"
    usage = ("Pick `dataset`: 'finance' (one row per district-year, revenues rev_* and expenditures exp_* in dollars, "
             "F-33 survey, years to 2020), 'enrollment' (one row per district x grade [x race/sex]; `grade` default "
             "'99' = total; `breakdown` adds race and/or sex rows where 99 = total) or 'directory' (district names, "
             "type, locale, counts). Always give `year` and usually `state`. leaid is the 7-digit NCES district id; "
             "-1/-2/-3 (missing/not applicable/suppressed) come back as null.")
    filters = [
        FilterSpec("dataset", "string", "finance, enrollment or directory.", required=True,
                   enum=["finance", "enrollment", "directory"], example="finance"),
        FilterSpec("year", "integer", "School/fiscal year (fall of the school year for enrollment/directory; fiscal year for finance).",
                   required=True, example=2020),
        FilterSpec("state", "string", "State postal code or FIPS.", example="DE"),
        FilterSpec("leaid", "string_list", "7-digit NCES district ids, e.g. ['1000006'].", example=["1000006"]),
        FilterSpec("grade", "string", "Enrollment only: pk, k, 1-12, 13 (ungraded) or 99 (total, default).", enum=GRADES, default="99"),
        FilterSpec("breakdown", "string", "Enrollment only: none (default), race, sex or race_sex.", enum=sorted(BREAKDOWNS), default="none"),
    ]
    contract = [
        ContractCase(
            name="delaware_finance_2019",
            filters={"dataset": "finance", "year": 2019, "state": "DE"},
            min_rows=30,
            required_columns=["year", "leaid", "fips", "rev_total", "rev_fed_total", "rev_state_total", "rev_local_total", "exp_total"],
            checks=[Check("fips", one_of=[10]), Check("year", one_of=[2019]), Check("leaid", regex=r"10\d{5}"),
                    Check("rev_total", numeric=True, min=0, max=5e9)],
            limit=200,
        ),
        ContractCase(
            name="delaware_enrollment_2020_total",
            filters={"dataset": "enrollment", "year": 2020, "state": "DE"},
            min_rows=30,
            required_columns=["year", "leaid", "fips", "grade", "race", "sex", "enrollment"],
            checks=[Check("grade", one_of=[99]), Check("enrollment", numeric=True, min=0, max=200000)],
            custom=_check_wilmington_scale,
            limit=200,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        ds, year = f["dataset"], f["year"]
        if year < 1986 or year > 2100:
            raise FilterError("year must be 1986 or later (finance: 1991, 1994-2020)")
        if ds != "enrollment" and (f.get("breakdown", "none") != "none" or f.get("grade", "99") != "99"):
            raise FilterError("grade/breakdown apply only to dataset='enrollment'")
        if ds == "finance":
            url = f"{BASE}/finance/{year}/"
        elif ds == "directory":
            url = f"{BASE}/directory/{year}/"
        else:
            url = f"{BASE}/enrollment/{year}/grade-{f.get('grade', '99')}/{BREAKDOWNS[f.get('breakdown', 'none')]}"
        params: dict = {}
        if f.get("state"):
            params["fips"] = int(state_fips(f["state"]))
        leaids = set(f.get("leaid") or [])
        if len(leaids) == 1:
            params["leaid"] = next(iter(leaids))
        rows: list[dict] = []
        urls: list[str] = []
        total = None
        next_url: str | None = url
        first = True
        while next_url and len(rows) < limit and len(urls) < 20:
            r = http.request("GET", next_url, params=params if first else None, timeout=120)
            first = False
            urls.append(str(r.request.url))
            try:
                data = r.json()
            except ValueError:
                require(False, f"non-JSON from {r.request.url}: {r.text[:200]}", kind="parse")
            require(isinstance(data, dict) and "results" in data, f"unexpected response shape from {r.request.url}: {str(data)[:200]}")
            if total is None:
                total = data.get("count")
            for row in data["results"]:
                if leaids and str(row.get("leaid")) not in leaids:
                    continue
                rows.append(_clean(row))
                if len(rows) >= limit:
                    break
            next_url = data.get("next")
        if len(leaids) > 1:
            total = None  # count refers to the unfiltered state query
        notes = [f"NCES Common Core of Data via the Urban Institute Education Data Portal ({ds}, {year}).",
                 "Codes -1 (missing), -2 (not applicable), -3 (suppressed) were converted to null in value columns."]
        if ds == "finance":
            notes.append("Finance amounts are nominal dollars for the fiscal year (F-33 School District Finance Survey).")
        return FetchResult(rows, urls, notes, total_available=total, metadata={"dataset": ds, "year": year})

    # ------------------------------------------------------------------ mirror (docs/MIRROR.md)
    # Scope: directory (all years), finance (all years), enrollment grade 99 (= all grades) for all years, with the
    # race x sex breakdown for the latest year only (it is ~500k rows per year and the API serves ~10k rows per
    # 15-30 s). Rows get `dataset` and `state_fips` (2-digit string of `fips`) columns for partitioning.
    mirror_partition_keys = ["dataset", "year", "state_fips"]
    mirror_required = ["dataset"]
    mirror_semantics = {"state_fips": "state_fips", "year": "year"}

    def mirror_plan(self):
        from ..mirror import MirrorUnit
        years = _endpoint_years()
        for ds in ("directory", "enrollment", "finance"):
            for y in years[ds]:
                yield MirrorUnit(partition={"dataset": ds, "year": str(y)}, filters={"dataset": ds, "year": y},
                                 split_by=["state_fips"])

    def mirror_rows(self, unit):
        ds, year = unit.filters["dataset"], unit.filters["year"]
        urls: list[str] = []
        notes = ["NCES Common Core of Data via the Urban Institute Education Data Portal.",
                 "Codes -1 (missing), -2 (not applicable), -3 (suppressed) were converted to null in value columns.",
                 "Finance amounts are nominal dollars for the fiscal year (F-33 School District Finance Survey).",
                 "Enrollment rows are grade 99 (all grades). Every year has the district total (race 99, sex 99); the "
                 f"latest year ({_endpoint_years()['enrollment'][-1]}) also has race x sex rows, so filter race=99 and "
                 "sex=99 for totals. Other grades and breakdowns: use the local odc-server or the publisher's API."]
        latest_enr = _endpoint_years()["enrollment"][-1]

        def tag(rows):
            for r in rows:
                f = r.get("fips")
                yield {"dataset": ds, "state_fips": "" if f is None else f"{int(f):02d}", **_clean(r)}

        def gen():
            if ds == "directory":
                yield from tag(_mirror_paged(f"{BASE}/directory/{year}/", {}, urls))
            elif ds == "enrollment":
                suffix = "race/sex/" if year == latest_enr else ""
                yield from tag(_mirror_paged(f"{BASE}/enrollment/{year}/grade-99/{suffix}", {}, urls))
            else:  # finance: national queries time out (HTTP 524), so query a few states at a time
                for group in _fips_groups(year):
                    try:
                        rows = list(_mirror_paged(f"{BASE}/finance/{year}/", {"fips": ",".join(group)}, urls))
                    except http.SourceError:
                        if len(group) == 1:
                            raise
                        rows = [r for g in group for r in _mirror_paged(f"{BASE}/finance/{year}/", {"fips": g}, urls)]
                    yield from tag(rows)

        return gen(), urls, notes, {"endpoints": {ds: f"{BASE}/{ds}/{{year}}/"}}


# ---------------------------------------------------------------------- mirror helpers

def _endpoint_years() -> dict[str, list[int]]:
    """Years per endpoint from the portal's endpoint catalogue (e.g. '1991, 1994&ndash;2020')."""
    global _YEARS
    if _YEARS is None:
        data = _cached_json("https://educationdata.urban.org/api/v1/api-endpoints/", {})
        by_id = {str(e.get("endpoint_id")): e for e in data.get("results", [])}
        out = {}
        for ds, eid in (("finance", "29"), ("directory", "54"), ("enrollment", "56")):
            text = (by_id.get(eid) or {}).get("years_available", "")
            ys: list[int] = []
            for part in re.split(r"\s*,\s*", text.replace("&ndash;", "-")):
                m = re.fullmatch(r"(\d{4})(?:\s*-\s*(\d{4}))?", part.strip())
                if m:
                    ys += list(range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1))
            require(ys, f"no years_available for endpoint {eid} ({ds}): {text!r}")
            out[ds] = sorted(set(ys))
        _YEARS = out
    return _YEARS


_YEARS: dict[str, list[int]] | None = None
RETRY_STATUSES = {429, 500, 502, 503, 504, 520, 521, 522, 523, 524}


def _cached_json(url: str, params: dict) -> dict:
    """GET through the license-gated download cache (pages survive an interrupted ingest), retrying the API's
    frequent gateway timeouts with backoff. Sequential only; the API publishes no rate limits or headers."""
    for attempt in range(6):
        try:
            with http.download(url, params=params or None, cache_allowed=True, max_age_s=3 * 86400) as path:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
        except http.SourceError as e:
            if attempt == 5 or not (e.kind == "network" or e.status in RETRY_STATUSES):
                raise
            time.sleep(min(15 * 2 ** attempt, 240))
        except ValueError as e:
            raise http.SourceError(f"non-JSON from {url} {params}: {e}", kind="parse", url=url) from e
    raise AssertionError("unreachable")


def _mirror_paged(url: str, params: dict, urls: list[str]):
    """Yield every result of an endpoint, following `page`; checks the row total against `count`."""
    page, n, count = 1, 0, None
    while True:
        p = dict(params, **({"page": page} if page > 1 else {}))
        data = _cached_json(url, p)
        require(isinstance(data, dict) and "results" in data, f"unexpected response shape from {url} {p}")
        if page == 1:
            count = data.get("count")
            urls.append(str(httpx.URL(url, params=p)))
        yield from data["results"]
        n += len(data["results"])
        if not data.get("next") or not data["results"]:
            break
        page += 1
    require(count is None or n == count, f"{url} {params}: paged {n} rows but count is {count}")


def _fips_groups(year: int, max_rows: int = 1200) -> list[list[str]]:
    """Batch states for finance queries using district counts from the (cached) directory of the same year."""
    counts: dict[int, int] = {}
    for r in _mirror_paged(f"{BASE}/directory/{year}/", {}, []):
        if r.get("fips") is not None:
            counts[int(r["fips"])] = counts.get(int(r["fips"]), 0) + 1
    groups: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for f in sorted(counts):
        if cur and size + counts[f] > max_rows:
            groups.append(cur)
            cur, size = [], 0
        cur.append(str(f))
        size += counts[f]
    if cur:
        groups.append(cur)
    return groups


ADAPTER = UrbanEducationDataCcd()
