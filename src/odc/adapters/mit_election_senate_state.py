"""MIT Election Data + Science Lab, U.S. Senate statewide 1976-2024. Catalog: catalog/mit-election-senate-state.yaml

Harvard Dataverse dataset doi:10.7910/DVN/PEJ5QU, file 1976-2024-senate-state.csv (ingested by Dataverse as .tab;
we request ?format=original). ~3,900 rows, one per candidate x party line x race. No guestbook; CC0.
Shared logic in _medsl.py.

Sentinel: the codebook says "Uncontested races are identified with a vote total of 1" (e.g. Louisiana 1978,
1984, 1990, 1992 where no general-election vote was held). Rows with totalvotes == 1 get candidatevotes and
totalvotes set to null and uncontested = True. stage/mode are inconsistently cased upstream ("gen"/"GEN",
"total"/"TOTAL"); values are returned as published, filters compare case-insensitively.
"""

from __future__ import annotations

from ._medsl import PARTY_SIMPLIFIED, fetch_medsl, year_predicate
from .base import Check, ContractCase, FetchResult, FilterSpec, SourceAdapter

DOI = "doi:10.7910/DVN/PEJ5QU"
FILE_PATTERN = r"^\d{4}-\d{4}-senate-state\.(csv|tab)$"
COLUMNS = ["year", "state", "state_po", "state_fips", "state_cen", "state_ic", "office", "district", "stage",
           "special", "candidate", "party_detailed", "writein", "mode", "candidatevotes", "totalvotes",
           "unofficial", "version", "party_simplified"]


def _ga_runoff(rows: list[dict]) -> None:
    by = {r["candidate"]: r["candidatevotes"] for r in rows}
    # Certified 5 Jan 2021 Georgia runoffs.
    assert by.get("JON OSSOFF") == 2269262, by
    assert by.get("RAPHAEL WARNOCK") == 2288446, by


def _la_uncontested(rows: list[dict]) -> None:
    unc = [r for r in rows if r.get("uncontested")]
    assert unc, "expected Louisiana 1978 uncontested row flagged"
    assert all(r["totalvotes"] is None and r["candidatevotes"] is None for r in unc), unc


class MitElectionSenateState(SourceAdapter):
    source_id = "mit-election-senate-state"
    version = "1.0.0"
    usage = ("One row per candidate per party line per U.S. Senate race (statewide), 1976-2024, including special "
             "elections and runoffs. Filter by year/state; use `special` to separate a special election held the same "
             "year as a regular one (two races in one state-year), and `stage` for runoffs ('gen', 'runoff'). Sum "
             "candidatevotes by candidate across party lines (fusion voting). Uncontested races (no vote held) have "
             "null vote counts and uncontested=true.")
    filters = [
        FilterSpec("year", "integer", "Election year, e.g. 2020 (odd years exist for runoffs/specials, e.g. 2021 GA).", example=2020),
        FilterSpec("year_from", "integer", "First election year (inclusive)."),
        FilterSpec("year_to", "integer", "Last election year (inclusive)."),
        FilterSpec("state", "string", "2-letter postal code or FIPS, e.g. 'AZ' or '04'.", example="AZ"),
        FilterSpec("party_simplified", "string_list", "One or more of DEMOCRAT, REPUBLICAN, LIBERTARIAN, OTHER.",
                   enum=PARTY_SIMPLIFIED),
        FilterSpec("candidate", "string", "Case-insensitive substring of the candidate name, e.g. 'OSSOFF'."),
        FilterSpec("stage", "string", "Electoral stage, case-insensitive: 'gen' (general), 'runoff', 'gen runoff', 'pre' "
                   "(GA 1992/2008 first rounds). Matches exactly after lower-casing.", example="gen"),
        FilterSpec("special", "boolean", "true = special elections only; false = regular elections only."),
    ]
    contract = [
        ContractCase(
            name="georgia_2021_runoffs",
            filters={"year": 2021, "state": "GA"},
            min_rows=4, max_rows=8,
            required_columns=["year", "state_po", "stage", "special", "candidate", "candidatevotes", "totalvotes", "uncontested"],
            checks=[Check("state_po", one_of=["GA"]), Check("state_fips", one_of=["13"]),
                    Check("candidatevotes", numeric=True, min=2_000_000, max=2_400_000)],
            custom=_ga_runoff,
        ),
        ContractCase(
            name="louisiana_1978_uncontested",
            filters={"year": 1978, "state": "LA"},
            min_rows=1, max_rows=5,
            required_columns=["candidate", "candidatevotes", "totalvotes", "uncontested"],
            checks=[Check("state_po", one_of=["LA"])],
            custom=_la_uncontested,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        base = year_predicate(f)
        stage = f.get("stage", "").strip().lower() or None
        special = f.get("special")

        def keep(r: dict) -> bool:
            if not base(r):
                return False
            if stage and (r.get("stage") or "").strip().lower() != stage:
                return False
            if special is not None and (r.get("special") or "").strip().lower() != str(special).lower():
                return False
            return True

        rows, matched, urls, meta = fetch_medsl(DOI, FILE_PATTERN, columns=COLUMNS, predicate=keep,
                                                limit=limit, cache_allowed=cache_allowed)
        n_unc = 0
        for r in rows:
            r["uncontested"] = r.get("totalvotes") == 1
            if r["uncontested"]:
                r["candidatevotes"] = None
                r["totalvotes"] = None
                n_unc += 1
        notes = [f"MEDSL dataset {DOI}, Dataverse version {meta.get('dataverse_version')} ({meta.get('file_name')}).",
                 "state_fips zero-padded to 2 digits; vote counts converted to integers; empty cells returned as null.",
                 "Uncontested-race sentinel (totalvotes = 1) converted to null vote counts with uncontested=true."
                 + (f" {n_unc} such row(s) in this result." if n_unc else "")]
        return FetchResult(rows, urls, notes, total_available=matched, metadata=meta)


ADAPTER = MitElectionSenateState()
