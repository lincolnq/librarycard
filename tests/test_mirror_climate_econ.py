"""Offline tests for the mirror plans of noaa-nclimgrid-daily, bls-laus and bea-regional (synthetic publisher files)."""
import contextlib
import datetime as dt
import zipfile

import pytest

from odc.adapters import bea_regional, bls_laus, noaa_nclimgrid_daily
from odc.http import SourceError

# ------------------------------------------------------------------ nClimGrid-Daily

MAPPING = "state_name,postal_code,NCEI_code,FIPS_code\nArizona,AZ,02,04\nMaryland,MD,18,24\n"


def _ncg_file(lvl: str) -> str:
    days = ",".join(["30.5"] * 28 + ["-999.99"] * 3)
    if lvl == "ste":
        return f"ste,02,Arizona,2023,01,tmax,{days}\n"
    return f"cty,02013,AZ: Maricopa County,2023,01,tmax,{days}\ncty,18511,DC: District of Columbia,2023,01,tmax,{days}\n"


@pytest.fixture()
def ncg(monkeypatch):
    """Fake bucket: scaled files for Jan-Mar, prelim only for April, nothing later."""
    monkeypatch.setattr(noaa_nclimgrid_daily, "_ncei_to_fips", None)
    requested = []

    def fake_get_text(url, **kw):
        requested.append(url)
        if url.endswith("us-state-codes_ncei-to-fips.csv"):
            return MAPPING
        name = url.rsplit("/", 1)[1]  # tmax-202301-cty-scaled.csv
        _, ym, lvl, version = name[:-4].split("-")
        month = int(ym[4:])
        if (version == "scaled" and month <= 3) or (version == "prelim" and month == 4):
            return _ncg_file(lvl)
        raise SourceError("404", kind="http", url=url, status=404)

    monkeypatch.setattr(noaa_nclimgrid_daily.http, "get_text", fake_get_text)
    return requested


def test_ncg_plan_covers_scope():
    a = noaa_nclimgrid_daily.ADAPTER
    units = list(a.mirror_plan())
    years = {u.partition["year"] for u in units}
    assert len(units) == 4 * len(years) and min(years) == str(a.MIRROR_START_YEAR)
    assert max(years) == str(dt.date.today().year)
    assert all(set(u.split_by) | set(u.partition) == set(a.mirror_partition_keys) for u in units)
    assert a.mirror_required == ["variable", "year"]


def test_ncg_rows_record_version_and_fix_dc(ncg, monkeypatch):
    a = noaa_nclimgrid_daily.ADAPTER
    unit = next(u for u in a.mirror_plan() if u.partition == {"variable": "tmax", "year": "2023"})
    # Months 5-12 are missing: allowed only when recent, so pretend "today" is shortly after April 2023.
    monkeypatch.setattr(noaa_nclimgrid_daily.dt, "date", _FakeDate)
    rows, urls, notes, meta = a.mirror_rows(unit)
    rows = list(rows)
    assert len(urls) == 8  # 4 months x 2 levels, filled while streaming
    assert {r["version"] for r in rows if r["date"].startswith("2023-04")} == {"prelim"}
    assert {r["version"] for r in rows if r["date"] < "2023-04"} == {"scaled"}
    dc = [r for r in rows if r["region_name"].startswith("DC:")]
    assert dc and {(r["fips"], r["state"]) for r in dc} == {("11001", "DC")}
    assert all(r["year"] == 2023 for r in rows) and len(rows) == 4 * 3 * 28
    assert all(k in rows[0] for k in a.mirror_partition_keys)


def test_ncg_missing_old_month_fails(ncg):
    a = noaa_nclimgrid_daily.ADAPTER
    unit = next(u for u in a.mirror_plan() if u.partition == {"variable": "tmax", "year": "2023"})
    rows, *_ = a.mirror_rows(unit)
    with pytest.raises(Exception, match="no tmax file"):
        list(rows)


def test_ncg_mirror_retries_transient_errors(ncg, monkeypatch):
    a = noaa_nclimgrid_daily.ADAPTER
    monkeypatch.setattr(noaa_nclimgrid_daily, "RETRY_BASE_S", 0)
    real = noaa_nclimgrid_daily.http.get_text
    fails = {"n": 2}

    def flaky(url, **kw):
        if "cty" in url and fails["n"]:
            fails["n"] -= 1
            raise SourceError("ConnectError: refused", kind="network", url=url)
        return real(url, **kw)

    monkeypatch.setattr(noaa_nclimgrid_daily.http, "get_text", flaky)
    res = a._fetch_retrying({"variable": "tmax", "year": 2023, "month": 1, "level": "county", "version": "scaled"})
    assert len(res.rows) == 2 * 28 and fails["n"] == 0
    with pytest.raises(noaa_nclimgrid_daily.FilterError):  # a 404 is not retried
        a._fetch_retrying({"variable": "tmax", "year": 2023, "month": 9, "level": "county", "version": "scaled"})


class _FakeDate(dt.date):
    @classmethod
    def today(cls):
        return cls(2023, 6, 1)


# ------------------------------------------------------------------ BLS LAUS

AREA = ("area_type_code\tarea_code\tarea_text\tdisplay_level\tselectable\tsort_sequence\n"
        "A\tST1000000000000\tDelaware\t0\tT\t1\n"
        "F\tCN1000100000000\tKent County, DE\t1\tT\t2\n"
        "B\tMT4237980000000\tPhiladelphia-Camden-Wilmington, PA-NJ-DE-MD Metropolitan Statistical Area\t1\tT\t3\n")
DATA = ("series_id                     \tyear\tperiod\tvalue\tfootnote_codes\n"
        "LAUST100000000000003\t2020\tM04\t14.3\t\n"
        "LASST100000000000003\t2020\tM04\t13.9\t\n"
        "LAUCN100010000000003\t2025\tM10\t-\tX\n"
        "LAUMT423798000000003\t2020\tM04\t15.0\t\n")


@pytest.fixture()
def bls_files(tmp_path, monkeypatch):
    seen = []

    @contextlib.contextmanager
    def fake_download(url, **kw):
        seen.append(url)
        p = tmp_path / url.rsplit("/", 1)[1]
        p.write_text(AREA if url.endswith("la.area") else DATA, encoding="latin-1")
        yield p

    def no_api(*a, **kw):
        raise AssertionError("API v1 must never be called during mirror ingest")

    monkeypatch.setattr(bls_laus.http, "download", fake_download)
    monkeypatch.setattr(bls_laus.http, "request", no_api)
    monkeypatch.setattr(bls_laus.BlsLaus, "_api_fallback", no_api)
    return seen


def test_bls_plan_rows_by_area_type(bls_files):
    a = bls_laus.ADAPTER
    units = {u.partition["area_type"]: u for u in a.mirror_plan()}
    assert set(units) == set(bls_laus.MIRROR_FILES) and "city" not in units
    rows = list(a.mirror_rows(units["state"])[0])
    assert {(r["seasonal"], r["area_type"], r["state"]) for r in rows} == {("U", "state", "DE"), ("S", "state", "DE")}
    county = list(a.mirror_rows(units["county"])[0])
    assert county[0]["fips"] == "10001" and county[0]["value"] is None and county[0]["footnote_codes"] == "X"
    metro = list(a.mirror_rows(units["metro"])[0])
    assert metro[0]["state"] == "PA" and metro[0]["area_type"] == "metro"
    assert all(u.startswith(bls_laus.BASE) for u in bls_files)


def test_bls_mirror_never_falls_back_to_api(monkeypatch):
    @contextlib.contextmanager
    def refused(url, **kw):
        raise SourceError("HTTP 403", kind="http", url=url, status=403)
        yield  # pragma: no cover

    def no_api(*a, **kw):
        raise AssertionError("API v1 must never be called during mirror ingest")

    monkeypatch.setattr(bls_laus.http, "download", refused)
    monkeypatch.setattr(bls_laus.http, "request", no_api)
    a = bls_laus.ADAPTER
    unit = next(iter(a.mirror_plan()))
    with pytest.raises(SourceError) as e:
        rows, *_ = a.mirror_rows(unit)
        list(rows)
    assert e.value.status == 403


# ------------------------------------------------------------------ BEA regional

CSV = ('GeoFIPS,GeoName,Region,TableName,LineCode,IndustryClassification,Description,Unit,"2019","2020"\n'
       ' "00000", "United States", "", "CAINC1", 1, "...", "Personal income", "Thousands of dollars", 100, 200\n'
       ' "10000", "Delaware", "2", "CAINC1", 1, "...", "Personal income", "Thousands of dollars", 10, (D)\n'
       ' "10003", "New Castle, DE", "2", "CAINC1", 1, "...", "Personal income", "Thousands of dollars", 5, 6\n'
       '"Last updated: November 14, 2025-- new statistics for 2024."\n')


@pytest.fixture()
def bea_zip(tmp_path, monkeypatch):
    def make(name, members):
        p = tmp_path / f"{name}.zip"
        with zipfile.ZipFile(p, "w") as zf:
            for m in members:
                zf.writestr(m, CSV)
        return p

    zips = {"CAINC1": make("CAINC1", ["CAINC1__ALL_AREAS_2019_2020.csv", "CAINC1_DE_2019_2020.csv"]),
            "SAINC": make("SAINC", ["SAINC1__ALL_AREAS_2019_2020.csv", "SAINC5H__ALL_AREAS_1929_1957.csv",
                                    "SARPP__ALL_AREAS_2019_2020.csv"])}

    @contextlib.contextmanager
    def fake_download(url, **kw):
        yield zips[url.rsplit("/", 1)[1][:-4]]

    monkeypatch.setattr(bea_regional.http, "download", fake_download)
    monkeypatch.setattr(bea_regional, "MIRROR_ZIPS", ["CAINC1", "SAINC"])


def test_bea_mirror_tables_only_fetchable(bea_zip):
    assert bea_regional.mirror_tables() == ["CAINC1", "SAINC1", "SAINC5H"]


def test_bea_mirror_rows_stream_with_state(bea_zip):
    a = bea_regional.ADAPTER
    unit = next(u for u in a.mirror_plan() if u.partition == {"table": "CAINC1"})
    rows, urls, notes, meta = a.mirror_rows(unit)
    assert not isinstance(rows, list)
    rows = list(rows)
    assert [(r["state"], r["geo_level"], r["period"], r["value"], r["value_note"]) for r in rows] == [
        ("00", "us", "2019", 100, None), ("00", "us", "2020", 200, None),
        ("10", "state", "2019", 10, None), ("10", "state", "2020", None, "(D)"),
        ("10", "county", "2019", 5, None), ("10", "county", "2020", 6, None)]
    assert meta["last_updated"]["CAINC1"].startswith("Last updated: November 14, 2025")
    assert all(r["table"] == "CAINC1" for r in rows) and urls == [f"{bea_regional.BASE}/CAINC1.zip"]


def test_bea_fetch_unchanged_by_streaming(bea_zip):
    res = bea_regional.ADAPTER._fetch({"table": "CAINC1", "state": "DE", "geo_level": "county"}, 1, True)
    assert res.total_available == 2 and len(res.rows) == 1 and res.rows[0]["GeoFIPS"] == "10003"
    assert res.metadata["last_updated"].startswith("Last updated")
