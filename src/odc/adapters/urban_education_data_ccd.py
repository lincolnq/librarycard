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
    version = "1.0.0"
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


ADAPTER = UrbanEducationDataCcd()
