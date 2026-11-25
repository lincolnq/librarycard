"""County Health Rankings & Roadmaps national analytic data (CSV). Catalog: catalog/county-health-rankings.yaml

Files: https://www.countyhealthrankings.org/sites/default/files/media/document/<FILE> (FILES below; listed on
the data-documentation page). Re-issued files get a version suffix (2025 is currently analytic_data2025_v3.csv);
change detection watches the file names on that page — update FILES when a new year or version appears.

Layout: ~800 columns, TWO header rows: row 1 = human-readable labels ("Premature Death raw value"),
row 2 = variable codes ("v001_rawvalue"). We key rows by the codes (stable across years) and return the labels
in metadata.variable_labels. Row grain: one per county, plus state rows (countycode '000') and a national row
(fipscode '00000'). Measure columns follow vNNN_<rawvalue|numerator|denominator|cilow|cihigh|flag|race_*>.
License is link_only (non-commercial terms): never cached, streamed to a temp file per request (~13 MB).
"""

from __future__ import annotations

import csv
import re

from .. import http
from ..http import SourceError
from ._common import state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

BASE = "https://www.countyhealthrankings.org/sites/default/files/media/document"
FILES = {
    2025: "analytic_data2025_v3.csv",
    2024: "analytic_data2024.csv",
    2023: "analytic_data2023.csv",
    2022: "analytic_data2022.csv",
    2021: "analytic_data2021.csv",
    2020: "analytic_data2020.csv",
    2019: "analytic_data2019.csv",
}
LATEST = max(FILES)
ID_COLS = ("statecode", "countycode", "fipscode", "state", "county", "year")
_MEASURE_RE = re.compile(r"^v\d{3}$")


def _num(v: str):
    v = (v or "").strip()
    if v in ("", "."):
        return None
    try:
        f = float(v)
    except ValueError:
        return v
    return int(f) if f.is_integer() and "." not in v and "e" not in v.lower() else f


def _check_dane(rows: list[dict]) -> None:
    r = rows[0]
    assert r["county"].startswith("Dane"), r["county"]
    assert r["v001_rawvalue"] is not None and 3000 < r["v001_rawvalue"] < 9000, r["v001_rawvalue"]


class CountyHealthRankings(SourceAdapter):
    source_id = "county-health-rankings"
    version = "1.0.0"
    usage = ("One row per county (plus state rows with countycode '000' and the US row '00000') for one release year. "
             "Columns are CHR&R variable codes: vNNN_rawvalue (the measure), _numerator, _denominator, _cilow, _cihigh, "
             "_flag, and race-specific vNNN_race_*; metadata.variable_labels maps codes to names (e.g. v001 = Premature "
             "Death, v009 = Adult Smoking, v011 = Adult Obesity, v085 = Uninsured). Use `measures` (e.g. ['v001','v011']) "
             "or `variables` to keep the response small. Each call downloads the ~13 MB national file (not cached).")
    filters = [
        FilterSpec("year", "integer", f"Release year (data years lag 1-5 years by measure). Default {LATEST}.",
                   enum=sorted(FILES), default=LATEST),
        FilterSpec("state", "string", "State postal code or FIPS.", example="WI"),
        FilterSpec("fips", "string_list", "5-digit FIPS codes (county, or SS000 for a state row, 00000 for US).", example=["55025"]),
        FilterSpec("level", "string", "county (default), state or national rows.", enum=["county", "state", "national"], default="county"),
        FilterSpec("measures", "string_list", "Measure ids; returns all columns of each, e.g. ['v001','v011'].", example=["v001", "v011"]),
        FilterSpec("variables", "string_list", "Exact column codes, e.g. ['v001_rawvalue','v011_rawvalue'].", example=["v001_rawvalue"]),
    ]
    contract = [
        ContractCase(
            name="dane_county_wi_2025",
            filters={"year": 2025, "fips": ["55025"], "measures": ["v001", "v011"]},
            min_rows=1, max_rows=1,
            required_columns=["fipscode", "state", "county", "year", "v001_rawvalue", "v001_cilow", "v011_rawvalue"],
            checks=[Check("state", one_of=["WI"]), Check("v011_rawvalue", numeric=True, min=0.1, max=0.6),
                    Check("year", numeric=True, min=2025, max=2025)],
            custom=_check_dane,
            limit=5,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        year = f.get("year", LATEST)
        level = f.get("level", "county")
        st = state_fips(f["state"]) if f.get("state") else None
        fips = {x.zfill(5) for x in f.get("fips") or []}
        measures = [m.lower() for m in f.get("measures") or []]
        bad = [m for m in measures if not _MEASURE_RE.match(m)]
        if bad:
            raise FilterError(f"measures must look like 'v001'; got {bad}")
        variables = set(f.get("variables") or [])
        url = f"{BASE}/{FILES[year]}"

        def keep_row(r: dict) -> bool:
            code = r.get("fipscode", "")
            if fips:
                return code in fips
            if st and r.get("statecode") != st:
                return False
            cc = r.get("countycode")
            if level == "national":
                return code == "00000"
            if level == "state":
                return cc == "000" and code != "00000"
            return cc != "000"

        rows: list[dict] = []
        matched = 0
        with http.download(url, cache_allowed=cache_allowed, max_age_s=30 * 86400) as path:
            with http.open_text(path, encoding="utf-8-sig") as fh:
                reader = csv.reader(fh)
                try:
                    labels = next(reader)
                    codes = [c.strip() for c in next(reader)]
                except StopIteration:
                    raise SourceError(f"{url}: file has fewer than two header rows", kind="empty", url=url) from None
                require(all(c in codes for c in ("fipscode", "statecode", "countycode", "county")),
                        f"{url}: second header row lacks variable codes; got {codes[:10]}", kind="schema")
                keep_cols = [c for c in codes if c in ID_COLS or (not measures and not variables)
                             or c in variables or any(c.startswith(m + "_") for m in measures)]
                missing = [v for v in variables if v not in codes]
                if missing:
                    raise FilterError(f"unknown variable code(s) {missing} for {year}; see metadata.variable_labels of an unfiltered call")
                if measures and not any(c.startswith(m + "_") for c in codes for m in measures):
                    raise FilterError(f"none of measures {measures} exist in the {year} file")
                idx = [(i, c) for i, c in enumerate(codes) if c in keep_cols]
                for raw in reader:
                    r = dict(zip(codes, raw))
                    if not keep_row(r):
                        continue
                    matched += 1
                    if len(rows) < limit:
                        rows.append({c: (raw[i].strip() if c in ID_COLS[:5] else _num(raw[i])) if i < len(raw) else None
                                     for i, c in idx})
        label_map = {c: labels[i] for i, c in idx if i < len(labels)}
        notes = [f"County Health Rankings & Roadmaps {year} release ({FILES[year]}). Measures draw on different data "
                 "years and sources; see the year's technical documentation.",
                 "Empty cells and '.' were returned as null. Flags: 1 = unreliable, 2 = suppressed."]
        return FetchResult(rows, [url], notes, total_available=matched,
                           metadata={"year": year, "variable_labels": label_map})


ADAPTER = CountyHealthRankings()
