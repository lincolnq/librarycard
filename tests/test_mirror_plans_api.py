"""Offline tests for mirror plans of API-backed sources (cdc-places, cms-medicare-geographic-variation,
urban-education-data-ccd). No network: publisher calls are monkeypatched."""
from odc.adapters import cdc_places, cms_medicare_geographic_variation as cms, urban_education_data_ccd as urban
from odc.adapters.base import FetchResult


def test_cdc_places_plan_scope():
    units = list(cdc_places.ADAPTER.mirror_plan())
    keys = {(u.partition["release"], u.partition["geography"]) for u in units}
    assert len(keys) == len(units)
    assert {(str(r), "county") for r in cdc_places.RELEASES} <= keys
    for geo in ("place", "zcta"):
        assert {(str(r), geo) for r in cdc_places.RELEASES} <= keys
    assert {r for r, g in keys if g == "tract"} == {str(r) for r in cdc_places.MIRROR_TRACT_RELEASES}
    assert all(u.split_by == ["stateabbr"] for u in units)


def test_cms_plan_and_rows(monkeypatch):
    def fake_fetch(self, f, limit, cache_allowed):
        if f["level"] == "national" and "columns" in f:
            rows = [{"YEAR": y} for y in (2014, 2015)]
            return FetchResult(rows, ["u"], total_available=len(rows))
        rows = [{"YEAR": f["year"], "BENE_GEO_LVL": cms.LEVELS[f["level"]], "BENE_GEO_CD": "10", "BENE_GEO_DESC": "DE",
                 "BENE_AGE_LVL": cms.AGES[f["age_group"]]}]
        return FetchResult(rows, ["u"], total_available=1)

    monkeypatch.setattr(cms.CmsMedicareGeographicVariation, "_fetch", fake_fetch)
    units = list(cms.ADAPTER.mirror_plan())
    assert len(units) == 6 and units[0].partition == {"BENE_GEO_LVL": "National", "YEAR": "2014"}
    rows, urls, notes, meta = cms.ADAPTER.mirror_rows(units[-1])
    assert sorted(r["BENE_AGE_LVL"] for r in rows) == ["<65", ">=65", "All"]


def test_urban_endpoint_years_and_fips_groups(monkeypatch):
    catalogue = {"results": [
        {"endpoint_id": "29", "years_available": "1991, 1994&ndash;1996"},
        {"endpoint_id": "54", "years_available": "1986&ndash;1988"},
        {"endpoint_id": "56", "years_available": "1987"},
    ]}
    directory = {"count": 5, "next": None, "results": [{"fips": 6}] * 3 + [{"fips": 10}, {"fips": 11}]}

    def fake_json(url, params):
        return catalogue if "api-endpoints" in url else directory

    monkeypatch.setattr(urban, "_cached_json", fake_json)
    monkeypatch.setattr(urban, "_YEARS", None)
    assert urban._endpoint_years() == {"finance": [1991, 1994, 1995, 1996], "directory": [1986, 1987, 1988],
                                       "enrollment": [1987]}
    assert urban._fips_groups(1994, max_rows=3) == [["6"], ["10", "11"]]
    units = list(urban.ADAPTER.mirror_plan())
    assert len(units) == 3 + 1 + 4
    rows, urls, _, _ = urban.ADAPTER.mirror_rows(units[0])
    rows = list(rows)
    assert {r["state_fips"] for r in rows} == {"06", "10", "11"} and rows[0]["dataset"] == "directory"
    monkeypatch.setattr(urban, "_YEARS", None)


def test_cdc_places_mirror_rows_pages_and_evicts(monkeypatch, tmp_path):
    import contextlib
    import json
    from odc import http
    monkeypatch.setattr(cdc_places, "MIRROR_PAGE", 2)
    monkeypatch.setattr(cdc_places, "socrata", lambda *a, **k: ([{"n": "3"}], "count-url"))
    data = [{"stateabbr": "DE", "locationid": str(i), "data_value": "1.5", ":@computed_region_x": "1"} for i in range(3)]
    evicted = []

    @contextlib.contextmanager
    def fake_download(url, params=None, **kw):
        p = tmp_path / f"page{params['$offset']}.json"
        p.write_text(json.dumps(data[params["$offset"]:params["$offset"] + params["$limit"]]))
        yield p

    monkeypatch.setattr(http, "download", fake_download)
    monkeypatch.setattr(http, "evict", lambda url, params=None: evicted.append(params["$offset"]))
    unit = next(u for u in cdc_places.ADAPTER.mirror_plan() if u.partition["geography"] == "county")
    rows, urls, notes, meta = cdc_places.ADAPTER.mirror_rows(unit)
    rows = list(rows)
    assert [r["locationid"] for r in rows] == ["0", "1", "2"] and rows[0]["data_value"] == 1.5
    assert rows[0]["geography"] == "county" and ":@computed_region_x" not in rows[0]
    assert evicted == [0, 2]
