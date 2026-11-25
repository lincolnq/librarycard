"""2020 Census Redistricting Data (Public Law 94-171) Summary File. Catalog: catalog/census-decennial-2020-pl.yaml

Bulk files on www2.census.gov, one zip per state (legacy "logical record" format, pipe-delimited, no header):
  /programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/<State_Name>/<st>2020.pl.zip
    <st>geo2020.pl      geographic header: 97 fields, one record per geography (LOGRECNO is the join key), latin-1
    <st>000012020.pl    segment 1: FILEID|STUSAB|CHARITER|CIFSN|LOGRECNO + P1 (71 cells) + P2 (73 cells)
    <st>000022020.pl    segment 2: key fields + P3 (71) + P4 (73) + H1 (3)
    <st>000032020.pl    segment 3: key fields + P5 (10)
Field names come from the Census R import scripts (Phase3/SupportMaterials/2020PL_R_import_scripts.zip), which the
adapter also reads at run time for cell labels (metadata.variable_labels). Zips range from ~2 MB (WY) to ~100 MB
(TX); they are cached for 180 days because the 2020 release is final.

Mirror (docs/MIRROR.md): one unit per state, rows streamed (geo header and the three segments are read in lock-step
by LOGRECNO, so memory stays flat), partitioned by state and summary level (`geography`), with every table (P1-P5,
H1). MIRROR_GEOGRAPHIES lists the summary levels mirrored: every level except blocks (see the comment there).
"""

from __future__ import annotations

import io
import re
import zipfile

from .. import http
from ..http import SourceError
from ._common import FIPS_STATE, state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

BASE = "https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/"
R_SCRIPTS = ("https://www2.census.gov/programs-surveys/decennial/rdo/about/2020-census-program/Phase3/"
             "SupportMaterials/2020PL_R_import_scripts.zip")

STATE_DIRS = {
    "01": "Alabama", "02": "Alaska", "04": "Arizona", "05": "Arkansas", "06": "California", "08": "Colorado",
    "09": "Connecticut", "10": "Delaware", "11": "District_of_Columbia", "12": "Florida", "13": "Georgia",
    "15": "Hawaii", "16": "Idaho", "17": "Illinois", "18": "Indiana", "19": "Iowa", "20": "Kansas", "21": "Kentucky",
    "22": "Louisiana", "23": "Maine", "24": "Maryland", "25": "Massachusetts", "26": "Michigan", "27": "Minnesota",
    "28": "Mississippi", "29": "Missouri", "30": "Montana", "31": "Nebraska", "32": "Nevada", "33": "New_Hampshire",
    "34": "New_Jersey", "35": "New_Mexico", "36": "New_York", "37": "North_Carolina", "38": "North_Dakota",
    "39": "Ohio", "40": "Oklahoma", "41": "Oregon", "42": "Pennsylvania", "44": "Rhode_Island", "45": "South_Carolina",
    "46": "South_Dakota", "47": "Tennessee", "48": "Texas", "49": "Utah", "50": "Vermont", "51": "Virginia",
    "53": "Washington", "54": "West_Virginia", "55": "Wisconsin", "56": "Wyoming", "72": "Puerto_Rico",
}

GEO_FIELDS = [
    "FILEID", "STUSAB", "SUMLEV", "GEOVAR", "GEOCOMP", "CHARITER", "CIFSN", "LOGRECNO", "GEOID", "GEOCODE", "REGION",
    "DIVISION", "STATE", "STATENS", "COUNTY", "COUNTYCC", "COUNTYNS", "COUSUB", "COUSUBCC", "COUSUBNS", "SUBMCD",
    "SUBMCDCC", "SUBMCDNS", "ESTATE", "ESTATECC", "ESTATENS", "CONCIT", "CONCITCC", "CONCITNS", "PLACE", "PLACECC",
    "PLACENS", "TRACT", "BLKGRP", "BLOCK", "AIANHH", "AIHHTLI", "AIANHHFP", "AIANHHCC", "AIANHHNS", "AITS", "AITSFP",
    "AITSCC", "AITSNS", "TTRACT", "TBLKGRP", "ANRC", "ANRCCC", "ANRCNS", "CBSA", "MEMI", "CSA", "METDIV", "NECTA",
    "NMEMI", "CNECTA", "NECTADIV", "CBSAPCI", "NECTAPCI", "UA", "UATYPE", "UR", "CD116", "CD118", "CD119", "CD120",
    "CD121", "SLDU18", "SLDU22", "SLDU24", "SLDU26", "SLDU28", "SLDL18", "SLDL22", "SLDL24", "SLDL26", "SLDL28", "VTD",
    "VTDI", "ZCTA", "SDELM", "SDSEC", "SDUNI", "PUMA", "AREALAND", "AREAWATR", "BASENAME", "NAME", "FUNCSTAT", "GCUNI",
    "POP100", "HU100", "INTPTLAT", "INTPTLON", "LSADC", "PARTFLAG", "UGA",
]
# geo columns returned with every row
GEO_OUT = ["GEOID", "GEOCODE", "SUMLEV", "NAME", "STATE", "COUNTY", "COUSUB", "PLACE", "TRACT", "BLKGRP", "BLOCK",
           "VTD", "CD116", "SLDU18", "SLDL18", "SDUNI", "AREALAND", "AREAWATR", "INTPTLAT", "INTPTLON", "POP100", "HU100"]


def _cells(table: str, n: int) -> list[str]:
    t, k = table[0], int(table[1:])
    return [f"{t}{k:03d}{i:04d}" for i in range(1, n + 1)]


# table -> (segment, cell names)
TABLES = {
    "P1": (1, _cells("P1", 71)), "P2": (1, _cells("P2", 73)),
    "P3": (2, _cells("P3", 71)), "P4": (2, _cells("P4", 73)), "H1": (2, _cells("H1", 3)),
    "P5": (3, _cells("P5", 10)),
}
SEGMENT_TABLES = {1: ["P1", "P2"], 2: ["P3", "P4", "H1"], 3: ["P5"]}
TABLE_TITLES = {
    "P1": "Race (total population)", "P2": "Hispanic or Latino, and not Hispanic or Latino by race (total population)",
    "P3": "Race for the population 18 years and over", "P4": "Hispanic or Latino by race for the population 18 years and over",
    "H1": "Occupancy status (housing units)", "P5": "Group quarters population by major group quarters type",
}
GEOGRAPHIES = {
    "state": "040", "county": "050", "county_subdivision": "060", "tract": "140", "block_group": "150",
    "place": "160", "congressional_district": "500", "state_legislative_district_upper": "610",
    "state_legislative_district_lower": "620", "voting_district": "700", "block": "750",
    "school_district_elementary": "950", "school_district_secondary": "960", "school_district_unified": "970",
}
# Summary levels in the R2 mirror: all but blocks. Blocks (~8.2M rows nationally) would add ~1.35 GB compressed (DE
# measured: 20,198 blocks -> 3.3 MB) and ~40 min of single-process ingest (DE: 6.2 s with blocks vs 0.8 s without),
# well beyond one mirror run's budget here. To add them: include "block", bump `version` (minor) here and in the
# catalog entry, drop the "no blocks" caveat, and consider splitting block partitions by county (TX/CA blocks exceed
# the Worker's 60 MB per-request scan budget as one partition).
MIRROR_GEOGRAPHIES = [g for g in GEOGRAPHIES if g != "block"]
INT_GEO = {"AREALAND", "AREAWATR", "POP100", "HU100"}
FLOAT_GEO = {"INTPTLAT", "INTPTLON"}

_labels: dict[str, str] = {}


def zip_url(st: str) -> str:
    return f"{BASE}{STATE_DIRS[st]}/{FIPS_STATE[st].lower()}2020.pl.zip"


def labels() -> dict[str, str]:
    """Cell labels parsed from the Census R import scripts ('#  P0010003  White alone'). Best effort."""
    if not _labels:
        try:
            r = http.request("GET", R_SCRIPTS)
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                for n in z.namelist():
                    if re.search(r"pl_part\d_2020", n):
                        for m in re.finditer(r"^#\s+([PH]00\d{5})\s+(.+?)\s*$", z.read(n).decode("latin-1"), re.M):
                            _labels[m.group(1)] = m.group(2)
        except (SourceError, zipfile.BadZipFile):
            pass
    return _labels


def _geo_val(k: str, v: str):
    v = v.strip()
    if v == "":
        return None
    if k in INT_GEO:
        return int(v)
    if k in FLOAT_GEO:
        return float(v)
    return v


class CensusDecennial2020Pl(SourceAdapter):
    source_id = "census-decennial-2020-pl"
    version = "1.1.0"
    usage = ("2020 Census counts for one state at one summary level (state, county, tract, block group, block, place, "
             "voting district, congressional/legislative district, school district, ...). Tables: P1 race, P2 "
             "Hispanic origin by race, P3/P4 the same for ages 18+, H1 housing occupancy, P5 group quarters; cells are "
             "named like P0010001 (P1 cell 1 = total population), labels in metadata.variable_labels. `state` is "
             "required (the publisher ships one zip per state, up to ~100 MB). District columns are the 2020 "
             "plans (CD116, SLDU18, SLDL18); later plans are not in this release.")
    filters = [
        FilterSpec("state", "string", "State (postal code or FIPS); one per request.", required=True, example="DE"),
        FilterSpec("geography", "string", "Summary level.", enum=sorted(GEOGRAPHIES), default="county", example="county"),
        FilterSpec("tables", "string_list", f"Tables to include: {sorted(TABLES)}. Default ['P1','P2','H1'].",
                   enum=sorted(TABLES), default=["P1", "P2", "H1"], example=["P1", "P2"]),
        FilterSpec("county", "string", "3-digit county FIPS within the state, to restrict sub-county geographies.", example="001"),
        FilterSpec("geoids", "string_list", "Exact GEOCODEs (e.g. '10001' county, '10001040100' tract) to return.",
                   example=["10001"]),
    ]
    contract = [
        ContractCase(
            name="delaware_counties_p1",
            filters={"state": "DE", "geography": "county", "tables": ["P1", "H1"]},
            min_rows=3, max_rows=3,
            required_columns=["GEOID", "GEOCODE", "NAME", "POP100", "P0010001", "H0010001"],
            checks=[Check("GEOCODE", one_of=["10001", "10003", "10005"]),
                    Check("P0010001", numeric=True, min=150_000, max=600_000)],
            limit=10,
            custom=lambda rows: _check_delaware(rows),
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        st = state_fips(f["state"])
        if st not in STATE_DIRS:
            raise FilterError(f"no PL 94-171 file for state {f['state']}")
        geo = f.get("geography", "county")
        sumlev = GEOGRAPHIES[geo]
        tables = f.get("tables") or ["P1", "P2", "H1"]
        county = f.get("county")
        if county is not None and not re.fullmatch(r"\d{3}", county):
            raise FilterError("county must be a 3-digit county FIPS code within the state, e.g. '001'")
        geoids = set(f.get("geoids") or [])
        abbr = FIPS_STATE[st].lower()
        url = zip_url(st)
        selected: dict[str, dict] = {}
        order: list[str] = []
        matched = 0
        with http.download(url, cache_allowed=cache_allowed, max_age_s=180 * 86400) as path:
            with http.open_text(path, member=f"{abbr}geo2020.pl", encoding="latin-1") as fh:
                for i, line in enumerate(fh):
                    vals = line.rstrip("\r\n").split("|")
                    if i == 0:
                        require(len(vals) == len(GEO_FIELDS) and vals[0] == "PLST",
                                f"{url}: geo header has {len(vals)} fields (expected {len(GEO_FIELDS)}) / FILEID {vals[0]!r}")
                    if vals[2] != sumlev or vals[4] != "00":
                        continue
                    rec = dict(zip(GEO_FIELDS, vals))
                    if county and rec["COUNTY"] != county:
                        continue
                    if geoids and rec["GEOCODE"] not in geoids:
                        continue
                    matched += 1
                    if len(order) < limit:
                        order.append(rec["LOGRECNO"])
                        selected[rec["LOGRECNO"]] = {k: _geo_val(k, rec[k]) for k in GEO_OUT}
            for seg, seg_tables in SEGMENT_TABLES.items():
                want = [t for t in seg_tables if t in tables]
                if not want or not selected:
                    continue
                names = [c for t in seg_tables for c in TABLES[t][1]]
                keep = {c for t in want for c in TABLES[t][1]}
                with http.open_text(path, member=f"{abbr}0000{seg}2020.pl", encoding="latin-1") as fh:
                    for line in fh:
                        vals = line.rstrip("\r\n").split("|")
                        rec = selected.get(vals[4])
                        if rec is None:
                            continue
                        require(len(vals) == 5 + len(names),
                                f"{url}: segment {seg} record has {len(vals)} fields, expected {5 + len(names)}", kind="parse")
                        for n, v in zip(names, vals[5:]):
                            if n in keep:
                                rec[n] = int(v) if v.strip() else None
        rows = [selected[k] for k in order]
        lab = labels()
        var_labels = {c: lab.get(c, "") for t in tables for c in TABLES[t][1]}
        notes = [f"2020 Census PL 94-171 redistricting data for {FIPS_STATE[st]} from {url}.",
                 "Counts are subject to the Census Bureau's 2020 disclosure avoidance (differential privacy); only "
                 "state total population and housing-unit counts and group-quarters facility counts are invariant.",
                 "GEOID is the fully-qualified GEO_ID (e.g. 0500000US10001); GEOCODE is the short code."]
        meta = {"tables": {t: TABLE_TITLES[t] for t in tables}, "variable_labels": var_labels, "summary_level": sumlev}
        return FetchResult(rows, [url], notes, total_available=matched, metadata=meta)

    # -------------------------------------------------------------- mirror (docs/MIRROR.md)
    # Rows = fetch rows (all tables) plus the partition columns state (postal) and geography (summary level name).
    mirror_partition_keys = ["state", "geography"]
    mirror_required = ["state"]
    mirror_semantics = {"state": "state_postal", "STATE": "state_fips"}

    def mirror_plan(self):
        from ..mirror import MirrorUnit
        for st in sorted(STATE_DIRS):
            abbr = FIPS_STATE[st]
            yield MirrorUnit(partition={"state": abbr}, filters={"state": abbr}, split_by=["geography"])

    def mirror_rows(self, unit):
        st = state_fips(unit.filters["state"])
        abbr = FIPS_STATE[st]
        url = zip_url(st)
        by_sumlev = {GEOGRAPHIES[g]: g for g in MIRROR_GEOGRAPHIES}
        seg_names = {seg: [c for t in ts for c in TABLES[t][1]] for seg, ts in SEGMENT_TABLES.items()}

        def rows():
            with http.download(url, cache_allowed=True, max_age_s=180 * 86400) as path:
                fhs = [http.open_text(path, member=f"{abbr.lower()}geo2020.pl", encoding="latin-1")]
                fhs += [http.open_text(path, member=f"{abbr.lower()}0000{seg}2020.pl", encoding="latin-1") for seg in SEGMENT_TABLES]
                try:
                    for i, lines in enumerate(zip(*fhs, strict=True)):
                        if i == 0:
                            vals = lines[0].rstrip("\r\n").split("|")
                            require(len(vals) == len(GEO_FIELDS) and vals[0] == "PLST",
                                    f"{url}: geo header has {len(vals)} fields (expected {len(GEO_FIELDS)}) / FILEID {vals[0]!r}")
                        head = lines[0].split("|", 5)  # FILEID|STUSAB|SUMLEV|GEOVAR|GEOCOMP|...: cheap skip of blocks
                        geo = by_sumlev.get(head[2])
                        if geo is None or head[4] != "00":
                            continue
                        vals = lines[0].rstrip("\r\n").split("|")
                        g = dict(zip(GEO_FIELDS, vals))
                        rec = {"state": abbr, "geography": geo}
                        rec.update((k, _geo_val(k, g[k])) for k in GEO_OUT)
                        for seg, line in zip(SEGMENT_TABLES, lines[1:]):
                            sv = line.rstrip("\r\n").split("|")
                            names = seg_names[seg]
                            require(len(sv) == 5 + len(names) and sv[4] == g["LOGRECNO"],
                                    f"{url}: segment {seg} record {i} has {len(sv)} fields / LOGRECNO {sv[4] if len(sv) > 4 else None!r}, "
                                    f"expected {5 + len(names)} / {g['LOGRECNO']!r}", kind="parse")
                            for n, v in zip(names, sv[5:]):
                                rec[n] = int(v) if v.strip() else None
                        yield rec
                except ValueError as e:  # zip(strict=True): segment files of different lengths
                    raise SourceError(f"{url}: geo/segment files are not aligned: {e}", kind="parse") from None
                finally:
                    for fh in fhs:
                        fh.close()

        notes = ["2020 Census PL 94-171 redistricting data (one zip per state).",
                 "Counts are subject to the Census Bureau's 2020 disclosure avoidance (differential privacy); only "
                 "state total population and housing-unit counts and group-quarters facility counts are invariant.",
                 "GEOID is the fully-qualified GEO_ID (e.g. 0500000US10001); GEOCODE is the short code.",
                 "Mirror columns state (postal code) and geography (summary level name) are partition keys; filter on both.",
                 f"Mirrored summary levels: {', '.join(MIRROR_GEOGRAPHIES)}. Blocks are not in the mirror; fetch them "
                 "from the publisher with the local odc-server (geography 'block')."]
        lab = labels()
        meta = {"tables": dict(TABLE_TITLES),
                "variable_labels": {c: lab.get(c, "") for t in TABLES for c in TABLES[t][1]},
                "summary_levels": {g: GEOGRAPHIES[g] for g in MIRROR_GEOGRAPHIES}}
        return rows(), [url], notes, meta


def _check_delaware(rows: list[dict]) -> None:
    pop = {r["GEOCODE"]: r["P0010001"] for r in rows}
    # 2020 Census counts (county totals are not invariant, but these are the published 2020 values)
    assert pop == {"10001": 181851, "10003": 570719, "10005": 237378}, pop


ADAPTER = CensusDecennial2020Pl()
