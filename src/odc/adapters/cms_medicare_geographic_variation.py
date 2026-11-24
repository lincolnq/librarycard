"""CMS Medicare Geographic Variation — by National, State & County. Catalog: catalog/cms-medicare-geographic-variation.yaml

API (keyless): https://data.cms.gov/data-api/v1/dataset/<UUID>/data
  UUID 6219697b-... is the "latest" distribution of the series in data.cms.gov/data.json (it served the
  2014-2024 file on 2026-11-24); each release also gets a version-specific uuid.
  Params: filter[COL]=value (exact), filter[k][condition][path|operator|value]=... (STARTS_WITH, IN, ...),
  column=A,B,C (select), size (<= 5000), offset. /data/stats returns {"found_rows", "total_rows"}.
All values are strings. "*" marks cells suppressed for small counts (CMS cell-size rule) -> null.
Rows: one per YEAR x BENE_GEO_LVL (National/State/County) x geography x BENE_AGE_LVL (All, <65, >=65).
"""

from __future__ import annotations

from .. import http
from ._common import state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

UUID = "6219697b-8f6c-4164-bed4-cd9317c58ebc"
BASE = f"https://data.cms.gov/data-api/v1/dataset/{UUID}/data"
PAGE = 5000
TEXT_COLS = {"BENE_GEO_LVL", "BENE_GEO_DESC", "BENE_GEO_CD", "BENE_AGE_LVL"}
LEVELS = {"national": "National", "state": "State", "county": "County"}
AGES = {"all": "All", "under65": "<65", "65plus": ">=65"}


def _num(v):
    if v is None:
        return None
    v = str(v).strip()
    if v in ("", "*"):
        return None
    try:
        f = float(v)
    except ValueError:
        return v
    return int(f) if f.is_integer() and "." not in v else f


def _clean(row: dict) -> dict:
    return {k: (v if k in TEXT_COLS else _num(v)) for k, v in row.items()}


def _check_de(rows: list[dict]) -> None:
    by = {r["BENE_GEO_CD"]: r for r in rows}
    assert {"10001", "10003", "10005"} <= set(by), sorted(by)
    for cd in ("10001", "10003", "10005"):
        assert 5000 < by[cd]["TOT_MDCR_STDZD_PYMT_PC"] < 20000, by[cd]


class CmsMedicareGeographicVariation(SourceAdapter):
    source_id = "cms-medicare-geographic-variation"
    version = "1.0.0"
    usage = ("One row per year x geography x age group for Original (fee-for-service) Medicare: beneficiary counts and "
             "demographics, total and standardized (price-adjusted) Medicare payments per capita, and use by service "
             "type (inpatient, outpatient, SNF, home health, hospice, E&M, imaging, tests, ...), plus prevention-quality "
             "measures. Filter `level` (state default), `year`, `state`; `columns` selects fields (~240 total). Use "
             "*_STDZD_* columns to compare spending across areas. Suppressed cells ('*') return null.")
    filters = [
        FilterSpec("level", "string", "Geography level: national, state (default) or county.", enum=sorted(LEVELS), default="state"),
        FilterSpec("year", "integer", "Calendar year of claims, 2014 or later.", example=2022),
        FilterSpec("state", "string", "State postal code or FIPS (state or county level).", example="DE"),
        FilterSpec("county_fips", "string_list", "5-digit county FIPS codes (county level).", example=["10003"]),
        FilterSpec("age_group", "string", "all (default), under65 or 65plus beneficiaries.", enum=sorted(AGES), default="all"),
        FilterSpec("columns", "string_list", "Columns to return, e.g. ['TOT_MDCR_STDZD_PYMT_PC','BENES_OM_CNT']; id columns always included.",
                   example=["TOT_MDCR_STDZD_PYMT_PC", "BENES_OM_CNT"]),
    ]
    contract = [
        ContractCase(
            name="delaware_counties_2022",
            filters={"level": "county", "year": 2022, "state": "DE",
                     "columns": ["TOT_MDCR_STDZD_PYMT_PC", "BENES_OM_CNT", "MA_PRTCPTN_RATE"]},
            min_rows=3, max_rows=4,
            required_columns=["YEAR", "BENE_GEO_LVL", "BENE_GEO_CD", "BENE_GEO_DESC", "BENE_AGE_LVL", "TOT_MDCR_STDZD_PYMT_PC"],
            checks=[Check("YEAR", one_of=[2022]), Check("BENE_GEO_LVL", one_of=["County"]),
                    Check("BENE_GEO_CD", regex=r"10\d{3}"), Check("MA_PRTCPTN_RATE", numeric=True, min=0, max=1)],
            custom=_check_de,
        ),
        ContractCase(
            name="states_2019_all_ages",
            filters={"level": "state", "year": 2019, "columns": ["BENES_TOTAL_CNT", "TOT_MDCR_PYMT_PC"]},
            min_rows=50, max_rows=56,
            required_columns=["BENE_GEO_CD", "BENES_TOTAL_CNT", "TOT_MDCR_PYMT_PC"],
            checks=[Check("BENES_TOTAL_CNT", numeric=True, min=10000, max=8_000_000),
                    Check("TOT_MDCR_PYMT_PC", numeric=True, min=3000, max=25000)],
            limit=100,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        level = f.get("level", "state")
        params: dict = {"filter[BENE_GEO_LVL]": LEVELS[level], "filter[BENE_AGE_LVL]": AGES[f.get("age_group", "all")]}
        if "year" in f:
            if f["year"] < 2014:
                raise FilterError("this release covers 2014 onward")
            params["filter[YEAR]"] = str(f["year"])
        if f.get("state"):
            if level == "national":
                raise FilterError("state filter needs level 'state' or 'county'")
            sf = state_fips(f["state"])
            if level == "state":
                params["filter[BENE_GEO_CD]"] = sf
            else:
                params.update({"filter[st][condition][path]": "BENE_GEO_CD", "filter[st][condition][operator]": "STARTS_WITH",
                               "filter[st][condition][value]": sf})
        if f.get("county_fips"):
            if level != "county":
                raise FilterError("county_fips needs level='county'")
            params.update({"filter[cf][condition][path]": "BENE_GEO_CD", "filter[cf][condition][operator]": "IN"})
            for i, c in enumerate(f["county_fips"], 1):
                if not (c.isdigit() and len(c) == 5):
                    raise FilterError(f"county_fips must be 5 digits, got {c!r}")
                params[f"filter[cf][condition][value][{i}]"] = c
        if f.get("columns"):
            cols = ["YEAR", "BENE_GEO_LVL", "BENE_GEO_CD", "BENE_GEO_DESC", "BENE_AGE_LVL"]
            cols += [c for c in f["columns"] if c not in cols]
            params["column"] = ",".join(cols)
        rows: list[dict] = []
        urls: list[str] = []
        offset = 0
        while len(rows) < limit:
            size = min(PAGE, limit - len(rows))
            r = http.request("GET", BASE, params={**params, "size": size, "offset": offset}, timeout=120)
            urls.append(str(r.request.url))
            if "cannot be found" in r.text[:200]:
                raise http.SourceError(f"CMS dataset {UUID} not found (release replaced?)", kind="http", url=urls[-1])
            try:
                data = r.json()
            except ValueError:
                require(False, f"non-JSON from {r.request.url}: {r.text[:200]}", kind="parse")
            require(isinstance(data, list), f"expected a JSON list from {r.request.url}: {str(data)[:200]}")
            rows.extend(_clean(x) for x in data)
            if len(data) < size:
                break
            offset += size
        if f.get("columns") and rows:
            missing = [c for c in f["columns"] if c not in rows[0]]
            if missing:
                raise FilterError(f"unknown column(s) {missing}; see the data dictionary linked in the catalog entry")
        total = None
        try:
            st = http.get_json(BASE + "/stats", params=params)
            total = int(st.get("found_rows"))
        except (http.SourceError, TypeError, ValueError, AttributeError):
            pass
        notes = ["Original Medicare (fee-for-service) beneficiaries only; Medicare Advantage enrollees are excluded from "
                 "spending/use measures.",
                 "Cells suppressed by CMS for small counts ('*') were converted to null; values converted from strings."]
        return FetchResult(rows[:limit], urls, notes, total_available=total, metadata={"dataset_uuid": UUID})


ADAPTER = CmsMedicareGeographicVariation()
