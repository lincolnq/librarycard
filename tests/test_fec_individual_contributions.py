"""Offline tests for fec-individual-contributions: remote-zip streaming, row parsing, and the mirror plan's
guarantee that every row of the file lands in exactly one unit. Synthetic data only (fictitious names)."""
import io
import zipfile

import httpx
import pytest

from odc import http
from odc.adapters import _common
from odc.adapters import fec_individual_contributions as fec
from odc.http import SourceError

ENTRY = {"id": "fec-individual-contributions", "name": "x", "publisher": {"name": "FEC"}, "homepage": "h",
         "status": "healthy", "license": {"name": "pd", "url": "u", "redistribution": "allowed", "commercial_use": "no",
                                          "attribution": "FEC."}}


def line(cmte, state, zipc, date, amt, sub):
    f = [cmte, "N", "Q3", "P2024", "202410159000000001", "15", "IND", "DOE, JANE", "ANYTOWN", state, zipc,
         "ACME", "ENGINEER", date, amt, "", "SA11AI.1", "1800000", "", "", sub]
    return "|".join(f)


LINES_A = [line("C00000001", "VT", "054011234", "12312022", "250", "1"),     # before the cycle -> month '2022'
           line("C00000001", "VT", "05401", "01152023", "300", "2"),
           line("C00000002", "CA", "90210", "06302024", "-50", "3")]
LINES_B = [line("C00000001", "NY", "10001", "10052024", "1000", "4"),
           line("C00000002", "VT", "05401", "10202024", "75.5", "5"),
           line("C00000002", "TX", "73301", "07012024", "500", "6"),
           line("C00000003", "", "", "01022025", "20", "7")]                 # after the cycle -> month '2025'
LINES_BAD = [line("C00000003", "VT", "05401", "", "201", "8")]


def make_zip(b_lines=LINES_B) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("itcont.txt", "\n".join(LINES_A + b_lines + LINES_BAD) + "\n")
        z.writestr("by_date/itcont_2024_20000101_20240630.txt", "\n".join(LINES_A) + "\n")
        z.writestr("by_date/itcont_2024_20240701_20250102.txt", "\n".join(b_lines))   # no trailing newline
        z.writestr("by_date/itcont_2024_invalid_dates.txt", "\n".join(LINES_BAD) + "\n")
    return buf.getvalue()


@pytest.fixture
def served(monkeypatch):
    """Serve a synthetic zip through the http helpers the adapter uses."""
    state = {"data": make_zip(), "streams": 0}

    class Head:
        url = "https://s3.example/indiv24.zip"

        @property
        def headers(self):
            return {"content-length": str(len(state["data"])), "accept-ranges": "bytes"}

    def read_range(url, start, length):
        d = state["data"]
        return d[start:start + length] if start >= 0 else d[start:]

    def iter_bytes(url, start=0, end=None, chunk=1 << 20, retries=4):
        state["streams"] += 1
        d = state["data"][start:None if end is None else end + 1]
        for i in range(0, len(d), 7):   # tiny chunks exercise header/line splitting
            yield d[i:i + 7]

    monkeypatch.setattr(http, "head", lambda url, params=None: Head())
    monkeypatch.setattr(http, "read_range", read_range)
    monkeypatch.setattr(http, "iter_bytes", iter_bytes)
    return state


def test_remote_zip_members_and_lines(served):
    url, ms = _common.remote_zip_members("https://www.fec.gov/x.zip")
    assert url == "https://s3.example/indiv24.zip"
    names = [m.name for m in ms]
    assert names[0] == "itcont.txt" and len(names) == 4
    assert list(_common.remote_zip_lines(url, ms[0])) == LINES_A + LINES_B + LINES_BAD
    assert list(_common.remote_zip_lines(url, ms[2])) == LINES_B     # last line without newline


def test_to_row_conversions():
    rec = fec.split_line(LINES_B[1], "t")
    row = fec.to_row(rec, 2024, fec.iso_date(rec[fec.I_DT]))
    assert row["TRANSACTION_DT"] == "2024-10-20" and row["TRANSACTION_AMT"] == 75.5 and row["FILE_NUM"] == 1800000
    assert row["OTHER_ID"] is None and row["SUB_ID"] == "5" and row["month"] == "2024-10" and row["cycle"] == 2024
    assert row["NAME"] == "DOE, JANE" and row["ZIP5"] == "05401"
    assert set(row) == set(fec.COLUMNS) | {"cycle", "month", "ZIP5"}
    assert fec.month_slot(2024, "2022-12-31") == "2022" and fec.month_slot(2024, None) == "unknown"
    assert fec.iso_date("02302024") is None
    with pytest.raises(SourceError):
        fec.split_line("a|b|c", "t")


def test_fetch_filters(served):
    r = fec.ADAPTER.fetch(ENTRY, {"cycle": 2024, "state": "VT"}, 10)
    assert [x["SUB_ID"] for x in r["rows"]] == ["1", "2", "5", "8"]
    assert r["notes"][0].startswith("LEGAL USE RESTRICTION (52 U.S.C. 30111(a)(4))")
    r = fec.ADAPTER.fetch(ENTRY, {"cycle": 2024, "date_from": "2024-07-01", "date_to": "2024-10-31", "min_amount": 100}, 10)
    assert [x["SUB_ID"] for x in r["rows"]] == ["4", "6"]
    assert r["metadata"]["members_read"] == ["by_date/itcont_2024_20240701_20250102.txt"]
    r = fec.ADAPTER.fetch(ENTRY, {"cycle": 2024, "committee_ids": ["c00000002"], "zip": "054"}, 10)
    assert [x["SUB_ID"] for x in r["rows"]] == ["5"]


def test_fetch_stops_early(served):
    r = fec.ADAPTER.fetch(ENTRY, {"cycle": 2024}, 1)
    assert r["row_count"] == 1 and r["truncated"]
    assert served["streams"] == 1          # only the first member was opened


def test_mirror_units_cover_every_row_once(served):
    seen = []
    keys = set()
    for unit in fec.ADAPTER.mirror_plan():
        if unit.partition["cycle"] != "2024":
            continue
        rows, urls, notes, _ = fec.ADAPTER.mirror_rows(unit)
        for row in rows:
            seen.append(row["SUB_ID"])
            key = (row["cycle"], row["month"], row["STATE"] or "")
            if "month" in unit.partition:
                assert row["month"] == unit.partition["month"]
            if unit.filters.get("state_group") == "A-M":
                assert (row["STATE"] or "") < "N"
            keys.add(key)
        assert notes[0].startswith("LEGAL USE RESTRICTION")
    assert sorted(seen) == sorted(str(i) for i in range(1, 9))     # every row exactly once
    assert (2024, "2022", "VT") in keys and (2024, "2025", None or "") in keys and (2024, "unknown", "VT") in keys


def test_mirror_rejects_rows_outside_member_range(served):
    served["data"] = make_zip(LINES_B + [line("C00000009", "VT", "05401", "03012024", "5", "9")])
    unit = next(u for u in fec.ADAPTER.mirror_plan() if u.partition.get("month") == "2024-10")
    rows, *_ = fec.ADAPTER.mirror_rows(unit)
    with pytest.raises(SourceError, match="outside the file's range"):
        list(rows)


def test_iter_bytes_resumes_after_disconnect(monkeypatch):
    data = bytes(range(256)) * 40
    calls = []

    class Flaky(httpx.SyncByteStream):
        def __init__(self, body):
            self.body = body

        def __iter__(self):
            yield self.body[:1000]
            raise httpx.ReadError("connection reset")

    def handler(request):
        rng = request.headers.get("Range")
        calls.append(rng)
        if rng is None:
            return httpx.Response(200, stream=Flaky(data))
        start = int(rng.split("=")[1].split("-")[0])
        return httpx.Response(206, content=data[start:])

    monkeypatch.setattr(http, "client", lambda timeout=None: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    assert b"".join(http.iter_bytes("https://x.example/f.zip", chunk=100)) == data
    assert calls == [None, "bytes=1000-"]
