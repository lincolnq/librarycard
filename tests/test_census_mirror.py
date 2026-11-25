"""Offline tests for the streaming mirror_rows of the two big Census adapters (synthetic files, no network)."""
import zipfile
from contextlib import contextmanager

import pytest

from odc import http, mirror
from odc.adapters import census_acs_summary_file as acs
from odc.adapters import census_decennial_2020_pl as pl


@pytest.fixture()
def files(monkeypatch, tmp_path):
    """Serve http.download/http.head from a {url: path} dict."""
    served: dict[str, object] = {}

    @contextmanager
    def download(url, **kw):
        if url not in served:
            raise http.SourceError(f"404 {url}", kind="http", status=404)
        yield served[url]

    def head(url, params=None):
        if url not in served:
            raise http.SourceError(f"404 {url}", kind="http", status=404)

    monkeypatch.setattr(http, "download", download)
    monkeypatch.setattr(http, "head", head)
    return served, tmp_path


def test_acs_mirror_rows(files, monkeypatch):
    served, tmp = files
    monkeypatch.setattr(acs, "latest_year", lambda ds: 2024)
    monkeypatch.setattr(acs, "MIRROR_TABLES", ["B19013", "B01003"])
    acs.CensusAcsSummaryFile._names_cache.clear()
    acs.CensusAcsSummaryFile._labels_cache.clear()
    dat = tmp / "b19013.dat"
    dat.write_text("GEO_ID|B19013_E001|B19013_M001\n0100000US|80000|100\n0400000US10|90000|-555555555\n"
                   "0500000US10001|70000|2000\n0500000US06037|85000|900\n0500001US10001|1|1\n1400000US10001040100|-666666666|5\n")
    served[acs._dat_url(2024, "5yr", "B19013")] = dat
    geos = tmp / "geos.txt"
    lines = ["GEO_ID|NAME", "0100000US|United States", "0400000US10|Delaware", "0500000US10001|Kent County, Delaware",
             "0500000US06037|Los Angeles County, California"] + [f"1400000US10001{i:06d}|Tract {i}" for i in range(1001)]
    geos.write_text("\n".join(lines) + "\n", encoding="latin-1")
    served[acs._doc_url(2024, "5yr", "geos")] = geos
    shells = tmp / "shells.txt"
    shells.write_text("Table ID|Line|Indent|Unique ID|Label|Title|Universe|Type\n"
                      "B19013|1.0|0|B19013_001|Median household income|Median Household Income|Households|int\n", encoding="latin-1")
    served[acs._doc_url(2024, "5yr", "shells")] = shells
    a = acs.ADAPTER
    units = list(a.mirror_plan())
    assert [u.partition for u in units] == [{"table": "B19013"}, {"table": "B01003"}]
    assert all(u.split_by == ["geography", "state"] for u in units)
    rows, urls, notes, meta = a.mirror_rows(units[0])
    rows = list(rows)
    assert [(r["geography"], r["state"], r["GEO_ID"]) for r in rows] == [
        ("nation", None, "0100000US"), ("state", None, "0400000US10"), ("county", "DE", "0500000US10001"),
        ("county", "CA", "0500000US06037"), ("tract", "DE", "1400000US10001040100")]
    assert rows[2]["NAME"] == "Kent County, Delaware" and rows[2]["B19013_E001"] == 70000 and rows[2]["table"] == "B19013"
    assert rows[1]["B19013_M001"] is None and rows[4]["B19013_E001"] is None  # jam values
    assert list(meta["variable_labels"]) == ["B19013_E001", "B19013_M001"]
    assert meta["variable_labels"]["B19013_E001"].startswith("Estimate: Median Household Income")
    assert meta["release"]["period"] == "2020-2024" and urls[0] == acs._dat_url(2024, "5yr", "B19013")
    # a missing table file fails the unit (the curated list must exist upstream)
    with pytest.raises(http.SourceError):
        list(a.mirror_rows(units[1])[0])


def test_acs_clean():
    assert [acs._clean(v) for v in ("12", " 7 ", "38.5", "0.45", "-666666666", "", None, "1.0", "x")] == [
        12, 7, 38.5, 0.45, None, None, None, 1.0, "x"]


def _pl_zip(path, abbr="de"):
    def geo(sumlev, logrec, county="", comp="00"):
        g = dict.fromkeys(pl.GEO_FIELDS, "")
        g.update(FILEID="PLST", STUSAB=abbr.upper(), SUMLEV=sumlev, GEOCOMP=comp, LOGRECNO=logrec, STATE="10",
                 COUNTY=county, GEOID=f"{sumlev}0000US10{county}", GEOCODE=f"10{county}", NAME=f"n{logrec}", POP100="5")
        return "|".join(g[f] for f in pl.GEO_FIELDS)

    recs = [geo("040", "0000001"), geo("050", "0000002", "001"), geo("750", "0000003", "001"),
            geo("750", "0000004", "003"), geo("050", "0000005", "003", comp="01")]
    segs = {}
    for seg, tables in pl.SEGMENT_TABLES.items():
        n = sum(len(pl.TABLES[t][1]) for t in tables)
        segs[seg] = [f"PLST|{abbr.upper()}|000|0{seg}|{r.split('|')[7]}|" + "|".join(str(i % 7) for i in range(n)) for r in recs]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{abbr}geo2020.pl", "\n".join(recs) + "\n")
        for seg, lines in segs.items():
            z.writestr(f"{abbr}0000{seg}2020.pl", "\n".join(lines) + "\n")


def test_pl_mirror_rows(files, monkeypatch):
    served, tmp = files
    monkeypatch.setattr(pl, "labels", lambda: {"P0010001": "Total:"})
    z = tmp / "de2020.pl.zip"
    _pl_zip(z)
    served[pl.zip_url("10")] = z
    a = pl.ADAPTER
    unit = next(u for u in a.mirror_plan() if u.partition == {"state": "DE"})
    rows, urls, notes, meta = a.mirror_rows(unit)
    rows = list(rows)
    # blocks (750) are not mirrored; the county component record (GEOCOMP 01) is skipped
    assert [(r["state"], r["geography"], r["GEOCODE"]) for r in rows] == [("DE", "state", "10"), ("DE", "county", "10001")]
    assert "block" not in pl.MIRROR_GEOGRAPHIES and unit.split_by == ["geography"]
    assert rows[0]["P0010001"] == 0 and rows[0]["P0050010"] == 2 and rows[0]["POP100"] == 5
    assert all(len([k for k in r if k[0] in "PH" and k[1:].isdigit()]) == 301 for r in rows)
    assert meta["variable_labels"]["P0010001"] == "Total:" and urls == [pl.zip_url("10")]


def test_pl_misaligned_segments_fail(files, monkeypatch):
    served, tmp = files
    monkeypatch.setattr(pl, "labels", lambda: {})
    z = tmp / "de2020.pl.zip"
    _pl_zip(z)
    bad = tmp / "bad.zip"  # segment 2 truncated to 2 records
    with zipfile.ZipFile(z) as src, zipfile.ZipFile(bad, "w") as dst:
        for n in src.namelist():
            data = src.read(n)
            if n == "de000022020.pl":
                data = b"\n".join(data.split(b"\n")[:2]) + b"\n"
            dst.writestr(n, data)
    served[pl.zip_url("10")] = bad
    unit = next(u for u in pl.ADAPTER.mirror_plan() if u.partition == {"state": "DE"})
    with pytest.raises(http.SourceError, match="not aligned"):
        list(pl.ADAPTER.mirror_rows(unit)[0])


def test_census_partition_keys_are_row_columns():
    for a in (acs.ADAPTER, pl.ADAPTER):
        assert set(a.mirror_required) <= set(a.mirror_partition_keys)
    assert mirror.MAX_CHUNK_BYTES <= 32_000_000
