"""MIT Election Data + Science Lab, U.S. President 1976-2024 (state level). Catalog: catalog/mit-election-president-state.yaml

Harvard Dataverse dataset doi:10.7910/DVN/42MVDX, file 1976-2024-president.csv (~0.5 MB, ~4,800 rows,
one row per candidate x party line x state x election). No guestbook; CC0. Shared logic in _medsl.py.
"""

from __future__ import annotations

from ._medsl import PARTY_SIMPLIFIED, fetch_medsl, year_predicate
from .base import Check, ContractCase, FetchResult, FilterSpec, SourceAdapter

DOI = "doi:10.7910/DVN/42MVDX"
FILE_PATTERN = r"^\d{4}-\d{4}-president\.(csv|tab)$"
COLUMNS = ["year", "state", "state_po", "state_fips", "state_cen", "state_ic", "office", "candidate",
           "party_detailed", "writein", "candidatevotes", "totalvotes", "version", "notes", "party_simplified"]


def _ga_2020(rows: list[dict]) -> None:
    by = {r["candidate"]: r["candidatevotes"] for r in rows}
    biden = next((v for k, v in by.items() if k and "BIDEN" in k), None)
    trump = next((v for k, v in by.items() if k and "TRUMP" in k), None)
    assert biden and trump, f"Biden/Trump rows missing: {sorted(k for k in by if k)}"
    # Certified Georgia 2020 result: Biden 2,473,633 vs Trump 2,461,854.
    assert 2_470_000 <= biden <= 2_480_000 and 2_455_000 <= trump <= 2_465_000 and biden > trump, (biden, trump)


class MitElectionPresidentState(SourceAdapter):
    source_id = "mit-election-president-state"
    version = "1.0.0"
    usage = ("One row per candidate per party line per state per presidential election (1976-2024). Filter by "
             "year (or year_from/year_to) and state. A candidate on several party lines (e.g. NY fusion voting) has "
             "one row per line: sum candidatevotes by candidate for their total. totalvotes is the state total for "
             "the office (repeated on every row); rows with a null candidate are blank/scattering/other entries.")
    filters = [
        FilterSpec("year", "integer", "Election year (presidential years 1976-2024).", example=2020),
        FilterSpec("year_from", "integer", "First election year (inclusive); use with year_to for a time series."),
        FilterSpec("year_to", "integer", "Last election year (inclusive)."),
        FilterSpec("state", "string", "2-letter postal code or FIPS, e.g. 'GA' or '13'.", example="GA"),
        FilterSpec("party_simplified", "string_list", "One or more of DEMOCRAT, REPUBLICAN, LIBERTARIAN, OTHER.",
                   enum=PARTY_SIMPLIFIED),
        FilterSpec("candidate", "string", "Case-insensitive substring of the candidate name as printed, e.g. 'BIDEN'."),
    ]
    contract = [
        ContractCase(
            name="georgia_2020",
            filters={"year": 2020, "state": "GA"},
            min_rows=3, max_rows=30,
            required_columns=["year", "state_po", "state_fips", "candidate", "party_simplified", "candidatevotes", "totalvotes"],
            checks=[Check("state_po", one_of=["GA"]), Check("state_fips", one_of=["13"]), Check("year", one_of=[2020]),
                    Check("candidatevotes", numeric=True, min=0, max=6_000_000),
                    Check("totalvotes", numeric=True, min=4_900_000, max=5_100_000),
                    Check("party_simplified", one_of=PARTY_SIMPLIFIED)],
            custom=_ga_2020,
        ),
        ContractCase(
            name="wyoming_republican_series",
            filters={"state": "WY", "year_from": 1976, "year_to": 2024, "party_simplified": ["REPUBLICAN"]},
            min_rows=13, max_rows=15,
            required_columns=["year", "candidate", "candidatevotes", "totalvotes"],
            checks=[Check("candidatevotes", numeric=True, min=40_000, max=200_000),
                    Check("year", numeric=True, min=1976, max=2024)],
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        rows, matched, urls, meta = fetch_medsl(DOI, FILE_PATTERN, columns=COLUMNS, predicate=year_predicate(f),
                                                limit=limit, cache_allowed=cache_allowed)
        notes = [f"MEDSL dataset {DOI}, Dataverse version {meta.get('dataverse_version')} ({meta.get('file_name')}).",
                 "state_fips zero-padded to 2 digits; vote counts converted to integers; empty cells returned as null."]
        if matched == 0:
            notes.append("No rows matched. Presidential elections are every 4 years (1976, 1980, ..., 2024).")
        return FetchResult(rows, urls, notes, total_available=matched, metadata=meta)


ADAPTER = MitElectionPresidentState()
