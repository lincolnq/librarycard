"""U.S. EAC Election Administration and Voting Survey (EAVS), jurisdiction level. Catalog: catalog/eac-eavs.yaml

One CSV per survey year ("nolabel" CSV, usually zipped) linked from
https://www.eac.gov/research-and-data/datasets-codebooks-and-surveys . File URLs sit in Drupal upload-date folders
with version suffixes, so they are hard-coded per year below; when EAC posts a new version (e.g. 2024 V1 -> V2) the
catalog's change detection fires and DATA_FILES must be updated.

Layout: header row; ID columns FIPSCode, Jurisdiction_Name, State_Full, State_Abbr, then several hundred numeric
items named by survey question (A1a = total registered, F1a = total voters, ...) plus free-text *_Other and
*Comments columns. ~6,460 rows (one per reporting jurisdiction: counties in most states, towns/townships in
New England, Michigan and Wisconsin).

Sentinels (codebook): -77 = valid skip, -88 = "does not apply", -99 = "data not available". Converted to null.
FIPSCode is a 10-digit state+county+county-subdivision string; some files drop the leading zero (9 digits, e.g. CA
'600100000') - we left-pad 9-digit codes to 10. Wisconsin municipalities use 5-digit non-FIPS codes; left as-is.

2016 and earlier files use a different layout (FIPS_2Digit, State, JurisdictionName; different item numbering) and
are not served; add them with a column mapping if needed.

Variable labels come from the year's codebook .xlsx (parsed with stdlib zipfile + regex, best effort).
"""

from __future__ import annotations

import csv
import html
import re
import zipfile

from .. import http
from ..http import SourceError
from ._common import STATE_FIPS
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter

SITE = "https://www.eac.gov/sites/default/files"
DATA_FILES = {
    2018: f"{SITE}/2019-10/EAVS_2018_for_Public_Release_nolabel%20v1.1.csv",
    2020: f"{SITE}/2023-12/2020_EAVS_for_Public_Release_nolabel_V1.2_CSV.zip",
    2022: f"{SITE}/2023-06/2022_EAVS_for_Public_Release_nolabel_V1_CSV.zip",
    2024: f"{SITE}/2026-02/2024_EAVS_for_Public_Release_nolabel_V2_csv.zip",
}
CODEBOOKS = {
    2018: f"{SITE}/eac_assets/1/6/2018_EAVS_Codebook.xlsx",
    2020: f"{SITE}/2021-08/2020_EAVS_Codebook.xlsx",
    2024: f"{SITE}/2025-06/2024_EAVS_Codebook.xlsx",
}
ID_COLS = ["FIPSCode", "Jurisdiction_Name", "State_Full", "State_Abbr"]
SENTINELS = {"-77", "-88", "-99"}
TERRITORIES = {"AS", "GU", "MP", "VI", "PR"}


def _clean(v: str | None):
    if v is None:
        return None
    v = v.strip()
    if v == "" or v in SENTINELS:
        return None
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d*\.\d+", v):
        return float(v)
    return v


def _norm_fips(code: str) -> str:
    code = code.strip()
    return code.zfill(10) if len(code) == 9 and code.isdigit() else code


def _codebook_labels(url: str, cache_allowed: bool) -> dict[str, str]:
    """VariableName -> Label from an EAVS codebook workbook (first sheet). Best effort; {} on any problem."""
    try:
        with http.download(url, cache_allowed=cache_allowed, max_age_s=30 * 86400) as path:
            z = zipfile.ZipFile(path)
            shared: list[str] = []
            if "xl/sharedStrings.xml" in z.namelist():
                x = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
                for si in re.findall(r"<si>(.*?)</si>", x, re.S):
                    shared.append(html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))))
            sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8", "replace")
    except (SourceError, zipfile.BadZipFile, KeyError, OSError):
        return {}
    rows = []
    for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        cells = []
        for attrs, inner in re.findall(r"<c ([^>]*?)(?:/>|>(.*?)</c>)", row, re.S):
            m = re.search(r"<v>(.*?)</v>", inner or "", re.S)
            v = m.group(1) if m else "".join(re.findall(r"<t[^>]*>(.*?)</t>", inner or "", re.S))
            if 't="s"' in attrs and v.isdigit() and int(v) < len(shared):
                v = shared[int(v)]
            cells.append(html.unescape(v).strip())
        rows.append(cells)
    if not rows or "VariableName" not in rows[0] or "Label" not in rows[0]:
        return {}
    iv, il = rows[0].index("VariableName"), rows[0].index("Label")
    return {r[iv]: re.sub(r"\s+", " ", r[il]) for r in rows[1:] if len(r) > max(iv, il) and r[iv]}


def _ca_2024(rows: list[dict]) -> None:
    la = next((r for r in rows if r["FIPSCode"] == "0603700000"), None)
    assert la, f"Los Angeles County (0603700000) missing; FIPS seen: {[r['FIPSCode'] for r in rows[:5]]}"
    assert la["A1a"] and 5_000_000 < la["A1a"] < 7_000_000, la["A1a"]  # total registered
    assert la["F1a"] and 3_000_000 < la["F1a"] < 4_500_000, la["F1a"]  # total voters


class EacEavs(SourceAdapter):
    source_id = "eac-eavs"
    version = "1.0.0"
    usage = ("One row per election jurisdiction (county, or town/township in New England, MI and WI) for one "
             f"biennial survey year ({', '.join(map(str, sorted(DATA_FILES)))}). Columns are survey item codes "
             "(A1a = total registered voters, A1b active, F1a total who voted, C1a mail ballots transmitted, "
             "E1a provisional ballots cast, B1a UOCAVA registered, D1a precincts, D5a poll workers); "
             "`metadata.variable_labels` maps codes to labels where a codebook exists. Pass `variables` to keep "
             "rows small; ID columns are always returned. Item numbering changes between years.")
    filters = [
        FilterSpec("year", "integer", "Survey (federal general election) year.", required=True,
                   enum=sorted(DATA_FILES), example=2024),
        FilterSpec("state", "string", "2-letter postal code (states, DC, and territories AS, GU, MP, PR, VI) or state FIPS.", example="CA"),
        FilterSpec("county_fips", "string", "5-digit county FIPS; matches jurisdictions whose FIPSCode starts with it.", example="06037"),
        FilterSpec("jurisdiction", "string", "Case-insensitive substring of Jurisdiction_Name, e.g. 'LOS ANGELES'."),
        FilterSpec("variables", "string_list", "Item columns to return, e.g. ['A1a','F1a','C1a']. Default: all items (500+ columns)."),
        FilterSpec("include_comments", "boolean", "Include free-text *Comments / *_Other columns (default false).", default=False),
    ]
    contract = [
        ContractCase(
            name="california_2024_core_items",
            filters={"year": 2024, "state": "CA", "variables": ["A1a", "A1b", "F1a", "C1a", "E1a"]},
            min_rows=58, max_rows=58,
            required_columns=["FIPSCode", "Jurisdiction_Name", "State_Abbr", "A1a", "F1a", "C1a"],
            checks=[Check("State_Abbr", one_of=["CA"]), Check("FIPSCode", regex=r"06\d{8}"),
                    Check("A1a", numeric=True, min=0, max=8_000_000), Check("F1a", numeric=True, min=0, max=5_000_000)],
            limit=100,
            custom=_ca_2024,
        ),
        ContractCase(
            name="delaware_2020_counties",
            filters={"year": 2020, "state": "DE", "variables": ["A1a", "F1a"]},
            min_rows=3, max_rows=3,
            required_columns=["FIPSCode", "A1a", "F1a"],
            checks=[Check("FIPSCode", regex=r"10\d{8}"), Check("A1a", numeric=True, min=100_000, max=600_000)],
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        year = f["year"]
        url = DATA_FILES[year]
        st = None
        if f.get("state"):
            s = str(f["state"]).strip().upper()
            if s in STATE_FIPS or s in TERRITORIES:
                st = s
            elif s.isdigit():
                st = next((k for k, v in STATE_FIPS.items() if v == s.zfill(2)), None)
            if not st:
                raise FilterError(f"unrecognized state {f['state']!r}; use a postal code like 'CA' (territories: AS, GU, MP, PR, VI)")
        cf = f.get("county_fips")
        if cf and not (len(cf) == 5 and cf.isdigit()):
            raise FilterError("county_fips must be 5 digits, e.g. '06037'")
        jur = f.get("jurisdiction", "").strip().upper() or None
        wanted = f.get("variables")
        comments = f.get("include_comments", False)

        out: list[dict] = []
        matched = 0
        with http.download(url, cache_allowed=cache_allowed, max_age_s=30 * 86400) as path:
            with http.open_text(path, encoding="utf-8-sig") as fh:
                reader = csv.reader(fh)
                header = [h.strip() for h in next(reader, [])]
                missing = [c for c in ID_COLS if c not in header]
                if missing:
                    raise SourceError(f"{url}: ID columns {missing} not in header {header[:10]}", kind="schema", url=url)
                if wanted:
                    unknown = [v for v in wanted if v not in header]
                    if unknown:
                        raise FilterError(f"unknown variable(s) {unknown} for {year}; item codes differ by year — "
                                          f"first items in this file: {header[4:24]}")
                    keep_cols = ID_COLS + [v for v in wanted if v not in ID_COLS]
                else:
                    keep_cols = [h for h in header if comments or not (h.endswith("Comments") or h.endswith("_Other"))]
                idx = {h: i for i, h in enumerate(header)}
                for rec in reader:
                    if not rec:
                        continue
                    if len(rec) < len(header):
                        rec = rec + [""] * (len(header) - len(rec))
                    sa = rec[idx["State_Abbr"]].strip().upper()
                    fips = _norm_fips(rec[idx["FIPSCode"]])
                    if st and sa != st:
                        continue
                    if cf and not (len(fips) == 10 and fips.startswith(cf)):
                        continue
                    if jur and jur not in rec[idx["Jurisdiction_Name"]].upper():
                        continue
                    matched += 1
                    if len(out) < limit:
                        row = {}
                        for c in keep_cols:
                            v = rec[idx[c]]
                            row[c] = fips if c == "FIPSCode" else (v.strip() or None) if c in ID_COLS else _clean(v)
                        out.append(row)
        urls = [url]
        labels: dict[str, str] = {}
        if year in CODEBOOKS:
            all_labels = _codebook_labels(CODEBOOKS[year], cache_allowed)
            cols = set(out[0]) if out else set()
            labels = {k: v for k, v in all_labels.items() if k in cols}
            urls.append(CODEBOOKS[year])
        notes = [f"EAVS {year} public-release file ({url.rsplit('/', 1)[-1]}).",
                 "Sentinel codes -77 (valid skip), -88 (does not apply) and -99 (data not available) were converted to null; "
                 "null therefore does not mean zero.",
                 "9-digit FIPSCode values (leading zero dropped upstream) were left-padded to 10 digits."]
        if year not in CODEBOOKS:
            notes.append(f"No machine-readable codebook for {year}; see the PDF survey instrument on eac.gov for item labels.")
        return FetchResult(out, urls, notes, total_available=matched,
                           metadata={"year": year, "variable_labels": labels,
                                     "codebook": CODEBOOKS.get(year),
                                     "sentinels": {"-77": "valid skip", "-88": "does not apply", "-99": "data not available"}})


ADAPTER = EacEavs()
