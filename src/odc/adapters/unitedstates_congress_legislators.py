"""@unitedstates congress-legislators. Catalog: catalog/unitedstates-congress-legislators.yaml

The project maintains YAML in the `main` branch of github.com/unitedstates/congress-legislators and publishes
generated CSV/JSON on its gh-pages site:
  https://unitedstates.github.io/congress-legislators/legislators-current.csv      (~180 KB, one row per sitting member)
  https://unitedstates.github.io/congress-legislators/legislators-historical.csv   (~1.5 MB, everyone else since 1789)
  https://unitedstates.github.io/congress-legislators/committee-membership-current.csv (one row per member per (sub)committee)
Legislator CSVs flatten each person to their MOST RECENT term (type/state/district/party/url/address are from that term).
`type` is 'rep' (House incl. delegates/resident commissioner) or 'sen'. Empty strings are converted to null.
`birthday` (full date) is dropped and replaced by `birth_year` (policy: official/public identifiers only).
CC0 → cache allowed (the base class passes cache_allowed=True).
"""

from __future__ import annotations

from ..http import SourceError
from ._common import scan_csv, state_abbr
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter

BASE = "https://unitedstates.github.io/congress-legislators"
TABLES = {
    "current": f"{BASE}/legislators-current.csv",
    "historical": f"{BASE}/legislators-historical.csv",
    "committee_membership": f"{BASE}/committee-membership-current.csv",
}
LEGISLATOR_COLS = ["bioguide_id", "full_name", "last_name", "first_name", "type", "state", "district", "party"]
MEMBERSHIP_COLS = ["bioguide", "name", "committee_id", "committee_name", "party", "rank"]
CHAMBER_TYPE = {"house": "rep", "senate": "sen"}
DROP = {"birthday"}


def _clean_legislator(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if k is None or k in DROP:
            continue
        out[k] = v if v not in ("",) else None
    b = row.get("birthday") or ""
    out["birth_year"] = int(b[:4]) if b[:4].isdigit() else None
    for k in ("district", "senate_class"):
        if out.get(k) is not None and str(out[k]).lstrip("-").isdigit():
            out[k] = int(out[k])
    return out


def _clean_membership(row: dict) -> dict:
    out = {k: (v if v != "" else None) for k, v in row.items() if k is not None}
    if out.get("rank") and str(out["rank"]).isdigit():
        out["rank"] = int(out["rank"])
    return out


def _check_counts(rows: list[dict]) -> None:
    sen = sum(1 for r in rows if r["type"] == "sen")
    rep = sum(1 for r in rows if r["type"] == "rep")
    assert 95 <= sen <= 100, f"expected ~100 sitting senators, got {sen}"
    assert 420 <= rep <= 441, f"expected ~435 House members + 6 delegates, got {rep}"


class UnitedStatesCongressLegislators(SourceAdapter):
    source_id = "unitedstates-congress-legislators"
    version = "1.0.0"
    usage = ("table='current' (default) gives one row per sitting member of Congress with cross-walk ids (bioguide_id, "
             "icpsr_id, fec_ids, govtrack_id, opensecrets_id ...) and official social accounts; 'historical' covers every "
             "former member since 1789; 'committee_membership' gives one row per member per current (sub)committee. "
             "Legislator rows describe the member's MOST RECENT term only. Join to other sources on bioguide_id "
             "(e.g. voteview-congress also carries bioguide_id; icpsr_id joins Voteview's icpsr).")
    filters = [
        FilterSpec("table", "string", "Which file: current members, historical members, or current committee membership.",
                   enum=sorted(TABLES), default="current"),
        FilterSpec("state", "string", "2-letter postal code or FIPS of the member's (latest) state, e.g. 'TX'.", example="TX"),
        FilterSpec("chamber", "string", "'house' (type rep, incl. non-voting delegates) or 'senate' (type sen).", enum=sorted(CHAMBER_TYPE)),
        FilterSpec("party", "string", "Party name as published, e.g. 'Democrat', 'Republican', 'Independent' (case-insensitive). "
                   "For committee_membership this is 'majority'/'minority'.", example="Republican"),
        FilterSpec("bioguide_id", "string_list", "One or more Bioguide ids, e.g. ['C000127'].", example=["C000127"]),
        FilterSpec("name", "string", "Case-insensitive substring of the member's name (full_name / last_name; 'name' for memberships).",
                   example="Cantwell"),
        FilterSpec("committee_id", "string", "committee_membership only: Thomas committee id prefix, e.g. 'HSAG' (House "
                   "Agriculture, includes subcommittees HSAG15 ...) or 'SSFI' (Senate Finance).", example="SSFI"),
    ]
    contract = [
        ContractCase(
            name="current_full_roster",
            filters={"table": "current"},
            min_rows=525, max_rows=545,
            required_columns=LEGISLATOR_COLS + ["birth_year", "icpsr_id", "fec_ids"],
            checks=[Check("bioguide_id", regex=r"[A-Z]\d{6}"), Check("type", one_of=["rep", "sen"]),
                    Check("birth_year", numeric=True, min=1920, max=2005)],
            limit=1000,
            custom=_check_counts,
        ),
        ContractCase(
            name="historical_known_member",
            filters={"table": "historical", "bioguide_id": ["R000570"]},  # Paul Ryan, left office 2019
            min_rows=1, max_rows=1,
            required_columns=LEGISLATOR_COLS,
            checks=[Check("state", one_of=["WI"]), Check("last_name", one_of=["Ryan"]), Check("type", one_of=["rep"])],
        ),
        ContractCase(
            name="senate_finance_membership",
            filters={"table": "committee_membership", "committee_id": "SSFI"},
            min_rows=15,
            required_columns=MEMBERSHIP_COLS,
            checks=[Check("committee_id", regex=r"SSFI\d*"), Check("party", one_of=["majority", "minority"]),
                    Check("bioguide", regex=r"[A-Z]\d{6}")],
            limit=200,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        table = f.get("table", "current")
        url = TABLES[table]
        urls = [url]
        notes: list[str] = []
        ids = {i.strip().upper() for i in f.get("bioguide_id", [])}
        name = (f.get("name") or "").strip().lower()
        party = (f.get("party") or "").strip().lower()
        st = state_abbr(f["state"]) if f.get("state") else None

        if table == "committee_membership":
            if f.get("chamber"):
                raise FilterError("chamber is not supported for committee_membership; use committee_id prefix 'H'/'S'/'J' instead")
            member_state: dict[str, str] = {}
            if st:  # membership file has no state column: join it from the current roster
                cur, _ = scan_csv(TABLES["current"], cache_allowed=cache_allowed, limit=10_000, columns=["bioguide_id", "state"],
                                  max_age_s=86400)
                member_state = {r["bioguide_id"]: r["state"] for r in cur}
                urls.append(TABLES["current"])
            cid = (f.get("committee_id") or "").strip().upper()

            def keep(r: dict) -> bool:
                if cid and not (r.get("committee_id") or "").upper().startswith(cid):
                    return False
                if ids and (r.get("bioguide") or "").upper() not in ids:
                    return False
                if name and name not in (r.get("name") or "").lower():
                    return False
                if party and (r.get("party") or "").lower() != party:
                    return False
                if st and member_state.get(r.get("bioguide") or "") != st:
                    return False
                return True

            rows, matched = scan_csv(url, cache_allowed=cache_allowed, predicate=keep, limit=limit, columns=None,
                                     transform=_clean_membership, max_age_s=86400)
            if rows:
                missing = [c for c in MEMBERSHIP_COLS if c not in rows[0]]
                if missing:
                    raise SourceError(f"{url}: expected columns {missing} missing", kind="schema", url=url)
            notes.append("Current Congress committee and subcommittee assignments only; subcommittee rows have a longer "
                         "committee_id (e.g. HSAG15) and committee_subcommittee_name set. party is majority/minority side.")
            return FetchResult(rows, urls, notes, total_available=matched, metadata={"table": table})

        if f.get("committee_id"):
            raise FilterError("committee_id only applies to table='committee_membership'")
        typ = CHAMBER_TYPE.get(f.get("chamber") or "")

        def keep_leg(r: dict) -> bool:
            if ids and (r.get("bioguide_id") or "").upper() not in ids:
                return False
            if st and r.get("state") != st:
                return False
            if typ and r.get("type") != typ:
                return False
            if party and (r.get("party") or "").lower() != party:
                return False
            if name and name not in ((r.get("full_name") or "") + " " + (r.get("last_name") or "")).lower():
                return False
            return True

        rows, matched = scan_csv(url, cache_allowed=cache_allowed, predicate=keep_leg, limit=limit,
                                 transform=_clean_legislator, max_age_s=86400)
        if rows:
            missing = [c for c in LEGISLATOR_COLS if c not in rows[0]]
            if missing:
                raise SourceError(f"{url}: expected columns {missing} missing", kind="schema", url=url)
        notes.append("Each row reflects the member's most recent term only (state/district/party/type/url/address); "
                     "full term histories are in the project's YAML/JSON files.")
        notes.append("Empty fields were converted to null. The full birth date is omitted; birth_year is derived from it.")
        if table == "historical":
            notes.append("historical = every member not in the current file (since 1789); the split can lag departures by days.")
        return FetchResult(rows, urls, notes, total_available=matched, metadata={"table": table})


ADAPTER = UnitedStatesCongressLegislators()
