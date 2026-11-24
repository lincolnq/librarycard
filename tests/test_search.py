from odc.catalog import CatalogError

import pytest


def ids(results):
    return [r["id"] for r in results]


def test_keyword_ranking(cat):
    assert ids(cat.search("median household income tract"))[0] == "census-acs-summary-file"
    assert ids(cat.search("daily temperature heat county"))[0] == "noaa-nclimgrid-daily"


def test_filters(cat):
    assert all("disasters_emergency" in r["domains"] for r in cat.search("", domain="disasters_emergency", limit=100))
    assert "census-acs-summary-file" in ids(cat.search("", geography="tract", limit=100))
    assert "noaa-nclimgrid-daily" in ids(cat.search("", geography="Texas", limit=100))
    assert "noaa-nclimgrid-daily" not in ids(cat.search("", time_range="1900-1940", limit=100))


def test_bad_time_range(cat):
    with pytest.raises(CatalogError):
        cat.search("x", time_range="recent")


def test_summary_shape(cat):
    r = cat.search("census")[0]
    for k in ("id", "status", "fetchable", "access_method", "caveat_count"):
        assert k in r


# Natural-language queries an agent might send, with the source that must rank first.
# When you onboard a source, add a line here for it.
TOP1 = {
    "county presidential election results": "mit-election-county-president",
    "senate election results": "mit-election-senate-state",
    "campaign finance candidates": "fec-all-candidates",
    "unemployment rate county": "bls-laus",
    "median household income tract": "census-acs-summary-file",
    "poverty school district": "census-saipe",
    "population estimates county": "census-pep",
    "house price index": "fhfa-hpi",
    "federal spending by state": "usaspending-spending-by-geography",
    "executive orders": "federal-register-documents",
    "roll call votes ideology": "voteview-congress",
    "members of congress": "unitedstates-congress-legislators",
    "diabetes prevalence tract": "cdc-places",
    "social vulnerability": "cdc-svi",
    "school district enrollment": "urban-education-data-ccd",
    "medicare spending county": "cms-medicare-geographic-variation",
    "disaster declarations": "fema-disaster-declarations",
    "heat temperature county": "noaa-nclimgrid-daily",
    "rural urban county classification": "usda-ers-rural-urban-codes",
    "jobs by census block commuting": "lehd-lodes",
    "business establishments employment naics": "census-cbp",
    "gdp by county": "bea-regional",
    "voter turnout jurisdiction": "eac-eavs",
    "crime rates": "fbi-crime-data-explorer",
    "redistricting block population": "census-decennial-2020-pl",
    "county land area latitude longitude": "census-gazetteer",
    "county health outcomes rankings": "county-health-rankings",
}


@pytest.mark.parametrize("query,expected", sorted(TOP1.items()))
def test_top1(cat, query, expected):
    assert ids(cat.search(query, limit=3))[0] == expected
