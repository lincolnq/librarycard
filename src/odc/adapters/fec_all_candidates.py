"""FEC "All candidates" summary file (weballYY). Catalog: catalog/fec-all-candidates.yaml

Bulk file: https://www.fec.gov/files/bulk-downloads/<CYCLE>/weball<YY>.zip  (302 -> FEC's S3 bucket
cg-519a459a-0ea3-42c2-b7bc-fa1143481f74.s3-us-gov-west-1.amazonaws.com/bulk-downloads/...). The zip holds one
pipe-delimited text file weball<YY>.txt with NO header row and 30 columns, documented at
https://www.fec.gov/campaign-finance-data/all-candidates-file-description/ (column list hard-coded below; the
catalog's change detection watches that page's column names). One row per candidate (all authorized committees
combined) for the two-year cycle ending in <CYCLE>. Regenerated daily by FEC, including for past cycles.

Scope: candidate-level totals only. This adapter must never be extended to itemized individual contributions
(names private donors; docs/POLICY.md#scope).
"""

from __future__ import annotations

import csv
import datetime as dt

from .. import http
from ..http import SourceError
from ._common import state_abbr
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter

BASE = "https://www.fec.gov/files/bulk-downloads"
FIRST_CYCLE = 1980
COLUMNS = [
    "CAND_ID", "CAND_NAME", "CAND_ICI", "PTY_CD", "CAND_PTY_AFFILIATION", "TTL_RECEIPTS", "TRANS_FROM_AUTH",
    "TTL_DISB", "TRANS_TO_AUTH", "COH_BOP", "COH_COP", "CAND_CONTRIB", "CAND_LOANS", "OTHER_LOANS",
    "CAND_LOAN_REPAY", "OTHER_LOAN_REPAY", "DEBTS_OWED_BY", "TTL_INDIV_CONTRIB", "CAND_OFFICE_ST",
    "CAND_OFFICE_DISTRICT", "SPEC_ELECTION", "PRIM_ELECTION", "RUN_ELECTION", "GEN_ELECTION",
    "GEN_ELECTION_PRECENT", "OTHER_POL_CMTE_CONTRIB", "POL_PTY_CONTRIB", "CVG_END_DT", "INDIV_REFUNDS",
    "CMTE_REFUNDS",
]
MONEY = {"TTL_RECEIPTS", "TRANS_FROM_AUTH", "TTL_DISB", "TRANS_TO_AUTH", "COH_BOP", "COH_COP", "CAND_CONTRIB",
         "CAND_LOANS", "OTHER_LOANS", "CAND_LOAN_REPAY", "OTHER_LOAN_REPAY", "DEBTS_OWED_BY", "TTL_INDIV_CONTRIB",
         "OTHER_POL_CMTE_CONTRIB", "POL_PTY_CONTRIB", "INDIV_REFUNDS", "CMTE_REFUNDS", "GEN_ELECTION_PRECENT"}
OFFICES = {"H": "House", "S": "Senate", "P": "President"}


def zip_url(cycle: int) -> str:
    return f"{BASE}/{cycle}/weball{cycle % 100:02d}.zip"


def _num(v: str):
    v = v.strip()
    if v == "":
        return None
    try:
        f = float(v)
    except ValueError:
        raise SourceError(f"non-numeric money value {v!r}", kind="parse") from None
    return int(f) if f.is_integer() else f


def _date(v: str):
    v = v.strip()
    if not v:
        return None
    try:
        return dt.datetime.strptime(v, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return v


def _clean(rec: list[str]) -> dict:
    row: dict = {}
    for k, v in zip(COLUMNS, rec):
        if k in MONEY:
            row[k] = _num(v)
        elif k == "CVG_END_DT":
            row[k] = _date(v)
        else:
            row[k] = v.strip() or None
    cid = row["CAND_ID"] or ""
    row["CAND_OFFICE"] = cid[:1] if cid[:1] in OFFICES else None
    return row


def _aoc_2024(rows: list[dict]) -> None:
    r = next((x for x in rows if x["CAND_ID"] == "H8NY15148"), None)
    assert r, "H8NY15148 (Ocasio-Cortez) missing from NY 2024 House rows"
    assert r["CAND_OFFICE_DISTRICT"] == "14" and r["CAND_PTY_AFFILIATION"] == "DEM", r
    assert 10_000_000 < r["TTL_RECEIPTS"] < 25_000_000, r["TTL_RECEIPTS"]


class FecAllCandidates(SourceAdapter):
    source_id = "fec-all-candidates"
    version = "1.1.0"
    usage = ("One row per federal candidate per two-year cycle with financial totals summed over all of the "
             "candidate's authorized committees (receipts, disbursements, cash on hand, loans, debts, individual/PAC/"
             "party contributions). `cycle` (even year) is required. Filter by state, office (H/S/P), party or "
             "cand_ids. Money is in nominal dollars as reported; subtract TRANS_FROM_AUTH / TRANS_TO_AUTH to avoid "
             "double counting transfers between a candidate's committees.")
    filters = [
        FilterSpec("cycle", "integer", f"Two-year election cycle, named by its even end year ({FIRST_CYCLE}-present), e.g. 2024.",
                   required=True, example=2024),
        FilterSpec("state", "string", "State of the office sought (postal code or FIPS). Presidential candidates have CAND_OFFICE_ST '00' (filter them with office='P').",
                   example="NY"),
        FilterSpec("office", "string", "H = House, S = Senate, P = President (first letter of CAND_ID).", enum=["H", "S", "P"]),
        FilterSpec("district", "string", "House district, 2 digits (e.g. '14'; '00' = at-large). Use with state.", example="14"),
        FilterSpec("party", "string", "FEC 3-letter party code in CAND_PTY_AFFILIATION, e.g. DEM, REP, LIB, GRE, IND.", example="DEM"),
        FilterSpec("incumbent_challenger", "string", "CAND_ICI: I = incumbent, C = challenger, O = open seat.", enum=["I", "C", "O"]),
        FilterSpec("cand_ids", "string_list", "Exact FEC candidate ids, e.g. ['H8NY15148']."),
        FilterSpec("name", "string", "Case-insensitive substring of CAND_NAME ('LAST, FIRST'), e.g. 'OCASIO'."),
        FilterSpec("min_receipts", "number", "Only candidates with TTL_RECEIPTS >= this many dollars (drops paper candidates)."),
    ]
    contract = [
        ContractCase(
            name="ny_house_2024",
            filters={"cycle": 2024, "state": "NY", "office": "H"},
            min_rows=60, max_rows=400,
            required_columns=["CAND_ID", "CAND_NAME", "CAND_PTY_AFFILIATION", "TTL_RECEIPTS", "TTL_DISB", "COH_COP",
                              "CAND_OFFICE_ST", "CAND_OFFICE_DISTRICT", "CVG_END_DT", "CAND_OFFICE"],
            checks=[Check("CAND_ID", regex=r"H\d[A-Z]{2}\d{5}"), Check("CAND_OFFICE_ST", one_of=["NY"]),
                    Check("CAND_OFFICE", one_of=["H"]), Check("TTL_RECEIPTS", numeric=True, min=-1e6, max=1e8),
                    Check("CVG_END_DT", regex=r"20\d\d-\d\d-\d\d")],
            limit=500,
            custom=_aoc_2024,
        ),
        ContractCase(
            name="senate_2020_big_spenders",
            filters={"cycle": 2020, "office": "S", "min_receipts": 50_000_000},
            min_rows=5, max_rows=60,
            required_columns=["CAND_ID", "TTL_RECEIPTS", "TTL_INDIV_CONTRIB"],
            checks=[Check("CAND_ID", regex=r"S\d[A-Z]{2}\d{5}"), Check("TTL_RECEIPTS", numeric=True, min=5e7, max=5e8)],
            limit=100,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        cycle = f["cycle"]
        this_year = dt.date.today().year
        if cycle % 2 or cycle < FIRST_CYCLE or cycle > this_year + 2:
            raise FilterError(f"cycle must be an even year between {FIRST_CYCLE} and {this_year + (this_year % 2)} (e.g. 2024)")
        st = state_abbr(f["state"]) if f.get("state") else None
        office = f.get("office")
        district = f["district"].zfill(2) if f.get("district") else None
        party = f.get("party", "").strip().upper() or None
        ici = f.get("incumbent_challenger")
        ids = {i.strip().upper() for i in f.get("cand_ids") or []}
        name = f.get("name", "").strip().upper() or None
        min_r = f.get("min_receipts")

        url = zip_url(cycle)
        out: list[dict] = []
        matched = 0
        try:
            with http.download(url, cache_allowed=cache_allowed, max_age_s=86400) as path:
                with http.open_text(path, encoding="latin-1") as fh:
                    for n, rec in enumerate(csv.reader(fh, delimiter="|", quoting=csv.QUOTE_NONE)):
                        if not rec:
                            continue
                        if len(rec) != len(COLUMNS):
                            raise SourceError(f"{url}: line {n + 1} has {len(rec)} fields, expected {len(COLUMNS)} "
                                              "(file layout changed? see all-candidates-file-description)", kind="schema", url=url)
                        cid = rec[0].strip()
                        if ids and cid.upper() not in ids:
                            continue
                        if office and cid[:1] != office:
                            continue
                        if st and rec[18].strip().upper() != st:
                            continue
                        if district and rec[19].strip().zfill(2) != district:
                            continue
                        if party and rec[4].strip().upper() != party:
                            continue
                        if ici and rec[2].strip() != ici:
                            continue
                        if name and name not in rec[1].upper():
                            continue
                        if min_r is not None and (_num(rec[5]) or 0) < min_r:
                            continue
                        matched += 1
                        if len(out) < limit:
                            out.append(_clean(rec))
        except SourceError as e:
            if e.status in (403, 404):
                raise FilterError(f"no all-candidates file for cycle {cycle} ({url}); FEC publishes cycles {FIRST_CYCLE} onward") from None
            raise
        notes = ["Totals combine all of a candidate's authorized committees for the cycle; FEC regenerates this file daily, so "
                 "current-cycle (and occasionally past-cycle) figures change as reports are filed or amended.",
                 "Blank numeric fields returned as null. CVG_END_DT converted from MM/DD/YYYY to ISO date. "
                 "CAND_OFFICE (H/S/P) is derived from the first letter of CAND_ID."]
        if cycle > 2006:
            notes.append("SPEC/PRIM/RUN/GEN_ELECTION and GEN_ELECTION_PRECENT (sic) are only populated in 1996-2006 files.")
        return FetchResult(out, [url], notes, total_available=matched,
                           metadata={"cycle": cycle, "column_doc": "https://www.fec.gov/campaign-finance-data/all-candidates-file-description/"})


    # Mirror: every cycle (one ~0.2 MB zip each), partitioned by cycle and office. Rows gain a `cycle` column.
    mirror_partition_keys = ["cycle", "CAND_OFFICE"]
    mirror_semantics = {"CAND_OFFICE_ST": "state_postal"}

    def mirror_plan(self):
        from ..mirror import MirrorUnit
        y = dt.date.today().year
        for cycle in range(FIRST_CYCLE, y + y % 2 + 1, 2):  # through the current cycle
            yield MirrorUnit(partition={"cycle": str(cycle)}, filters={"cycle": cycle}, split_by=["CAND_OFFICE"])

    def mirror_rows(self, unit):
        rows, urls, notes, _ = super().mirror_rows(unit)
        cycle = int(unit.partition["cycle"])
        notes = [n for n in notes if not n.startswith("SPEC/PRIM")] + [
            "SPEC/PRIM/RUN/GEN_ELECTION and GEN_ELECTION_PRECENT (sic) are only populated in 1996-2006 files.",
            "`cycle` (even end year of the two-year cycle) is added by the mirror; it is the adapter's `cycle` filter."]
        meta = {"column_doc": "https://www.fec.gov/campaign-finance-data/all-candidates-file-description/"}
        return [{"cycle": cycle, **r} for r in rows], urls, notes, meta


ADAPTER = FecAllCandidates()
