"""FEC "Contributions by individuals" bulk file (indivYY). Catalog: catalog/fec-individual-contributions.yaml

POLICY: served under docs/POLICY.md §Scope 3, "Exception: statutory public disclosure of political contributions".
Its guardrails are binding on this adapter:
* Serve exactly the rows FEC itemizes in the bulk file. Never add rows, never join/enrich/geocode contributor
  fields with other data, never drop FEC's "salted" (decoy) entries.
* No filters whose purpose is profiling one private person (there is deliberately no contributor-name filter here).
* The catalog entry's FIRST caveat states the 52 U.S.C. 30111(a)(4) sale-or-use restriction; every fetch repeats it
  in `notes`.
* Removals/amendments by FEC must disappear within one batch cycle: the mirror is rebuilt whenever the weekly zip
  changes (change_detection watches the current cycle's zip).

Bulk file: https://www.fec.gov/files/bulk-downloads/<CYCLE>/indiv<YY>.zip (302 -> FEC's S3 bucket
cg-519a459a-0ea3-42c2-b7bc-fa1143481f74.s3-us-gov-west-1.amazonaws.com). Several GB (2024: 4.2 GB zipped, 11 GB of
text, ~58M rows), regenerated weekly. Recent cycles' zips hold the whole file twice: `itcont.txt` and the same rows
split by transaction date into `by_date/itcont_<CYCLE>_<YYYYMMDD>_<YYYYMMDD>.txt` (inclusive ranges; adjacent files
can share a boundary day; dates outside the cycle sit in the first/last file) plus
`by_date/itcont_<CYCLE>_invalid_dates.txt` (blank or invalid dates). Older cycles have only `itcont.txt`.

Nothing is downloaded whole. The adapter reads the zip's central directory with HTTP Range requests
(`_common.remote_zip_members`) and streams only the members it needs (`_common.remote_zip_lines`), stopping as soon
as `fetch` has `limit` rows. With date_from/date_to only the by_date files covering those dates are read.

Layout: pipe-delimited, no header, no quoting, 21 columns, documented at
https://www.fec.gov/campaign-finance-data/contributions-individuals-file-description/ and in
https://www.fec.gov/files/bulk-downloads/data_dictionaries/indiv_header_file.csv (the contract test compares that
header with COLUMNS). A line with a different field count raises SourceError(schema).

Mirror (docs/MIRROR.md): partitions cycle / month (of TRANSACTION_DT) / STATE (contributor state). One mirror unit
per (cycle, month) reads the by_date files overlapping that month; out-of-cycle and invalid dates form one more unit
per cycle (month = the year "YYYY", or "unknown"). Rows are yielded from a generator, so memory stays flat.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Iterator

from .. import http
from ..http import SourceError
from ._common import RemoteZipMember, remote_zip_lines, remote_zip_members, state_abbr
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter

BASE = "https://www.fec.gov/files/bulk-downloads"
HEADER_URL = f"{BASE}/data_dictionaries/indiv_header_file.csv"
DESCRIPTION_URL = "https://www.fec.gov/campaign-finance-data/contributions-individuals-file-description/"
FIRST_CYCLE = 1980
MIRROR_CYCLES = [2024, 2026]
HEAVY_MONTHS = (8, 9, 10)  # of the election year: mirror units split by STATE_GROUPS
STATE_GROUPS = ["A-M", "N-Z"]  # first letter of STATE ("" sorts into A-M)
SCAN_ROW_CAP = 5_000_000   # direct fetch: stop scanning after this many lines without enough matches
COLUMNS = [
    "CMTE_ID", "AMNDT_IND", "RPT_TP", "TRANSACTION_PGI", "IMAGE_NUM", "TRANSACTION_TP", "ENTITY_TP", "NAME", "CITY",
    "STATE", "ZIP_CODE", "EMPLOYER", "OCCUPATION", "TRANSACTION_DT", "TRANSACTION_AMT", "OTHER_ID", "TRAN_ID",
    "FILE_NUM", "MEMO_CD", "MEMO_TEXT", "SUB_ID",
]
NCOL = len(COLUMNS)
I_CMTE, I_STATE, I_ZIP, I_DT, I_AMT, I_FILE = (COLUMNS.index(c) for c in
                                                ("CMTE_ID", "STATE", "ZIP_CODE", "TRANSACTION_DT", "TRANSACTION_AMT", "FILE_NUM"))
BY_DATE_RE = re.compile(r"^by_date/itcont_(\d{4})_(\d{8})_(\d{8})\.txt$")
INVALID_RE = re.compile(r"^by_date/itcont_(\d{4})_invalid_dates\.txt$")
USE_RESTRICTION = ("LEGAL USE RESTRICTION (52 U.S.C. 30111(a)(4)): information about individual contributors copied "
                   "from FEC reports may not be sold or used for soliciting contributions or for any commercial purpose "
                   "(committee names may be used). Committees may 'salt' their reports with fictitious contributors "
                   "to detect misuse; those decoy rows are kept exactly as FEC publishes them.")


def zip_url(cycle: int) -> str:
    return f"{BASE}/{cycle}/indiv{cycle % 100:02d}.zip"


_DATES: dict[str, str | None] = {}


def iso_date(v: str) -> str | None:
    """MMDDYYYY -> YYYY-MM-DD; None if blank or not a real date (memoised: there are only a few thousand dates)."""
    r = _DATES.get(v)
    if r is None and v not in _DATES:
        try:
            r = dt.date(int(v[4:8]), int(v[0:2]), int(v[2:4])).isoformat() if len(v) == 8 and v.isdigit() else None
        except ValueError:
            r = None
        if len(_DATES) < 200_000:
            _DATES[v] = r
    return r


def _amount(v: str):
    if v == "":
        return None
    try:
        f = float(v)
    except ValueError:
        raise SourceError(f"non-numeric TRANSACTION_AMT {v!r}", kind="parse") from None
    return int(f) if f.is_integer() else f


def split_line(line: str, where: str) -> list[str] | None:
    if not line:
        return None
    rec = line.split("|")
    if len(rec) != NCOL:
        raise SourceError(f"{where}: line has {len(rec)} fields, expected {NCOL} (layout changed? see {DESCRIPTION_URL})",
                          kind="schema")
    return rec


def to_row(rec: list[str], cycle: int, iso: str | None) -> dict:
    """FEC fields unchanged except: blanks -> null, TRANSACTION_DT -> ISO date, TRANSACTION_AMT/FILE_NUM -> numbers.
    Adds cycle, month (YYYY-MM of TRANSACTION_DT) and ZIP5 (first 5 characters of ZIP_CODE); nothing else."""
    row = {c: (v.strip() or None) for c, v in zip(COLUMNS, rec)}
    row["TRANSACTION_DT"] = iso if iso else row["TRANSACTION_DT"]
    row["TRANSACTION_AMT"] = _amount(rec[I_AMT].strip())
    fn = rec[I_FILE].strip()
    row["FILE_NUM"] = int(fn) if fn.isdigit() else (fn or None)
    row["cycle"] = cycle
    row["month"] = month_slot(cycle, iso)
    z = row["ZIP_CODE"]
    row["ZIP5"] = z[:5] if z else None
    return row


def month_slot(cycle: int, iso: str | None) -> str:
    """Mirror partition value: 'YYYY-MM' inside the two-year cycle, the year 'YYYY' for dates outside it,
    'unknown' for blank/invalid dates."""
    if not iso:
        return "unknown"
    y = int(iso[:4])
    return iso[:7] if cycle - 1 <= y <= cycle else iso[:4]


class Member:
    """One zip member with its declared transaction-date range (by_date files) or none (itcont.txt / invalid)."""

    def __init__(self, z: RemoteZipMember, start: str | None, end: str | None, invalid: bool = False):
        self.z, self.start, self.end, self.invalid = z, start, end, invalid

    def overlaps(self, lo: str | None, hi: str | None) -> bool:
        if self.invalid:
            return False
        return (hi is None or self.start <= hi) and (lo is None or self.end >= lo)


def list_members(cycle: int) -> tuple[str, str, list[Member], Member | None, Member | None]:
    """(public url, resolved url, by_date members sorted by start, invalid-dates member, itcont.txt member)."""
    url = zip_url(cycle)
    try:
        final, zs = remote_zip_members(url)
    except SourceError as e:
        if e.status in (403, 404):
            raise FilterError(f"no individual-contributions file for cycle {cycle} ({url})") from None
        raise
    by_date, invalid, full = [], None, None
    for z in zs:
        if m := BY_DATE_RE.match(z.name):
            s, e = m.group(2), m.group(3)
            by_date.append(Member(z, f"{s[:4]}-{s[4:6]}-{s[6:]}", f"{e[:4]}-{e[4:6]}-{e[6:]}"))
        elif INVALID_RE.match(z.name):
            invalid = Member(z, None, None, invalid=True)
        elif z.name.lower().endswith("itcont.txt"):
            full = Member(z, None, None)
    if not by_date and not full:
        raise SourceError(f"{url}: no itcont.txt or by_date/ members; members: {[z.name for z in zs][:10]}", kind="schema", url=url)
    by_date.sort(key=lambda m: m.start)
    return url, final, by_date, invalid, full


def member_rows(final: str, cycle: int, mem: Member) -> Iterator[tuple[list[str], str | None]]:
    """Yield (fields, iso_date) for every line of a member. For by_date members, a row dated outside the file's
    declared range raises SourceError(schema): the mirror's month units rely on those ranges to read every row once."""
    where = f"{final}!{mem.z.name}"
    check = mem.start is not None
    for line in remote_zip_lines(final, mem.z, encoding="utf-8"):
        rec = split_line(line, where)
        if rec is None:
            continue
        iso = iso_date(rec[I_DT].strip())
        if check and not (iso and mem.start <= iso <= mem.end):
            raise SourceError(f"{where}: row dated {rec[I_DT]!r} outside the file's range {mem.start}..{mem.end}; "
                              "FEC changed how by_date files are split (update the adapter's mirror plan)", kind="schema")
        yield rec, iso


def _check_header(rows: list[dict]) -> None:
    header = http.get_text(HEADER_URL).strip().splitlines()[0].split(",")
    assert [h.strip() for h in header] == COLUMNS, f"FEC header file changed: {header}"
    assert all(r["STATE"] == "VT" for r in rows)
    assert all("2024-10-01" <= r["TRANSACTION_DT"] <= "2024-10-15" for r in rows)


class FecIndividualContributions(SourceAdapter):
    source_id = "fec-individual-contributions"
    version = "1.0.0"
    usage = ("One row per itemized contribution exactly as FEC publishes it in the bulk 'contributions by individuals' "
             "file (contributors giving > $200 per cycle/year to a committee; also earmarks, refunds and memo items). "
             "`cycle` (even year) is required; narrow with committee_ids, state, zip, date_from/date_to and "
             "min_amount. Earmarked gifts appear twice (conduit such as ActBlue/WinRed, and recipient; MEMO_CD 'X'), "
             "so do not sum naively. Legal restriction: contributor information may not be used to solicit "
             "contributions or for commercial purposes (52 U.S.C. 30111(a)(4)).")
    filters = [
        FilterSpec("cycle", "integer", f"Two-year election cycle named by its even end year ({FIRST_CYCLE}-present), e.g. 2024.",
                   required=True, example=2024),
        FilterSpec("committee_ids", "string_list", "Recipient committee ids (CMTE_ID), e.g. ['C00703975'].", example=["C00703975"]),
        FilterSpec("state", "string", "Contributor's state (STATE): postal code (also AA/AE/AP, ZZ = foreign) or state FIPS.", example="VT"),
        FilterSpec("zip", "string", "Contributor ZIP code prefix (e.g. '05401' or '054').", example="05401"),
        FilterSpec("date_from", "string", "Earliest TRANSACTION_DT, YYYY-MM-DD. Date filters also make the scan much faster.",
                   example="2024-10-01"),
        FilterSpec("date_to", "string", "Latest TRANSACTION_DT, YYYY-MM-DD.", example="2024-10-31"),
        FilterSpec("min_amount", "number", "Only rows with TRANSACTION_AMT >= this many dollars.", example=1000),
    ]
    contract = [
        ContractCase(
            name="vt_early_october_2024",
            filters={"cycle": 2024, "state": "VT", "date_from": "2024-10-01", "date_to": "2024-10-15"},
            min_rows=40, max_rows=40,
            required_columns=COLUMNS + ["cycle", "month", "ZIP5"],
            checks=[Check("CMTE_ID", regex=r"C\d{8}"), Check("STATE", one_of=["VT"]),
                    Check("TRANSACTION_DT", regex=r"2024-10-(0\d|1[0-5])"), Check("month", one_of=["2024-10"]),
                    Check("TRANSACTION_AMT", numeric=True, min=-1e7, max=1e7), Check("SUB_ID", regex=r"\d{10,19}"),
                    Check("ENTITY_TP", one_of=["IND", "ORG", "CAN", "CCM", "COM", "PAC", "PTY"]),
                    Check("cycle", one_of=[2024])],
            limit=40,
            custom=_check_header,
        ),
        ContractCase(
            name="actblue_earmarks_july_2024",
            filters={"cycle": 2024, "committee_ids": ["C00401224"], "date_from": "2024-07-21", "date_to": "2024-07-22",
                     "min_amount": 100},
            min_rows=20, max_rows=20,
            required_columns=["CMTE_ID", "TRANSACTION_TP", "TRANSACTION_AMT", "MEMO_CD"],
            checks=[Check("CMTE_ID", one_of=["C00401224"]), Check("TRANSACTION_AMT", numeric=True, min=100, max=1e6),
                    Check("TRANSACTION_DT", regex=r"2024-07-2[12]")],
            limit=20,
        ),
    ]

    # ------------------------------------------------------------------ direct fetch

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        cycle = f["cycle"]
        this_year = dt.date.today().year
        if cycle % 2 or cycle < FIRST_CYCLE or cycle > this_year + 2:
            raise FilterError(f"cycle must be an even year between {FIRST_CYCLE} and {this_year + (this_year % 2)} (e.g. 2024)")
        cmtes = {c.strip().upper() for c in f.get("committee_ids") or []}
        st = None
        if f.get("state"):
            s = f["state"].strip().upper()
            st = state_abbr(s) if s.isdigit() else s
            if not re.fullmatch(r"[A-Z]{2}", st):
                raise FilterError(f"state must be a 2-letter postal code or FIPS, got {f['state']!r}")
        zp = (f.get("zip") or "").strip() or None
        lo, hi = f.get("date_from"), f.get("date_to")
        for name, v in (("date_from", lo), ("date_to", hi)):
            if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                raise FilterError(f"{name} must be YYYY-MM-DD, got {v!r}")
        min_amt = f.get("min_amount")

        url, final, by_date, invalid, full = list_members(cycle)
        members = [m for m in by_date if m.overlaps(lo, hi)] if by_date else [full]
        if by_date and not (lo or hi) and invalid:
            members.append(invalid)
        out: list[dict] = []
        scanned = 0
        capped = False
        for mem in members:
            for rec, iso in member_rows(final, cycle, mem):
                scanned += 1
                if cmtes and rec[I_CMTE] not in cmtes:
                    pass
                elif st and rec[I_STATE] != st:
                    pass
                elif zp and not rec[I_ZIP].startswith(zp):
                    pass
                elif (lo or hi) and not (iso and (lo is None or iso >= lo) and (hi is None or iso <= hi)):
                    pass
                elif min_amt is not None and (_amount(rec[I_AMT].strip()) or 0) < min_amt:
                    pass
                else:
                    out.append(to_row(rec, cycle, iso))
                    if len(out) >= limit:
                        break
                if scanned >= SCAN_ROW_CAP:
                    capped = True
                    break
            if len(out) >= limit or capped:
                break
        notes = [USE_RESTRICTION,
                 "Rows are FEC's itemized records as published (including amendments, memo entries, refunds and FEC's "
                 "salted decoy entries). Blank fields -> null; TRANSACTION_DT converted from MMDDYYYY to YYYY-MM-DD; "
                 "cycle, month and ZIP5 are derived from FEC's own fields.",
                 f"Streamed from {url} without downloading it; scanning stops once `limit` rows match."]
        if capped:
            notes.append(f"Scan stopped after {SCAN_ROW_CAP:,} lines with only {len(out)} matches: add date_from/date_to "
                         "(reads only the by_date files for those dates) or use the mirror-backed production server.")
        return FetchResult(out, [url], notes, total_available=None,
                           metadata={"cycle": cycle, "members_read": [m.z.name for m in members][:50],
                                     "lines_scanned": scanned, "column_doc": DESCRIPTION_URL})

    # ------------------------------------------------------------------ mirror

    mirror_private_columns = ["NAME", "EMPLOYER", "OCCUPATION", "MEMO_TEXT"]
    mirror_partition_keys = ["cycle", "month", "STATE"]
    mirror_semantics = {"STATE": "state_postal"}

    def mirror_plan(self):
        from ..mirror import MirrorUnit
        for cycle in MIRROR_CYCLES:
            for y in (cycle - 1, cycle):
                for mo in range(1, 13):
                    slot = f"{y}-{mo:02d}"
                    # The busiest months (up to ~9M rows in Oct 2024) are read twice, once per half of the states,
                    # so each unit finishes in a few minutes (resumable ingest checkpoints per unit).
                    groups = STATE_GROUPS if y == cycle and mo in HEAVY_MONTHS else [None]
                    for g in groups:
                        yield MirrorUnit(partition={"cycle": str(cycle), "month": slot},
                                         filters={"cycle": cycle, **({"state_group": g} if g else {})}, split_by=["STATE"])
            yield MirrorUnit(partition={"cycle": str(cycle)}, filters={"cycle": cycle},
                             split_by=["month", "STATE"])

    def mirror_rows(self, unit):
        cycle = int(unit.partition["cycle"])
        slot = unit.partition.get("month") or "other"
        group = unit.filters.get("state_group")
        url, final, by_date, invalid, _ = list_members(cycle)
        if not by_date:
            raise SourceError(f"{url} has no by_date/ members; the mirror plan needs them", kind="schema", url=url)
        if slot == "other":
            lo, hi = f"{cycle - 1}-01-01", f"{cycle}-12-31"
            members = [m for m in by_date if m.start < lo or m.end > hi] + ([invalid] if invalid else [])
        else:
            y, mo = int(slot[:4]), int(slot[5:])
            last = (dt.date(y + mo // 12, mo % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
            members = [m for m in by_date if m.overlaps(f"{slot}-01", last)]

        def gen():
            for mem in members:
                for rec, iso in member_rows(final, cycle, mem):
                    s = month_slot(cycle, iso)
                    if not ((s == slot) if slot != "other" else (s[4:5] != "-")):
                        continue
                    if group and (rec[I_STATE][:1] < "N") != (group == "A-M"):
                        continue
                    yield to_row(rec, cycle, iso)

        notes = [USE_RESTRICTION,
                 "Mirror of FEC's bulk file as published (rebuilt when FEC regenerates it, so FEC removals/amendments "
                 "propagate). Partitions: cycle, month (YYYY-MM of TRANSACTION_DT inside the cycle; 'YYYY' for dates "
                 "outside it; 'unknown' for blank/invalid dates), STATE (contributor state). Filter on all three when "
                 "you can, e.g. {cycle: 2024, month: {gte: '2024-09', lte: '2024-10'}, STATE: 'VT', CMTE_ID: ...}.",
                 f"Mirrored cycles: {', '.join(map(str, MIRROR_CYCLES))}."]
        return gen(), [url], notes, {"column_doc": DESCRIPTION_URL}


ADAPTER = FecIndividualContributions()
