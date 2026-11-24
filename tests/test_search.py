from odc.catalog import CatalogError

import pytest


def ids(results):
    return [r["id"] for r in results]


def test_keyword_ranking(cat):
    assert ids(cat.search("median household income tract"))[0] == "census-acs-summary-file"
    assert ids(cat.search("daily temperature heat county"))[0] == "noaa-nclimgrid-daily"


def test_filters(cat):
    assert all("disasters_emergency" in r["domains"] for r in cat.search("", domain="disasters_emergency"))
    assert "census-acs-summary-file" in ids(cat.search("", geography="tract"))
    assert "noaa-nclimgrid-daily" in ids(cat.search("", geography="Texas"))
    assert "noaa-nclimgrid-daily" not in ids(cat.search("", time_range="1900-1940"))


def test_bad_time_range(cat):
    with pytest.raises(CatalogError):
        cat.search("x", time_range="recent")


def test_summary_shape(cat):
    r = cat.search("census")[0]
    for k in ("id", "status", "fetchable", "access_method", "caveat_count"):
        assert k in r
