"""FHFA House Price Index (HPI) CSV downloads. Catalog: catalog/fhfa-hpi.yaml

Files used (index page https://www.fhfa.gov/data/hpi/datasets, checked 2026-11-24):
* https://www.fhfa.gov/hpi/download/monthly/hpi_master.csv (~17 MB, header row)
    hpi_type,hpi_flavor,frequency,level,place_name,place_id,yr,period,index_nsa,index_sa,rstderr,note
    level: 'USA or Census Division' (place_id USA, DV_ENC, ...), 'State' (postal), 'MSA' (CBSA/MSAD code),
    'Puerto Rico'. hpi_type: traditional, distress-free, non-metro, manufactured, developmental.
    hpi_flavor: purchase-only, all-transactions, expanded-data. frequency: monthly (purchase-only US/division
    only) or quarterly. `note` is sometimes a lone tab; we strip it.
* https://www.fhfa.gov/hpi/download/annual/hpi_at_tract.csv (~90 MB, header row)
    tract,state_abbr,year,annual_change,hpi,hpi1990,hpi2000   (empty = not computed)
County, ZIP3 and ZIP5 annual indexes are published only as .xlsx (the .csv URLs serve xlsx bytes), so they
are not served here.
"""

from __future__ import annotations

from ._common import scan_csv, state_abbr
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

MASTER = "https://www.fhfa.gov/hpi/download/monthly/hpi_master.csv"
TRACT = "https://www.fhfa.gov/hpi/download/annual/hpi_at_tract.csv"
LEVELS = {"us": "USA or Census Division", "division": "USA or Census Division", "state": "State", "metro": "MSA",
          "puerto_rico": "Puerto Rico", "tract": None}
TYPES = ["traditional", "distress-free", "non-metro", "manufactured", "developmental"]
FLAVORS = ["purchase-only", "all-transactions", "expanded-data"]
MASTER_COLS = ["hpi_type", "hpi_flavor", "frequency", "level", "place_name", "place_id", "yr", "period",
               "index_nsa", "index_sa", "rstderr", "note"]
TRACT_COLS = ["tract", "state_abbr", "year", "annual_change", "hpi", "hpi1990", "hpi2000"]


def _f(v):
    v = (v or "").strip()
    if v in ("", "-", "."):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _metro_states(name: str) -> set[str]:
    # "Allentown-Bethlehem-Easton, PA-NJ" / "Anaheim-Santa Ana-Irvine, CA (MSAD)" -> {"PA","NJ"} / {"CA"}
    if "," not in name:
        return set()
    tail = name.rsplit(",", 1)[1].split("(")[0].strip()
    return {s.strip() for s in tail.split("-") if s.strip()}


def _assert_ca_boom(rows: list[dict]) -> None:
    by = {r["yr"]: r["index_nsa"] for r in rows if r["period"] == 4}
    assert by.get(2005) and by.get(2011) and by[2005] > by[2011] * 1.25, f"CA 2005Q4 vs 2011Q4 bust not visible: {by}"


class FhfaHpi(SourceAdapter):
    source_id = "fhfa-hpi"
    version = "1.0.0"
    usage = ("Repeat-sales house price indexes. level us/division/state/metro/puerto_rico read the FHFA HPI master "
             "file: one row per place x period, with index_nsa / index_sa (seasonally adjusted, purchase-only only). "
             "Choose flavor (all-transactions = default, longest history incl. refinance appraisals; purchase-only = "
             "sales only; expanded-data adds FHA and county-recorder sales) and frequency (quarterly; monthly only for "
             "purchase-only US/divisions). level=tract returns FHFA's annual tract indexes (~90 MB file; pass state). "
             "Index levels are relative to each place's own base period — compare growth rates, not levels across places.")
    filters = [
        FilterSpec("level", "string", "Geography: us, division (census divisions), state, metro (CBSA/metro division), puerto_rico, tract (annual).",
                   enum=sorted(LEVELS), default="state"),
        FilterSpec("flavor", "string", "Index flavor (master-file levels): all-transactions (default), purchase-only, expanded-data.",
                   enum=FLAVORS, default="all-transactions"),
        FilterSpec("frequency", "string", "quarterly (default) or monthly (purchase-only, us/division only).",
                   enum=["quarterly", "monthly"], default="quarterly"),
        FilterSpec("hpi_type", "string", "traditional (default), distress-free (some large metros), non-metro (state non-metro areas), "
                   "manufactured (US manufactured homes), developmental (Puerto Rico; default there).", enum=TYPES),
        FilterSpec("state", "string", "Postal code or FIPS. For metro, keeps metros whose name lists the state; for tract, the state's tracts.",
                   example="CA"),
        FilterSpec("place_id", "string_list", "FHFA place ids: 'USA', 'DV_PAC' (division), state postal code, or CBSA/MSAD code e.g. '31080'."),
        FilterSpec("county_fips", "string", "level=tract only: 5-digit county FIPS prefix of the tract code, e.g. '06037'."),
        FilterSpec("year", "integer", "Single year."),
        FilterSpec("start_year", "integer", "First year to return."),
        FilterSpec("end_year", "integer", "Last year to return."),
    ]
    contract = [
        ContractCase(
            name="california_at_quarterly_2005_2011",
            filters={"level": "state", "state": "CA", "start_year": 2005, "end_year": 2011},
            min_rows=28, max_rows=28,
            required_columns=["place_id", "place_name", "yr", "period", "index_nsa", "hpi_flavor"],
            checks=[Check("place_id", one_of=["CA"]), Check("index_nsa", numeric=True, min=100, max=1500),
                    Check("hpi_flavor", one_of=["all-transactions"])],
            custom=_assert_ca_boom,
            limit=100,
        ),
        ContractCase(
            name="us_purchase_only_monthly_2020",
            filters={"level": "us", "flavor": "purchase-only", "frequency": "monthly", "year": 2020},
            min_rows=12, max_rows=12,
            required_columns=["index_nsa", "index_sa", "period"],
            checks=[Check("index_sa", numeric=True, min=150, max=600), Check("period", numeric=True, min=1, max=12),
                    Check("place_id", one_of=["USA"])],
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        level = f.get("level", "state")
        st = state_abbr(f["state"]) if f.get("state") else None
        ids = set(f.get("place_id") or [])
        y0 = f.get("start_year", f.get("year"))
        y1 = f.get("end_year", f.get("year"))

        def in_years(y: int) -> bool:
            return (y0 is None or y >= y0) and (y1 is None or y <= y1)

        if level == "tract":
            return self._tract(f, st, in_years, limit, cache_allowed)
        if f.get("county_fips"):
            raise FilterError("county_fips applies only to level='tract'")
        lvl = LEVELS[level]
        htype = f.get("hpi_type") or ("developmental" if level == "puerto_rico" else "traditional")
        flavor = f.get("flavor", "all-transactions")
        freq = f.get("frequency", "quarterly")
        if st and level not in ("state", "metro"):
            raise FilterError("state applies to level state, metro or tract")

        def keep(r: dict) -> bool:
            if r["level"] != lvl or r["hpi_type"] != htype or r["hpi_flavor"] != flavor or r["frequency"] != freq:
                return False
            pid = r["place_id"]
            if level == "us" and pid != "USA":
                return False
            if level == "division" and not pid.startswith("DV_"):
                return False
            if ids and pid not in ids:
                return False
            if st and level == "state" and pid != st:
                return False
            if st and level == "metro" and st not in _metro_states(r["place_name"]):
                return False
            try:
                return in_years(int(r["yr"]))
            except ValueError:
                return False

        def shape(r: dict) -> dict:
            return {"hpi_type": r["hpi_type"], "hpi_flavor": r["hpi_flavor"], "frequency": r["frequency"],
                    "level": r["level"], "place_name": r["place_name"], "place_id": r["place_id"],
                    "yr": int(r["yr"]), "period": int(r["period"]), "index_nsa": _f(r["index_nsa"]),
                    "index_sa": _f(r["index_sa"]), "rstderr": _f(r["rstderr"]), "note": (r.get("note") or "").strip() or None}

        rows, matched = scan_csv(MASTER, cache_allowed=cache_allowed, predicate=keep, limit=limit,
                                 columns=MASTER_COLS, transform=shape, max_age_s=7 * 86400)
        notes = ["Index values are relative to each series' base period (=100); compare percent changes, not levels across places.",
                 "Empty index cells (too few repeat sales, or no seasonal adjustment for this flavor) are returned as null."]
        if not rows:
            notes.append(f"No rows: check the combination level={level}, hpi_type={htype}, flavor={flavor}, frequency={freq} "
                         "(e.g. monthly exists only for purchase-only us/division; expanded-data only for us/division/state/metro).")
        return FetchResult(rows, [MASTER], notes, total_available=matched,
                           metadata={"hpi_type": htype, "flavor": flavor, "frequency": freq, "level": level})

    def _tract(self, f, st, in_years, limit, cache_allowed) -> FetchResult:
        cty = (f.get("county_fips") or "").strip()
        if cty and (len(cty) != 5 or not cty.isdigit()):
            raise FilterError("county_fips must be 5 digits, e.g. '06037'")
        ids = set(f.get("place_id") or [])
        if not (st or cty or ids):
            raise FilterError("level='tract' needs state, county_fips or place_id (11-digit tract codes) — the national file has ~2 million rows")

        def keep(r: dict) -> bool:
            if st and r["state_abbr"] != st:
                return False
            if cty and not r["tract"].startswith(cty):
                return False
            if ids and r["tract"] not in ids:
                return False
            try:
                return in_years(int(r["year"]))
            except ValueError:
                return False

        def shape(r: dict) -> dict:
            return {"tract": r["tract"], "state_abbr": r["state_abbr"], "year": int(r["year"]),
                    "annual_change": _f(r["annual_change"]), "hpi": _f(r["hpi"]),
                    "hpi1990": _f(r["hpi1990"]), "hpi2000": _f(r["hpi2000"])}

        rows, matched = scan_csv(TRACT, cache_allowed=cache_allowed, predicate=keep, limit=limit,
                                 columns=TRACT_COLS, transform=shape, max_age_s=30 * 86400)
        require(matched > 0 or not st, f"{TRACT}: no tracts for state {st}", kind="empty")
        notes = ["Annual tract indexes are developmental: hpi = base year is the tract's first year (=100); hpi1990/hpi2000 rebased "
                 "to 1990/2000 where available. Empty cells (too few sales) are null.",
                 "Tract codes are 11-digit 2020-vintage census tracts (e.g. Connecticut uses planning-region county codes 091xx)."]
        return FetchResult(rows, [TRACT], notes, total_available=matched, metadata={"level": "tract"})


ADAPTER = FhfaHpi()
