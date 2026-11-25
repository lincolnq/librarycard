"""County Business Patterns (bulk files on www2.census.gov). Catalog: catalog/census-cbp.yaml

Layout (checked 2026-11-24):
  https://www2.census.gov/programs-surveys/cbp/datasets/<YYYY>/cbp<yy><level>.zip
    level: us (national, by legal form of organization), st (state, by LFO), co (county), msa (metro/micro)
  Each zip holds one quoted CSV (cbp<yy><level>.txt). Header (2017+ county file):
    fipstate,fipscty,naics,emp_nf,emp,qp1_nf,qp1,ap_nf,ap,est,n<5,n5_9,...,n1000_4
  State/US files add lfo and per-size-class e*/q*/a* columns; MSA files key on msa.
  cbp15us.txt has upper-case headers (normalised to lower case here).
  2008-2016 files add `empflag` (A-M size-range code when emp/payroll are withheld; emp/qp1/ap = 0 then)
  and per-size-class `f*` flags. 2017+ files use noise flags (*_nf: G low, H moderate, J high noise) and
  no withholding. "N" in size-class columns = not available. County code 999 = "statewide" (establishments
  with no fixed county location).
NAICS codes use "-" / "/" padding: "------" all sectors, "23----" sector, "236///" subsector,
"2361//" industry group, "23611/" industry, "236115" national industry.
"""

from __future__ import annotations

import csv
import datetime as dt

from .. import http
from ..http import SourceError
from ._common import scan_csv, state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

BASE = "https://www2.census.gov/programs-surveys/cbp/datasets"
FIRST_YEAR = 2008
LEVELS = {"us": "us", "state": "st", "county": "co", "msa": "msa"}
CORE = ["emp_nf", "emp", "qp1_nf", "qp1", "ap_nf", "ap", "est"]
FLAG_COLS = {"emp_nf", "qp1_nf", "ap_nf", "empflag", "lfo", "naics", "fipstate", "fipscty", "msa", "uscode",
             "censtate", "cencty"}
LFO = {"-": "All establishments", "C": "C-corporations", "Z": "S-corporations", "S": "Sole proprietorships",
       "P": "Partnerships", "N": "Non-profits", "G": "Government", "O": "Other"}

_latest: list[int] = []


def _url(year: int, level: str) -> str:
    return f"{BASE}/{year}/cbp{year % 100:02d}{LEVELS[level]}.zip"


def latest_year() -> int:
    if _latest:
        return _latest[0]
    for y in range(dt.date.today().year, FIRST_YEAR - 1, -1):
        try:
            http.head(_url(y, "us"))
            _latest.append(y)
            return y
        except SourceError:
            continue
    raise SourceError("no County Business Patterns release found", kind="http")


def naics_code(v: str) -> str:
    """'23' -> '23----', '236' -> '236///', 'total'/'00' -> '------'; published forms pass through."""
    s = str(v).strip().lower()
    if s in ("total", "all", "00", "------", ""):
        return "------"
    s = s.rstrip("-/")
    if "-" in s:  # e.g. '31-33' sector ranges are published as '31----'
        s = s.split("-", 1)[0]
    if not s.isdigit() or not 2 <= len(s) <= 6:
        raise FilterError(f"bad NAICS code {v!r}; use 2-6 digits like '23', '236', '236115', or 'total'")
    return s + "-" * 4 if len(s) == 2 else s + "/" * (6 - len(s))


def naics_depth(code: str) -> int:
    return 0 if code == "------" else len(code.rstrip("-/"))


def _lower_keys(r: dict) -> None:
    """Some files use upper-case headers (2015 us: USCODE,NAICS,...); normalise in place to the usual lower case."""
    if "naics" not in r and "NAICS" in r:
        for k in list(r):
            r[k.lower()] = r.pop(k)


def _num(v):
    if v is None:
        return None
    v = v.strip()
    if v in ("", "N", "D", "S"):
        return None
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


class CensusCbp(SourceAdapter):
    source_id = "census-cbp"
    version = "1.1.1"
    usage = ("One row per area x NAICS code (x legal form of organization for level us/state): establishments (est), "
             "mid-March employment (emp), Q1 payroll (qp1) and annual payroll (ap), both in $1,000. Pick a level "
             "(county, state, msa, us), a year (default latest), and narrow with state / county_fips / naics. "
             "NAICS 'total' (code '------') is all industries; naics_depth=2 returns every sector. County files are "
             "~110 MB unzipped, so always pass state or county_fips when you can.")
    filters = [
        FilterSpec("level", "string", "Geography: county (default), state, msa (metro/micro area) or us.",
                   enum=sorted(LEVELS), default="county"),
        FilterSpec("year", "integer", f"Reference year ({FIRST_YEAR} or later). Default: latest published.", example=2023),
        FilterSpec("state", "string", "Postal code or FIPS (county/state levels).", example="DE"),
        FilterSpec("county_fips", "string", "5-digit county FIPS (or 3-digit with state), e.g. '10003'. County level only."),
        FilterSpec("msa", "string_list", "CBSA code(s) for level=msa, e.g. ['35620'] (New York metro)."),
        FilterSpec("naics", "string_list", "NAICS code(s): 'total', 2-6 digits ('23', '236', '236115') or published form ('23----').",
                   example=["total"]),
        FilterSpec("naics_depth", "integer", "Only return NAICS codes of this many digits (0 = total, 2 = sectors, ... 6)."),
        FilterSpec("lfo", "string", "Legal form of organization (state/us levels): '-' all (default), C, Z, S, P, N, G, O.",
                   enum=sorted(LFO), default="-"),
        FilterSpec("include_size_classes", "boolean", "Also return establishment counts (and for state/us, employment/payroll) by employment-size class.",
                   default=False),
    ]
    contract = [
        ContractCase(
            name="delaware_counties_total_2022",
            filters={"level": "county", "year": 2022, "state": "DE", "naics": ["total"]},
            min_rows=3, max_rows=4,
            required_columns=["fips", "fipstate", "fipscty", "naics", "est", "emp", "ap", "emp_nf"],
            checks=[Check("fipstate", one_of=["10"]), Check("est", numeric=True, min=100, max=50000),
                    Check("emp", numeric=True, min=0, max=500000), Check("emp_nf", one_of=["G", "H", "J"])],
            limit=20,
        ),
        ContractCase(
            name="us_sectors_2021",
            filters={"level": "us", "year": 2021, "naics_depth": 2},
            min_rows=18, max_rows=25,
            required_columns=["naics", "est", "emp", "ap", "lfo"],
            checks=[Check("emp", numeric=True, min=10000, max=30_000_000), Check("naics", regex=r"\d\d----")],
            custom=lambda rows: _assert_us_total(rows),
            limit=50,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        url, keep, shape, notes, meta = self._prepare(f)
        try:
            rows, matched = scan_csv(url, cache_allowed=cache_allowed, predicate=keep, limit=limit,
                                     transform=shape, max_age_s=30 * 86400)
        except SourceError as e:
            if e.status == 404:
                raise FilterError(f"no CBP {meta['level']} file for {meta['year']} ({url}); the latest year may not be released yet") from None
            raise
        if rows:
            require("naics" in rows[0] and "est" in rows[0], f"{url}: expected naics/est columns, got {list(rows[0])[:15]}")
        return FetchResult(rows, [url], notes, total_available=matched, metadata=meta)

    def _prepare(self, f: dict, all_lfo: bool = False):
        """Validate filters and return (url, keep, shape, notes, metadata). all_lfo=True keeps every legal form
        of organization (used by the mirror, which stores all rows)."""
        level = f.get("level", "county")
        year = f.get("year") or latest_year()
        if year < FIRST_YEAR:
            raise FilterError(f"this adapter serves {FIRST_YEAR}+ (NAICS-2007-or-later layouts); earlier years are on {BASE}/")
        st = state_fips(f["state"]) if f.get("state") else None
        cty = None
        if f.get("county_fips"):
            if level != "county":
                raise FilterError("county_fips requires level='county'")
            c = f["county_fips"].strip()
            if len(c) == 5 and c.isdigit():
                if st and c[:2] != st:
                    raise FilterError("county_fips does not lie in the given state")
                st, cty = c[:2], c[2:]
            elif len(c) == 3 and c.isdigit() and st:
                cty = c
            else:
                raise FilterError("county_fips must be 5 digits (e.g. '10003') or 3 digits together with state")
        if st and level not in ("county", "state"):
            raise FilterError("state applies only to level county or state (for metros use msa codes)")
        msas = set(f.get("msa") or [])
        if msas and level != "msa":
            raise FilterError("msa requires level='msa'")
        naics = {naics_code(n) for n in (f.get("naics") or [])}
        depth = f.get("naics_depth")
        if depth is not None and depth not in (0, 2, 3, 4, 5, 6):
            raise FilterError("naics_depth must be 0, 2, 3, 4, 5 or 6")
        lfo = f.get("lfo", "-")

        def keep(r: dict) -> bool:
            _lower_keys(r)
            if st and r.get("fipstate") != st:
                return False
            if cty and r.get("fipscty") != cty:
                return False
            if msas and r.get("msa") not in msas:
                return False
            code = r.get("naics", "")
            if naics and code not in naics:
                return False
            if depth is not None and naics_depth(code) != depth:
                return False
            if not all_lfo and "lfo" in r and r["lfo"] != lfo:
                return False
            return True

        sizes = f.get("include_size_classes", False)

        def shape(r: dict) -> dict:
            withheld = bool((r.get("empflag") or "").strip())
            out: dict = {}
            if level == "county":
                out["fips"] = r["fipstate"] + r["fipscty"]
            for k, v in r.items():
                if k in FLAG_COLS:
                    if k in ("censtate", "cencty"):
                        continue
                    out[k] = (v or "").strip() or None
                elif k in CORE or sizes:
                    out[k] = None if (withheld and k in ("emp", "qp1", "ap")) else _num(v)
            out["year"] = year
            return out

        url = _url(year, level)
        notes = ["emp = mid-March employment; qp1 = first-quarter payroll and ap = annual payroll, both in $1,000.",
                 "Size-class 'N' (not available) values are returned as null."]
        if year >= 2018:
            notes.append("2018 on: values are noise-infused; *_nf flags give noise level (G <2%, H 2-5%, J >=5%). Cells with fewer than 3 establishments are not published (rows absent).")
        else:
            notes.append("Before 2018: where empflag is set, emp/qp1/ap were withheld to avoid disclosure and are returned as null "
                         "(empflag gives the employment size range).")
        if level == "county":
            notes.append("fipscty '999' = statewide establishments with no fixed county location.")
        return url, keep, shape, notes, {"year": year, "level": level}

    # -------------------------------------------------------- mirror
    # Everything the adapter serves: every year FIRST_YEAR..latest x level, all NAICS codes, all legal forms of
    # organization (us/state files), with size-class columns. Partitioned by year, level and state (fipstate; empty
    # for us/msa). Rows gain a `level` column. A county file has ~1-2M rows, so rows are streamed, not listed.
    mirror_partition_keys = ["year", "level", "fipstate"]
    mirror_semantics = {"fipstate": "state_fips", "fips": "county_fips", "year": "year"}

    def mirror_plan(self):
        from ..mirror import MirrorUnit
        for year in range(FIRST_YEAR, latest_year() + 1):
            for level in ("us", "state", "county", "msa"):
                by_state = level in ("state", "county")
                yield MirrorUnit(partition={"year": str(year), "level": level, **({} if by_state else {"fipstate": ""})},
                                 filters={"year": year, "level": level, "include_size_classes": True},
                                 split_by=["fipstate"] if by_state else [])

    def mirror_rows(self, unit):
        f = self.validate_filters(unit.filters)
        url, keep, shape, notes, meta = self._prepare(f, all_lfo=True)
        level = meta["level"]
        if level in ("us", "state"):
            notes = notes + ["level us/state: rows for every legal form of organization (lfo '-' = all establishments, "
                             "C, Z, S, P, N, G, O); filter lfo='-' for totals."]

        def rows():
            with http.download(url, cache_allowed=True, max_age_s=30 * 86400) as path:
                with http.open_text(path) as fh:
                    reader = csv.DictReader(fh)
                    reader.fieldnames = [c.strip().lower() for c in reader.fieldnames or []]
                    require("naics" in reader.fieldnames and "est" in reader.fieldnames,
                            f"{url}: expected naics/est columns, got {reader.fieldnames[:15]}")
                    n = 0
                    for r in reader:
                        if keep(r):
                            n += 1
                            yield {"level": level, **shape(r)}
                    require(n > 0, f"{url}: no rows")

        return rows(), [url], notes, {}


def _assert_us_total(rows: list[dict]) -> None:
    total = sum(r["emp"] or 0 for r in rows)
    assert 100_000_000 < total < 160_000_000, f"sum of 2021 sector employment {total} outside 100-160 million"


ADAPTER = CensusCbp()
