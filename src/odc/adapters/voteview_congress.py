"""Voteview (UCLA) congressional roll-call data. Catalog: catalog/voteview-congress.yaml

Per-congress, per-chamber CSVs (no auth):
  https://voteview.com/static/data/out/members/<C><NNN>_members.csv     member ideology (DW-NOMINATE), ~50 KB
  https://voteview.com/static/data/out/rollcalls/<C><NNN>_rollcalls.csv roll-call descriptions, ~100-250 KB
  https://voteview.com/static/data/out/votes/<C><NNN>_votes.csv         member x roll call votes, 1-17 MB
  https://voteview.com/static/data/out/parties/HSall_parties.csv        party_code -> party_name (~60 KB)
<C> is H (House), S (Senate) or HS (both); <NNN> is the zero-padded congress number (001-119...).
HSall_* files (all congresses) are hundreds of MB and are never used here. Empty cells -> null.
Field docs: https://voteview.com/articles/data_help_{members,rollcalls,votes,parties}
Terms: none published (citation requested) → link_only, so files are streamed to temp files, never cached.
"""

from __future__ import annotations

import datetime as dt

from ..http import SourceError
from ._common import scan_csv, state_abbr
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter

BASE = "https://voteview.com/static/data/out"
PARTIES_URL = f"{BASE}/parties/HSall_parties.csv"
TABLES = {
    "members": ["congress", "chamber", "icpsr", "state_abbrev", "district_code", "party_code", "bioname", "bioguide_id",
                "nominate_dim1", "nominate_dim2"],
    "rollcalls": ["congress", "chamber", "rollnumber", "date", "yea_count", "nay_count", "bill_number", "vote_result",
                  "vote_question"],
    "votes": ["congress", "chamber", "rollnumber", "icpsr", "cast_code"],
}
CHAMBERS = {"house": "H", "senate": "S", "both": "HS"}
CAST_CODES = {"0": "Not a member", "1": "Yea", "2": "Paired Yea", "3": "Announced Yea", "4": "Announced Nay",
              "5": "Paired Nay", "6": "Nay", "7": "Present", "8": "Present", "9": "Not Voting"}
INT_COLS = {"congress", "icpsr", "state_icpsr", "district_code", "party_code", "occupancy", "last_means", "born", "died",
            "nominate_number_of_votes", "nominate_number_of_errors", "conditional", "rollnumber", "session",
            "clerk_rollnumber", "yea_count", "nay_count", "cast_code"}
FLOAT_COLS = {"nominate_dim1", "nominate_dim2", "nominate_log_likelihood", "nominate_geo_mean_probability",
              "nokken_poole_dim1", "nokken_poole_dim2", "nominate_mid_1", "nominate_mid_2", "nominate_spread_1",
              "nominate_spread_2", "prob"}


def current_congress(today: dt.date | None = None) -> int:
    """Congress in session on `today` (a new one starts Jan 3 of odd years)."""
    t = today or dt.date.today()
    y = t.year - (1 if (t.year % 2 == 0 or (t.month == 1 and t.day < 3)) else 0)
    return (y - 1789) // 2 + 1


def _convert(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if k is None:
            continue
        v = (v or "").strip()
        if v == "":
            out[k] = None
        elif k in INT_COLS:
            try:
                out[k] = int(float(v))
            except ValueError:
                out[k] = v
        elif k in FLOAT_COLS:
            try:
                out[k] = float(v)
            except ValueError:
                out[k] = v
        else:
            out[k] = v
    return out


def _check_aoc(rows: list[dict]) -> None:
    # Known fact: Alexandria Ocasio-Cortez (bioguide O000172) is among the most liberal House members (dim1 < -0.3).
    aoc = [r for r in rows if r.get("bioguide_id") == "O000172"]
    assert aoc, "O000172 missing from 116th House members"
    assert aoc[0]["nominate_dim1"] < -0.3, f"unexpected nominate_dim1 {aoc[0]['nominate_dim1']}"


class VoteviewCongress(SourceAdapter):
    source_id = "voteview-congress"
    version = "1.0.0"
    usage = ("Pick table (members = one row per member per congress with DW-NOMINATE ideology scores; rollcalls = one row "
             "per recorded vote; votes = one row per member per roll call) and a congress number (118 = 2023-2025). "
             "Join votes to members on (congress, chamber, icpsr) and to rollcalls on (congress, chamber, rollnumber). "
             "A whole-congress votes table is ~250k rows per chamber, so filter by rollnumber or icpsr. cast_code 1-3 = yea, "
             "4-6 = nay, 7-9 = present/not voting (cast_label added).")
    filters = [
        FilterSpec("table", "string", "members, rollcalls or votes.", required=True, enum=sorted(TABLES), example="members"),
        FilterSpec("congress", "integer", "Congress number, 1 (1789) to the current one (119 = 2025-2027).", required=True, example=118),
        FilterSpec("chamber", "string", "house, senate or both (default both; 'both' members also includes the President).",
                   enum=sorted(CHAMBERS), default="both"),
        FilterSpec("state", "string", "members only: 2-letter postal code (or FIPS) of the member's state.", example="CA"),
        FilterSpec("icpsr", "integer", "members/votes: Voteview/ICPSR member id (also icpsr_id in unitedstates-congress-legislators)."),
        FilterSpec("bioguide_id", "string", "members only: Bioguide id, e.g. 'O000172'."),
        FilterSpec("rollnumber", "integer", "rollcalls/votes: roll-call number within the congress and chamber (needs chamber house or senate)."),
        FilterSpec("party_code", "integer", "members only: Voteview party code (100 = Democrat, 200 = Republican, 328 = Independent)."),
    ]
    contract = [
        ContractCase(
            name="house_116_members_ideology",
            filters={"table": "members", "congress": 116, "chamber": "house"},
            min_rows=430, max_rows=460,
            required_columns=TABLES["members"] + ["party_name"],
            checks=[Check("congress", one_of=[116]), Check("chamber", one_of=["House", "President"]),
                    Check("nominate_dim1", numeric=True, min=-1, max=1), Check("bioguide_id", regex=r"[A-Z]\d{6}"),
                    Check("party_name", non_null=True)],
            limit=1000,
            custom=_check_aoc,
        ),
        ContractCase(
            name="senate_117_rollcall_1",
            filters={"table": "votes", "congress": 117, "chamber": "senate", "rollnumber": 1},
            min_rows=98, max_rows=101,
            required_columns=TABLES["votes"] + ["cast_label"],
            checks=[Check("cast_code", numeric=True, min=0, max=9), Check("rollnumber", one_of=[1]),
                    Check("chamber", one_of=["Senate"])],
            limit=200,
        ),
        ContractCase(
            name="house_118_rollcalls",
            filters={"table": "rollcalls", "congress": 118, "chamber": "house"},
            min_rows=1000,
            required_columns=TABLES["rollcalls"],
            checks=[Check("date", regex=r"20(23|24|25)-\d\d-\d\d"), Check("yea_count", numeric=True, min=0, max=435)],
            limit=2000,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        table, congress = f["table"], f["congress"]
        cur = current_congress()
        if not 1 <= congress <= cur:
            raise FilterError(f"congress must be between 1 and {cur} (the current congress)")
        prefix = CHAMBERS[f.get("chamber", "both")]
        if table != "members":
            for k in ("state", "bioguide_id", "party_code"):
                if k in f:
                    raise FilterError(f"filter '{k}' only applies to table='members'")
        if table == "members" and "rollnumber" in f:
            raise FilterError("rollnumber applies to rollcalls/votes, not members")
        if table == "rollcalls" and "icpsr" in f:
            raise FilterError("icpsr applies to members/votes; for a member's votes use table='votes'")
        if "rollnumber" in f and prefix == "HS":
            raise FilterError("rollnumber restarts in each chamber; set chamber to 'house' or 'senate'")
        url = f"{BASE}/{table}/{prefix}{congress:03d}_{table}.csv"
        st = state_abbr(f["state"]) if f.get("state") else None
        icpsr = str(f["icpsr"]) if "icpsr" in f else None
        roll = str(f["rollnumber"]) if "rollnumber" in f else None
        bio = (f.get("bioguide_id") or "").strip().upper()
        party = str(f["party_code"]) if "party_code" in f else None

        def keep(r: dict) -> bool:
            if st and r.get("state_abbrev") != st:
                return False
            if icpsr and r.get("icpsr") != icpsr:
                return False
            if roll and r.get("rollnumber") != roll:
                return False
            if bio and (r.get("bioguide_id") or "").upper() != bio:
                return False
            if party and r.get("party_code") != party:
                return False
            return True

        try:
            rows, matched = scan_csv(url, cache_allowed=cache_allowed, predicate=keep, limit=limit,
                                     transform=_convert, max_age_s=86400)
        except SourceError as e:
            if e.status == 404:
                raise FilterError(f"Voteview has no {table} file for congress {congress} / chamber {prefix} ({url})") from None
            raise
        if rows:
            missing = [c for c in TABLES[table] if c not in rows[0]]
            if missing:
                raise SourceError(f"{url}: expected columns {missing} missing; got {list(rows[0])[:30]}", kind="schema", url=url)
        urls = [url]
        notes = ["Empty cells were converted to null (e.g. nominate scores for members with too few votes, the President's "
                 "district)."]
        if table == "votes":
            for r in rows:
                r["cast_label"] = CAST_CODES.get(str(r.get("cast_code")), None)
            notes.append("cast_label added from Voteview's cast-code table: 1 Yea, 2 Paired Yea, 3 Announced Yea, "
                         "4 Announced Nay, 5 Paired Nay, 6 Nay, 7/8 Present, 9 Not Voting, 0 not a member at the time.")
        if table == "members" and rows:
            names = self._party_names(congress, cache_allowed)
            urls.append(PARTIES_URL)
            for r in rows:
                r["party_name"] = names.get((r.get("chamber"), r.get("party_code")))
            notes.append("party_name joined from HSall_parties.csv on (congress, chamber, party_code).")
        if congress == cur:
            notes.append("Current-congress files are regenerated nightly; NOMINATE scores for the current congress are "
                         "provisional and change as votes accumulate.")
        return FetchResult(rows, urls, notes, total_available=matched,
                           metadata={"table": table, "congress": congress, "file": url})

    def _party_names(self, congress: int, cache_allowed: bool) -> dict:
        try:
            rows, _ = scan_csv(PARTIES_URL, cache_allowed=cache_allowed, limit=1000,
                               predicate=lambda r: r.get("congress") == str(congress), max_age_s=86400)
        except SourceError:
            return {}
        out = {}
        for r in rows:
            try:
                out[(r["chamber"], int(float(r["party_code"])))] = r["party_name"]
            except (KeyError, ValueError):
                continue
        return out


ADAPTER = VoteviewCongress()
