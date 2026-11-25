"""LEHD Origin-Destination Employment Statistics, LODES 8. Catalog: catalog/lehd-lodes.yaml

Layout (checked 2026-11-24): https://lehd.ces.census.gov/data/lodes/LODES8/<st>/
  od/<st>_od_<main|aux>_<JT>_<year>.csv.gz     w_geocode,h_geocode,S000,SA01..SI03,createdate
  rac/<st>_rac_<SEG>_<JT>_<year>.csv.gz        h_geocode,C000,CA01..CFS05,createdate
  wac/<st>_wac_<SEG>_<JT>_<year>.csv.gz        w_geocode,C000,CA01..CFS05,createdate
  <st>_xwalk.csv.gz (block -> higher geographies), version.txt
  st = lowercase postal code; geocodes are 15-digit 2020 census blocks (state2 county3 tract6 block4).
  OD 'main' = both ends in the state; 'aux' = worker lives out of state. Segments: S000 all, SA01-03 age,
  SE01-03 earnings, SI01-03 industry; job types JT00 all .. JT05 federal primary. Some segment/job-type/year
  combinations do not exist (404) -> FilterError. Years 2002-2024 for most states.
"""

from __future__ import annotations

import csv
import datetime as dt
import re

from .. import http
from ..http import SourceError
from ._common import state_abbr
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

BASE = "https://lehd.ces.census.gov/data/lodes/LODES8"
TYPES = ["od", "rac", "wac"]
SEGMENTS = ["S000", "SA01", "SA02", "SA03", "SE01", "SE02", "SE03", "SI01", "SI02", "SI03"]
JOB_TYPES = ["JT00", "JT01", "JT02", "JT03", "JT04", "JT05"]
AGG = {"block": 15, "block_group": 12, "tract": 11, "county": 5, "state": 2}
FIRST_YEAR = 2002

_latest: dict[tuple, int] = {}


def file_url(st: str, ftype: str, seg: str, jt: str, year: int, od_part: str) -> str:
    mid = od_part if ftype == "od" else seg
    return f"{BASE}/{st}/{ftype}/{st}_{ftype}_{mid}_{jt}_{year}.csv.gz"


def latest_year(st: str, ftype: str, seg: str, jt: str, od_part: str) -> int:
    key = (st, ftype, seg, jt, od_part)
    if key not in _latest:
        for y in range(dt.date.today().year, FIRST_YEAR - 1, -1):
            try:
                http.head(file_url(st, ftype, seg, jt, y, od_part))
                _latest[key] = y
                break
            except SourceError:
                continue
        else:
            raise FilterError(f"no LODES8 {ftype} file for {st.upper()} {seg} {jt}; see {BASE}/{st}/{ftype}/")
    return _latest[key]


def _assert_de_total(rows: list[dict]) -> None:
    total = sum(r["C000"] for r in rows)
    assert 350_000 < total < 550_000, f"Delaware 2021 primary+secondary jobs {total} outside 350k-550k"


class LehdLodes(SourceAdapter):
    source_id = "lehd-lodes"
    version = "1.1.0"
    usage = ("Census-block job counts for one state and year. file_type wac = jobs by workplace block, rac = jobs by "
             "residence block (columns C000 total, CA01-03 age, CE01-03 earnings, CNS01-20 NAICS sector, CR/CT race/"
             "ethnicity, CD education, CS sex, CFA/CFS firm age/size), od = home-work block pairs (S000 and segment "
             "counts). Use aggregate='tract' or 'county' to sum blocks (strongly recommended for od). Counts are "
             "noise-protected synthetic data: small cells are unreliable, aggregate before analysing.")
    filters = [
        FilterSpec("state", "string", "Postal code or FIPS (one state per call).", required=True, example="DE"),
        FilterSpec("file_type", "string", "wac (workplace area), rac (residence area) or od (origin-destination pairs).",
                   enum=TYPES, default="wac"),
        FilterSpec("year", "integer", f"Year ({FIRST_YEAR}-latest; jobs as of the 2nd quarter). Default: latest available.", example=2021),
        FilterSpec("segment", "string", "Worker segment for wac/rac: S000 all (default), SA01-03 age, SE01-03 earnings, SI01-03 industry group.",
                   enum=SEGMENTS, default="S000"),
        FilterSpec("job_type", "string", "JT00 all jobs (default), JT01 primary, JT02 all private, JT03 private primary, "
                   "JT04 all federal, JT05 federal primary.", enum=JOB_TYPES, default="JT00"),
        FilterSpec("od_part", "string", "od only: main (home and work both in state, default) or aux (home out of state).",
                   enum=["main", "aux"], default="main"),
        FilterSpec("aggregate", "string", "Sum blocks to block_group, tract, county or state (default: block, no aggregation).",
                   enum=sorted(AGG), default="block"),
        FilterSpec("county_fips", "string", "5-digit county FIPS: keep blocks in this county (workplace side for od).", example="10003"),
        FilterSpec("home_county_fips", "string", "od only: 5-digit county FIPS of the residence block."),
    ]
    contract = [
        ContractCase(
            name="delaware_wac_counties_2021",
            filters={"state": "DE", "file_type": "wac", "year": 2021, "aggregate": "county"},
            min_rows=3, max_rows=3,
            required_columns=["w_geocode", "C000", "CNS01", "CE03", "block_count"],
            checks=[Check("w_geocode", one_of=["10001", "10003", "10005"]), Check("C000", numeric=True, min=50_000, max=400_000)],
            custom=_assert_de_total,
        ),
        ContractCase(
            name="rhode_island_rac_blocks_2020",
            filters={"state": "RI", "file_type": "rac", "year": 2020, "segment": "SE03", "job_type": "JT01"},
            min_rows=50,
            required_columns=["h_geocode", "C000", "CA01", "createdate"],
            checks=[Check("h_geocode", regex=r"44\d{13}"), Check("C000", numeric=True, min=0, max=5000)],
            limit=50,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        st = state_abbr(f["state"]).lower()
        ftype = f.get("file_type", "wac")
        seg = f.get("segment", "S000")
        jt = f.get("job_type", "JT00")
        part = f.get("od_part", "main")
        agg = f.get("aggregate", "block")
        if ftype == "od" and seg != "S000":
            raise FilterError("segment applies to wac/rac; od files carry all segment columns (SA01..SI03) in every row")
        cty = (f.get("county_fips") or "").strip()
        hcty = (f.get("home_county_fips") or "").strip()
        for c in (cty, hcty):
            if c and (len(c) != 5 or not c.isdigit()):
                raise FilterError("county_fips / home_county_fips must be 5 digits, e.g. '10003'")
        if hcty and ftype != "od":
            raise FilterError("home_county_fips applies only to file_type='od' (for rac use county_fips)")
        year = f.get("year") or latest_year(st, ftype, seg, jt, part)
        if year < FIRST_YEAR:
            raise FilterError(f"LODES8 starts in {FIRST_YEAR}")
        url = file_url(st, ftype, seg, jt, year, part)
        geo_cols = ["w_geocode", "h_geocode"] if ftype == "od" else (["w_geocode"] if ftype == "wac" else ["h_geocode"])
        n = AGG[agg]
        out: list[dict] = []
        groups: dict[tuple, dict] = {}
        matched = 0
        try:
            with http.download(url, cache_allowed=cache_allowed) as path, http.open_text(path, encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                header = reader.fieldnames or []
                require(all(g in header for g in geo_cols) and ("C000" in header or "S000" in header),
                        f"{url}: unexpected header {header[:8]}")
                num_cols = [h for h in header if h not in geo_cols and h != "createdate"]
                for r in reader:
                    g0 = r[geo_cols[0]]
                    if cty and not g0.startswith(cty):
                        continue
                    if hcty and not r["h_geocode"].startswith(hcty):
                        continue
                    if agg == "block":
                        matched += 1
                        if len(out) < limit:
                            rec = {g: r[g] for g in geo_cols}
                            rec.update({c: int(r[c]) for c in num_cols})
                            rec["createdate"] = r.get("createdate")
                            out.append(rec)
                        continue
                    key = tuple(r[g][:n] for g in geo_cols)
                    acc = groups.get(key)
                    if acc is None:
                        acc = groups[key] = {**dict(zip(geo_cols, key)), **{c: 0 for c in num_cols}, "block_count": 0}
                    for c in num_cols:
                        acc[c] += int(r[c])
                    acc["block_count"] += 1
        except SourceError as e:
            if e.status == 404:
                raise FilterError(f"no LODES8 file {url} — that year/segment/job type is not published for "
                                  f"{st.upper()} (see {BASE}/{st}/{ftype}/)") from None
            raise
        except ValueError as e:
            raise SourceError(f"{url}: non-integer count ({e})", kind="parse", url=url) from None
        if agg != "block":
            matched = len(groups)
            out = [groups[k] for k in sorted(groups)][:limit]
        notes = [f"LODES8 {ftype.upper()} {st.upper()} {year}, segment {seg if ftype != 'od' else 'all (columns)'}, {jt}; "
                 "jobs are beginning-of-2nd-quarter (about April 1) jobs, by 2020 census block.",
                 "Counts are noise-infused / synthetic (od) for confidentiality; small-area values are approximate."]
        if agg != "block":
            notes.append(f"Blocks summed to {agg} (first {n} digits of each geocode); 'block_count' = number of source rows summed (non-empty blocks; block pairs for od). "
                         "Only blocks with at least one job appear in the files.")
        if ftype == "od" and part == "aux":
            notes.append("od aux: workplace in this state, residence in another state.")
        return FetchResult(out, [url], notes, total_available=matched,
                           metadata={"year": year, "file_type": ftype, "segment": seg, "job_type": jt, "aggregate": agg})


    # Mirror (measured 2026-11-25 on the 2024 files): WAC+RAC for every segment and job type would be ~240M rows and
    # ~9 GB as NDJSON gzip (2x the publisher's 4.5 GB of csv.gz; DE alone 0.77M rows / 28 MB, CA ~23M rows / ~850 MB)
    # and take 4-5 hours to ingest single-threaded, beyond the mirror workflow's time and disk budget. So the mirror
    # holds the latest year's WAC and RAC for segment S000 (all workers; the age/earnings/industry breakdowns are still
    # columns CA*/CE*/CNS*) and job type JT00 (all jobs), every state, at census-block level as published. Widen with
    # MIRROR_SEGMENTS / MIRROR_JOB_TYPES once ingest can be chunked; partition keys already include both.
    # OD is not mirrored: its 2024 files alone are ~2.8 GB of csv.gz (~5.6 GB as NDJSON gzip).
    # Rows gain state, file_type, segment, job_type, year and county_fips (first 5 digits of the block geocode).
    mirror_partition_keys = ["state", "file_type", "segment", "job_type"]
    mirror_required = ["state"]
    mirror_semantics = {"state": "state_postal", "county_fips": "county_fips"}
    MIRROR_TYPES = ("wac", "rac")
    MIRROR_SEGMENTS = ("S000",)
    MIRROR_JOB_TYPES = ("JT00",)

    def mirror_plan(self):
        from concurrent.futures import ThreadPoolExecutor

        from ..mirror import MirrorUnit
        from ._common import STATE_FIPS
        states = sorted(s.lower() for s, f in STATE_FIPS.items() if int(f) <= 56)  # 50 states + DC; no PR in LODES
        dirs = [(st, ftype) for st in states for ftype in self.MIRROR_TYPES]

        def listing(d):
            st, ftype = d
            html = http.get_text(f"{BASE}/{st}/{ftype}/")
            pat = rf'href="{st}_{ftype}_(S\d{{3}}|S[AEI]\d\d)_(JT0\d)_(\d{{4}})\.csv\.gz"'
            return {(seg, jt, int(y)) for seg, jt, y in re.findall(pat, html)}

        with ThreadPoolExecutor(8) as pool:
            files = dict(zip(dirs, pool.map(listing, dirs)))
        year = max(y for fs in files.values() for _, _, y in fs)
        for (st, ftype), fs in files.items():
            for seg in self.MIRROR_SEGMENTS:
                for jt in self.MIRROR_JOB_TYPES:
                    if (seg, jt, year) in fs:
                        yield MirrorUnit(partition={"state": st.upper(), "file_type": ftype, "segment": seg, "job_type": jt},
                                         filters={"state": st, "file_type": ftype, "segment": seg, "job_type": jt, "year": year})

    def mirror_rows(self, unit):
        f = unit.filters
        st, ftype, seg, jt, year = f["state"], f["file_type"], f["segment"], f["job_type"], f["year"]
        url = file_url(st, ftype, seg, jt, year, "main")
        geo = "w_geocode" if ftype == "wac" else "h_geocode"
        fixed = {"state": st.upper(), "file_type": ftype, "segment": seg, "job_type": jt, "year": year}

        def rows():
            with http.download(url, cache_allowed=True) as path, http.open_text(path, encoding="utf-8") as fh:
                reader = csv.reader(fh)
                header = next(reader, [])
                require(header[:1] == [geo] and "C000" in header and header[-1] == "createdate",
                        f"{url}: unexpected header {header[:8]}")
                num = header[1:-1]
                for r in reader:
                    if not r:
                        continue
                    try:
                        rec = {**fixed, "county_fips": r[0][:5], geo: r[0]}
                        rec.update(zip(num, map(int, r[1:-1])))
                    except ValueError as e:
                        raise SourceError(f"{url}: non-integer count ({e})", kind="parse", url=url) from None
                    rec["createdate"] = r[-1]
                    yield rec

        notes = [f"LODES8 WAC (jobs by workplace block) and RAC (jobs by residence block), {year}, every state, segment "
                 f"{'/'.join(self.MIRROR_SEGMENTS)}, job type {'/'.join(self.MIRROR_JOB_TYPES)}, by 2020 census block "
                 "as published. `state`, `file_type`, `segment`, `job_type`, `year` and `county_fips` (first 5 digits "
                 "of the geocode) are added by the mirror.",
                 "Jobs are beginning-of-2nd-quarter (about April 1) jobs. Counts are noise-infused for confidentiality; "
                 "small-area values are approximate. Only blocks with at least one job appear.",
                 "Not mirrored: earlier years, other segments (SA01-SI03) and job types (JT01-JT05), and OD "
                 "(origin-destination) files; fetch those from the publisher via the local odc-server."]
        return rows(), [url], notes, {"year": year}


ADAPTER = LehdLodes()
